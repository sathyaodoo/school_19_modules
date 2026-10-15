# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'school_online_exam')
class TestOnlineExam(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.klass = cls.env['school.class'].create({'name': 'OE Class', 'code': 'OEC1'})
        cls.section = cls.env['school.section'].create({'name': 'A', 'class_id': cls.klass.id, 'capacity': 30})
        cls.year = cls.env['school.academic.year'].create({
            'name': 'OE Year', 'code': 'OEY', 'date_start': '2026-01-01', 'date_end': '2026-12-31'})
        cls.subject = cls.env['school.subject'].create({
            'name': 'OE Maths', 'code': 'OEM', 'class_ids': [(6, 0, cls.klass.ids)]})
        cls.student = cls._make_student('OE Student One')
        cls.other = cls._make_student('OE Student Two')

        cls.questions = cls.env['school.oe.question']
        for i in range(1, 51):
            cls.questions |= cls.env['school.oe.question'].create({
                'name': 'Q%s' % i, 'class_id': cls.klass.id, 'subject_id': cls.subject.id,
                'option_a': 'A%s' % i, 'option_b': 'B%s' % i,
                'option_c': 'C%s' % i, 'option_d': 'D%s' % i,
                'correct_option': 'a', 'marks': 1.0,
            })
        cls.exam = cls.env['school.oe.exam'].create({
            'name': 'OE Test', 'class_id': cls.klass.id, 'subject_id': cls.subject.id,
            'questions_per_attempt': 10, 'duration_minutes': 2, 'max_attempts': 0,
            'avoid_repeat': True,
        })
        cls.exam.action_publish()

    @classmethod
    def _make_student(cls, name):
        return cls.env['school.student'].create({
            'name': name, 'class_id': cls.klass.id, 'section_id': cls.section.id,
            'academic_year_id': cls.year.id})

    def _qids(self, attempt):
        return attempt.line_ids.sorted('sequence').mapped('question_id').ids

    # --- requirement: 10 questions out of 50 -----------------------------
    def test_first_attempt_has_10_distinct_questions_from_bank(self):
        att = self.exam._start_or_resume_attempt(self.student)
        ids = self._qids(att)
        self.assertEqual(len(ids), 10)
        self.assertEqual(len(set(ids)), 10)
        self.assertTrue(set(ids) <= set(self.questions.ids))
        self.assertEqual(att.attempt_no, 1)
        self.assertEqual(att.state, 'in_progress')

    # --- requirement: 2 minute timer, server side ------------------------
    def test_deadline_is_two_minutes(self):
        att = self.exam._start_or_resume_attempt(self.student)
        self.assertEqual(att.deadline - att.start_datetime, timedelta(minutes=2))
        self.assertTrue(0 < att.remaining_seconds() <= 120)

    # --- requirement: re-login in the middle -> same attempt --------------
    def test_relogin_resumes_same_attempt_same_questions(self):
        att1 = self.exam._start_or_resume_attempt(self.student)
        ids1 = self._qids(att1)
        line = att1.line_ids[0]
        att1.save_answer(line.id, 'a')
        # "re-login" = the portal calls start/resume again
        att2 = self.exam._start_or_resume_attempt(self.student)
        self.assertEqual(att1, att2)
        self.assertEqual(self._qids(att2), ids1)
        self.assertEqual(att2.line_ids[0].selected_option, 'a')       # saved answer kept
        self.assertEqual(self.env['school.oe.attempt'].search_count(
            [('exam_id', '=', self.exam.id), ('student_id', '=', self.student.id)]), 1)

    def test_timer_not_reset_by_relogin(self):
        att = self.exam._start_or_resume_attempt(self.student)
        deadline = att.deadline
        self.exam._start_or_resume_attempt(self.student)
        self.assertEqual(att.deadline, deadline)

    # --- time over -> auto submit + new attempt ----------------------------
    def test_expired_attempt_is_auto_submitted_and_new_attempt_created(self):
        att1 = self.exam._start_or_resume_attempt(self.student)
        att1.save_answer(att1.line_ids[0].id, 'a')                 # 1 right answer
        att1.write({'deadline': fields.Datetime.now() - timedelta(minutes=1)})
        att2 = self.exam._start_or_resume_attempt(self.student)
        self.assertNotEqual(att1, att2)
        self.assertEqual(att1.state, 'auto_submitted')
        self.assertEqual(att1.score, 1.0)
        self.assertEqual(att1.total_marks, 10.0)
        self.assertEqual(att2.attempt_no, 2)
        self.assertEqual(att2.state, 'in_progress')

    def test_late_answer_is_rejected(self):
        att = self.exam._start_or_resume_attempt(self.student)
        att.write({'deadline': fields.Datetime.now() - timedelta(minutes=1)})
        res = att.save_answer(att.line_ids[0].id, 'a')
        self.assertFalse(res['ok'])
        self.assertEqual(att.state, 'auto_submitted')
        self.assertEqual(att.score, 0.0)

    def test_cron_scores_abandoned_attempts(self):
        att = self.exam._start_or_resume_attempt(self.student)
        att.write({'deadline': fields.Datetime.now() - timedelta(minutes=10)})
        self.env['school.oe.attempt']._cron_auto_submit_expired()
        self.assertEqual(att.state, 'auto_submitted')

    # --- scoring -----------------------------------------------------------
    def test_submit_scores_correct_answers(self):
        att = self.exam._start_or_resume_attempt(self.student)
        lines = att.line_ids.sorted('sequence')
        answers = {l.id: 'a' for l in lines[:7]}                    # 7 correct
        answers.update({l.id: 'b' for l in lines[7:9]})             # 2 wrong, 1 blank
        att.submit(answers=answers)
        self.assertEqual(att.state, 'submitted')
        self.assertEqual(att.score, 7.0)
        self.assertEqual(att.correct_count, 7)
        self.assertEqual(att.answered_count, 9)
        self.assertAlmostEqual(att.percentage, 70.0)
        self.assertEqual(att.result, 'pass')

    # --- requirement: next attempts --------------------------------------
    def test_five_attempts_use_all_50_questions_without_repeat(self):
        seen = []
        for _i in range(5):
            att = self.exam._start_or_resume_attempt(self.student)
            seen += self._qids(att)
            att.submit()
        self.assertEqual(sorted(seen), sorted(self.questions.ids))

    def test_ten_attempts_history(self):
        for i in range(1, 11):
            att = self.exam._start_or_resume_attempt(self.student)
            self.assertEqual(att.attempt_no, i)
            lines = att.line_ids.sorted('sequence')
            att.submit(answers={l.id: 'a' for l in lines[:i]} if i <= 10 else None)
            self.assertEqual(att.score, float(i))
        history = self.env['school.oe.attempt'].search(
            [('exam_id', '=', self.exam.id), ('student_id', '=', self.student.id)], order='attempt_no')
        self.assertEqual(history.mapped('attempt_no'), list(range(1, 11)))
        self.assertEqual(history.mapped('score'), [float(i) for i in range(1, 11)])
        for a in history:
            self.assertEqual(len(a.line_ids), 10)

    def test_students_are_independent(self):
        a1 = self.exam._start_or_resume_attempt(self.student)
        a2 = self.exam._start_or_resume_attempt(self.other)
        self.assertNotEqual(a1, a2)

    # --- attempt limit ------------------------------------------------------
    def test_max_attempts_enforced(self):
        self.exam.max_attempts = 2
        for _i in range(2):
            self.exam._start_or_resume_attempt(self.student).submit()
        with self.assertRaises(UserError):
            self.exam._start_or_resume_attempt(self.student)

    # --- score policy -------------------------------------------------------
    def test_score_policy(self):
        scores = [3, 9, 5]
        for s in scores:
            att = self.exam._start_or_resume_attempt(self.student)
            lines = att.line_ids.sorted('sequence')
            att.submit(answers={l.id: 'a' for l in lines[:s]})
        self.exam.score_policy = 'best'
        self.assertEqual(self.exam._final_attempt(self.student).score, 9.0)
        self.exam.score_policy = 'latest'
        self.assertEqual(self.exam._final_attempt(self.student).score, 5.0)
        self.exam.score_policy = 'first'
        self.assertEqual(self.exam._final_attempt(self.student).score, 3.0)

    # --- config guards -------------------------------------------------------
    def test_cannot_publish_when_bank_too_small(self):
        exam = self.env['school.oe.exam'].create({
            'name': 'Too many', 'class_id': self.klass.id, 'subject_id': self.subject.id,
            'questions_per_attempt': 60})
        with self.assertRaises(UserError):
            exam.action_publish()

    def test_history_keeps_snapshot_after_bank_edit(self):
        att = self.exam._start_or_resume_attempt(self.student)
        line = att.line_ids[0]
        text = line.question_text
        line.question_id.name = 'EDITED LATER'
        self.assertEqual(line.question_text, text)

    def test_wrong_class_student_cannot_start(self):
        other_class = self.env['school.class'].create({'name': 'Other', 'code': 'OEC2'})
        sec = self.env['school.section'].create({'name': 'B', 'class_id': other_class.id, 'capacity': 30})
        stranger = self.env['school.student'].create({
            'name': 'Stranger', 'class_id': other_class.id, 'section_id': sec.id,
            'academic_year_id': self.year.id})
        with self.assertRaises(UserError):
            self.exam._start_or_resume_attempt(stranger)

    # --- section wise exam -------------------------------------------------
    def test_section_exam_only_for_that_section(self):
        sec_b = self.env['school.section'].create(
            {'name': 'B', 'class_id': self.klass.id, 'capacity': 30})
        in_b = self.env['school.student'].create({
            'name': 'Section B Student', 'class_id': self.klass.id,
            'section_id': sec_b.id, 'academic_year_id': self.year.id})
        exam = self.env['school.oe.exam'].create({
            'name': 'Section B only', 'class_id': self.klass.id, 'section_id': sec_b.id,
            'subject_id': self.subject.id})
        exam.action_publish()
        # students are fetched from the section
        self.assertEqual(exam.student_ids, in_b)
        self.assertEqual(exam.student_count, 1)
        # section A student (self.student) is refused, section B student can start
        with self.assertRaises(UserError):
            exam._start_or_resume_attempt(self.student)
        self.assertTrue(exam._start_or_resume_attempt(in_b))

    def test_exam_without_section_is_for_whole_class(self):
        self.assertFalse(self.exam.section_id)
        self.assertIn(self.student, self.exam.student_ids)
        self.assertIn(self.other, self.exam.student_ids)
        self.assertEqual(self.exam.student_count, 2)

    # --- mock tests ---------------------------------------------------------
    def test_default_type_is_exam_and_mock_never_pushes_marks(self):
        self.assertEqual(self.exam.exam_type, 'exam')
        mock = self.env['school.oe.exam'].create({
            'name': 'Mock 1', 'exam_type': 'mock', 'class_id': self.klass.id,
            'subject_id': self.subject.id, 'show_answers': False})
        mock.action_publish()
        att = mock._start_or_resume_attempt(self.student)
        att.submit()
        self.assertEqual(att.exam_type, 'mock')                  # shows in history, tagged as mock
        with self.assertRaises(UserError):
            mock.action_send_for_approval()

    def test_mock_unlimited_attempts_and_history(self):
        mock = self.env['school.oe.exam'].create({
            'name': 'Mock 2', 'exam_type': 'mock', 'class_id': self.klass.id,
            'subject_id': self.subject.id, 'max_attempts': 0})
        mock.action_publish()
        for i in range(1, 8):
            att = mock._start_or_resume_attempt(self.student)
            self.assertEqual(att.attempt_no, i)
            att.submit()
