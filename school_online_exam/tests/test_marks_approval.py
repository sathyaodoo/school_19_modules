# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged

PDF = b'%PDF-1.4\n%x\n'


@tagged('post_install', '-at_install', 'school_online_exam')
class TestMarksApproval(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.klass = env['school.class'].create({'name': 'MA Class', 'code': 'MAC1'})
        cls.section = env['school.section'].create({'name': 'A', 'class_id': cls.klass.id, 'capacity': 30})
        cls.year = env['school.academic.year'].create(
            {'name': 'MA Year', 'code': 'MAY', 'date_start': '2026-01-01', 'date_end': '2026-12-31'})
        cls.term = env['school.academic.term'].create({
            'name': 'MA Term', 'academic_year_id': cls.year.id,
            'start_date': '2026-01-01', 'end_date': '2026-06-30'})
        cls.subject = env['school.subject'].create(
            {'name': 'MA Maths', 'code': 'MAM', 'class_ids': [(6, 0, cls.klass.ids)]})
        cls.student = env['school.student'].create({
            'name': 'MA Kid A', 'class_id': cls.klass.id, 'section_id': cls.section.id,
            'academic_year_id': cls.year.id})
        cls.kid_b = env['school.student'].create({
            'name': 'MA Kid B', 'class_id': cls.klass.id, 'section_id': cls.section.id,
            'academic_year_id': cls.year.id})
        cls.register = env['school.exam'].create({
            'name': 'MA Register Exam', 'academic_year_id': cls.year.id, 'term_id': cls.term.id,
            'exam_subject_ids': [(0, 0, {
                'subject_id': cls.subject.id, 'date': '2026-03-01', 'time_start': 9.0, 'time_end': 10.0,
                'max_marks': 50.0, 'min_marks': 20.0})]})
        for i in range(10):
            env['school.oe.question'].create({
                'name': 'MQ%s' % i, 'class_id': cls.klass.id, 'subject_id': cls.subject.id,
                'option_a': 'A', 'option_b': 'B', 'option_c': 'C', 'option_d': 'D', 'correct_option': 'a'})
        cls.exam = env['school.oe.exam'].create({
            'name': 'MA Online Exam', 'class_id': cls.klass.id, 'subject_id': cls.subject.id,
            'questions_per_attempt': 5, 'school_exam_id': cls.register.id})
        cls.exam.action_publish()
        base_user = env.ref('base.group_user')
        cls.teacher = env['res.users'].create({
            'name': 'MA Teacher', 'login': 'ma_teacher',
            'group_ids': [(6, 0, [base_user.id, env.ref('ad_school_management.group_school_teacher').id])]})
        cls.principal = env['res.users'].create({
            'name': 'MA Principal', 'login': 'ma_principal',
            'group_ids': [(6, 0, [base_user.id, env.ref('ad_school_management.group_school_principal').id])]})
        cls.Entry = env['school.oe.mark.entry']
        cls.Result = env['school.exam.result']

    def _take(self, student, correct):
        att = self.exam._start_or_resume_attempt(student)
        lines = att.line_ids.sorted('sequence')
        att.submit(answers={l.id: 'a' for l in lines[:correct]})

    def _result(self, student):
        return self.Result.search([('exam_id', '=', self.register.id), ('student_id', '=', student.id)])

    # --- the main flow ----------------------------------------------------
    def test_marks_reach_the_register_only_after_approval(self):
        self._take(self.student, 4)                       # 80 %
        self._take(self.kid_b, 5)                         # 100 %
        self.exam.action_send_for_approval()
        entries = self.Entry.search([('exam_id', '=', self.exam.id)])
        self.assertEqual(len(entries), 2)
        self.assertEqual(set(entries.mapped('state')), {'pending'})
        self.assertFalse(self._result(self.student))      # nothing in the register yet
        mine = entries.filtered(lambda e: e.student_id == self.student)
        self.assertAlmostEqual(mine.percentage, 80.0)
        self.assertAlmostEqual(mine.marks, 40.0)          # 80 % of 50
        self.assertEqual(self.exam.mark_entry_count, 2)

        entries.action_approve()
        self.assertEqual(set(entries.mapped('state')), {'approved'})
        self.assertEqual(self._result(self.student).marks_obtained, 40.0)
        self.assertEqual(self._result(self.kid_b).marks_obtained, 50.0)
        self.assertEqual(mine.result_id, self._result(self.student))
        self.assertTrue(mine.approved_datetime)

    def test_sending_again_without_change_does_nothing(self):
        self._take(self.student, 4)
        self.exam.action_send_for_approval()
        self.Entry.search([('exam_id', '=', self.exam.id)]).action_approve()
        self.exam.action_send_for_approval()
        entry = self.Entry.search([('exam_id', '=', self.exam.id)])
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.state, 'approved')         # unchanged marks: stays approved

    def test_changed_marks_need_a_new_approval(self):
        self._take(self.student, 2)                       # 40 % -> 20 marks
        self.exam.action_send_for_approval()
        entry = self.Entry.search([('exam_id', '=', self.exam.id)])
        entry.action_approve()
        self.assertEqual(self._result(self.student).marks_obtained, 20.0)
        self._take(self.student, 5)                       # better attempt: best policy -> 50 marks
        self.exam.action_send_for_approval()
        self.assertEqual(entry.state, 'pending')          # back to waiting
        self.assertEqual(entry.marks, 50.0)
        self.assertEqual(self._result(self.student).marks_obtained, 20.0)   # register still old
        entry.action_approve()
        self.assertEqual(self._result(self.student).marks_obtained, 50.0)
        self.assertEqual(len(self._result(self.student)), 1)

    def test_reject_needs_reason_and_can_be_resent(self):
        self._take(self.student, 3)
        self.exam.action_send_for_approval()
        entry = self.Entry.search([('exam_id', '=', self.exam.id)])
        with self.assertRaises(UserError):
            entry.action_reject()                         # no reason written
        entry.reject_reason = 'Re-check question 3'
        entry.action_reject()
        self.assertEqual(entry.state, 'rejected')
        self.assertFalse(self._result(self.student))
        self.exam.action_send_for_approval()              # teacher fixed it and sends again
        self.assertEqual(entry.state, 'pending')
        self.assertFalse(entry.reject_reason)

    # --- who may approve -----------------------------------------------------
    def test_teacher_cannot_approve_or_reject(self):
        self._take(self.student, 3)
        self.exam.action_send_for_approval()
        entry = self.Entry.search([('exam_id', '=', self.exam.id)])
        as_teacher = entry.with_user(self.teacher)
        with self.assertRaises(AccessError):
            as_teacher.action_approve()
        with self.assertRaises(AccessError):
            as_teacher.action_reject()
        with self.assertRaises(AccessError):
            as_teacher.write({'state': 'approved'})       # no sneaking through write
        self.assertEqual(entry.state, 'pending')
        self.assertFalse(self._result(self.student))

    def test_teacher_can_send_and_principal_can_approve(self):
        self._take(self.student, 5)
        self.exam.with_user(self.teacher).action_send_for_approval()
        entry = self.Entry.search([('exam_id', '=', self.exam.id)])
        self.assertEqual(entry.submitted_by, self.teacher)
        entry.with_user(self.principal).action_approve()
        self.assertEqual(entry.state, 'approved')
        self.assertEqual(entry.approved_by, self.principal)
        self.assertEqual(self._result(self.student).marks_obtained, 50.0)

    # --- guards --------------------------------------------------------------
    def test_needs_linked_exam_finished_attempts_and_schedule_line(self):
        self.exam.school_exam_id = False
        with self.assertRaises(UserError):
            self.exam.action_send_for_approval()
        self.exam.school_exam_id = self.register
        with self.assertRaises(UserError):                # nobody finished yet
            self.exam.action_send_for_approval()
        other_subject = self.env['school.subject'].create(
            {'name': 'MA Other', 'code': 'MAO', 'class_ids': [(6, 0, self.klass.ids)]})
        other_register = self.env['school.exam'].create({
            'name': 'MA Other Register', 'academic_year_id': self.year.id, 'term_id': self.term.id,
            'exam_subject_ids': [(0, 0, {
                'subject_id': other_subject.id, 'date': '2026-03-02', 'time_start': 9.0, 'time_end': 10.0,
                'max_marks': 50.0, 'min_marks': 20.0})]})
        self._take(self.student, 3)
        self.exam.school_exam_id = other_register         # no schedule line for this subject
        with self.assertRaises(UserError):
            self.exam.action_send_for_approval()

    def test_running_attempt_is_not_sent(self):
        self.exam._start_or_resume_attempt(self.student)  # started, never submitted
        with self.assertRaises(UserError):
            self.exam.action_send_for_approval()

    # --- assignments --------------------------------------------------------
    def test_assignment_marks_follow_the_same_approval(self):
        work = self.env['school.oe.assignment'].create({
            'name': 'MA Project', 'kind': 'project', 'class_id': self.klass.id, 'subject_id': self.subject.id,
            'max_marks': 20.0, 'school_exam_id': self.register.id,
            'due_datetime': fields.Datetime.now() + timedelta(days=1)})
        work.action_publish()
        done = work._submission_for(self.student, create=True)
        done.add_files([('a.pdf', PDF)])
        done.submit_work()
        done.marks = 15.0
        done.action_evaluate()                            # 15 / 20 = 75 % -> 37.5 of 50
        waiting = work._submission_for(self.kid_b, create=True)
        waiting.add_files([('b.pdf', PDF)])
        waiting.submit_work()                             # submitted but NOT evaluated
        work.action_send_for_approval()
        entries = self.Entry.search([('assignment_id', '=', work.id)])
        self.assertEqual(entries.mapped('student_id'), self.student)      # only the evaluated one
        self.assertEqual(entries.source, 'assignment')
        self.assertAlmostEqual(entries.marks, 37.5)
        self.assertEqual(work.mark_entry_count, 1)
        self.assertFalse(self._result(self.student))
        entries.action_approve()
        self.assertAlmostEqual(self._result(self.student).marks_obtained, 37.5)

    def test_assignment_without_evaluated_work_cannot_be_sent(self):
        work = self.env['school.oe.assignment'].create({
            'name': 'MA Empty', 'class_id': self.klass.id, 'subject_id': self.subject.id,
            'school_exam_id': self.register.id,
            'due_datetime': fields.Datetime.now() + timedelta(days=1)})
        with self.assertRaises(UserError):
            work.action_send_for_approval()
