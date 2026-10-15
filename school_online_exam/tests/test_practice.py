# -*- coding: utf-8 -*-
import re

from odoo.exceptions import UserError
from odoo.tests.common import HttpCase, TransactionCase, tagged


def _setup(cls):
    env = cls.env
    cls.klass = env['school.class'].create({'name': 'PR Class', 'code': 'PRC1'})
    cls.section = env['school.section'].create({'name': 'A', 'class_id': cls.klass.id, 'capacity': 30})
    cls.year = env['school.academic.year'].create(
        {'name': 'PR Year', 'code': 'PRY', 'date_start': '2026-01-01', 'date_end': '2026-12-31'})
    cls.subject = env['school.subject'].create(
        {'name': 'PR Science', 'code': 'PRS', 'class_ids': [(6, 0, cls.klass.ids)]})
    cls.ch1 = env['school.oe.chapter'].create(
        {'name': 'Chapter One', 'class_id': cls.klass.id, 'subject_id': cls.subject.id})
    cls.ch2 = env['school.oe.chapter'].create(
        {'name': 'Chapter Two', 'class_id': cls.klass.id, 'subject_id': cls.subject.id})
    cls.topic = env['school.oe.topic'].create({'name': 'Topic A', 'chapter_id': cls.ch1.id})
    Q = env['school.oe.question']
    cls.q1 = Q
    for i in range(12):                                   # chapter 1: 12 questions (4 in the topic)
        cls.q1 |= Q.create({
            'name': 'C1 Q%s' % i, 'class_id': cls.klass.id, 'subject_id': cls.subject.id,
            'chapter_id': cls.ch1.id, 'topic_id': cls.topic.id if i < 4 else False,
            'option_a': 'A', 'option_b': 'B', 'option_c': 'C', 'option_d': 'D', 'correct_option': 'a'})
    cls.q2 = Q
    for i in range(8):                                    # chapter 2: 8 questions
        cls.q2 |= Q.create({
            'name': 'C2 Q%s' % i, 'class_id': cls.klass.id, 'subject_id': cls.subject.id,
            'chapter_id': cls.ch2.id,
            'option_a': 'A', 'option_b': 'B', 'option_c': 'C', 'option_d': 'D', 'correct_option': 'a'})
    cls.student = env['school.student'].create({
        'name': 'PR Kid A', 'class_id': cls.klass.id, 'section_id': cls.section.id,
        'academic_year_id': cls.year.id})
    cls.other = env['school.student'].create({
        'name': 'PR Kid B', 'class_id': cls.klass.id, 'section_id': cls.section.id,
        'academic_year_id': cls.year.id})


@tagged('post_install', '-at_install', 'school_online_exam')
class TestPractice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _setup(cls)
        cls.no_chapter = cls.env['school.oe.chapter']
        cls.no_topic = cls.env['school.oe.topic']
        cls.Exam = cls.env['school.oe.exam']

    def _practice(self, student=None, chapter=None, topic=None, n=5):
        return self.Exam._practice_exam_for(
            student or self.student, self.subject,
            chapter if chapter is not None else self.no_chapter,
            topic if topic is not None else self.no_topic, n)

    def test_session_is_reused_and_has_expected_settings(self):
        e1 = self._practice(chapter=self.ch1)
        e2 = self._practice(chapter=self.ch1)
        self.assertEqual(e1, e2)
        self.assertNotEqual(e1, self._practice(chapter=self.ch1, n=10))
        self.assertNotEqual(e1, self._practice(chapter=self.ch2))
        self.assertNotEqual(e1, self._practice(chapter=self.ch1, topic=self.topic))
        self.assertEqual((e1.exam_type, e1.state, e1.max_attempts, e1.duration_minutes), ('practice', 'published', 0, 5))
        self.assertTrue(e1.show_answers)
        self.assertEqual(e1.practice_student_id, self.student)
        self.assertEqual(e1.pool_count, 12)

    def test_questions_come_only_from_the_chosen_chapter_or_topic(self):
        att = self._practice(chapter=self.ch2).sudo()._start_or_resume_attempt(self.student)
        self.assertEqual(len(att.line_ids), 5)
        self.assertEqual(att.line_ids.mapped('question_id.chapter_id'), self.ch2)
        att2 = self._practice(chapter=self.ch1, topic=self.topic, n=4)._start_or_resume_attempt(self.student)
        self.assertEqual(set(att2.line_ids.mapped('question_id.topic_id.id')), {self.topic.id})

    def test_whole_subject_uses_all_chapters(self):
        exam = self._practice(n=20)
        self.assertEqual(exam.pool_count, 20)
        att = exam._start_or_resume_attempt(self.student)
        self.assertEqual(len(att.line_ids), 20)

    def test_unseen_questions_first_across_sessions(self):
        exam = self._practice(chapter=self.ch1, n=5)
        seen = []
        for _i in range(2):
            att = exam._start_or_resume_attempt(self.student)
            seen += att.line_ids.mapped('question_id').ids
            att.submit()
        self.assertEqual(len(set(seen)), 10)                  # no repeat in the first two rounds
        att3 = exam._start_or_resume_attempt(self.student)
        ids3 = set(att3.line_ids.mapped('question_id').ids)
        self.assertTrue((set(self.q1.ids) - set(seen)) <= ids3)  # the 2 never-seen ones come first

    def test_practice_belongs_to_one_student(self):
        exam = self._practice(chapter=self.ch1)
        with self.assertRaises(UserError):
            exam._start_or_resume_attempt(self.other)
        self.assertNotEqual(self._practice(student=self.other, chapter=self.ch1), exam)

    def test_practice_is_never_counted_in_marks_register(self):
        exam = self._practice(chapter=self.ch1)
        with self.assertRaises(UserError):
            exam.action_send_for_approval()

    def test_practice_settings_open_by_default_and_can_be_closed(self):
        Setting = self.env['school.oe.practice.setting']
        self.assertTrue(Setting.is_practice_open(self.klass, self.subject))
        Setting.create({'class_id': self.klass.id, 'subject_id': self.subject.id, 'practice_enabled': False})
        self.assertFalse(Setting.is_practice_open(self.klass, self.subject))


@tagged('post_install', '-at_install', 'school_online_exam')
class TestPracticePortal(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _setup(cls)
        portal = cls.env.ref('base.group_portal')
        for st, login in ((cls.student, 'prkida'), (cls.other, 'prkidb')):
            cls.env['res.users'].create({
                'name': st.name, 'login': login, 'password': login,
                'partner_id': st.partner_id.id, 'group_ids': [(6, 0, [portal.id])]})
        # a normal published exam: its "Start" form gives a CSRF token on /my/online-exams
        cls.regular = cls.env['school.oe.exam'].create({
            'name': 'PR Regular Exam', 'class_id': cls.klass.id, 'subject_id': cls.subject.id})
        cls.regular.action_publish()

    def _csrf(self, html):
        m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
        self.assertTrue(m)
        return m.group(1)

    def test_student_practises_a_chapter(self):
        self.authenticate('prkida', 'prkida')
        self.assertIn('/my/online-practice', self.url_open('/my/online-exams').text)
        page = self.url_open('/my/online-practice')
        self.assertEqual(page.status_code, 200)
        for text in ('PR Science', 'Whole subject', 'Chapter One', 'Chapter Two', 'Topic A', 'No practice sessions yet'):
            self.assertIn(text, page.text)
        csrf = self._csrf(page.text)

        res = self.url_open('/my/online-practice/start', allow_redirects=True, data={
            'csrf_token': csrf, 'subject_id': self.subject.id, 'chapter_id': self.ch2.id,
            'topic_id': 0, 'n': 5})
        self.assertIn('oe_exam_form', res.text)
        self.assertEqual(res.text.count('type="radio"'), 5 * 4)
        att = self.env['school.oe.attempt'].search([('student_id', '=', self.student.id)])
        self.assertEqual(att.exam_id.exam_type, 'practice')
        self.assertEqual(att.line_ids.mapped('question_id.chapter_id'), self.ch2)

        sub = self.url_open('/my/online-exams/attempt/%s/submit' % att.id,
                            data={'csrf_token': csrf}, allow_redirects=True)
        self.assertIn('self-practice', sub.text)
        self.assertIn('Review', sub.text)

        page = self.url_open('/my/online-practice')
        self.assertIn('Practice: PR Science / Chapter Two (5 questions)', page.text)
        self.assertNotIn('No practice sessions yet', page.text)
        # a practice session never appears in the normal exam list
        self.assertNotIn('Practice: PR Science', self.url_open('/my/online-exams').text)

    def test_other_student_cannot_use_my_practice_session(self):
        exam = self.env['school.oe.exam']._practice_exam_for(
            self.student, self.subject, self.ch1, self.env['school.oe.topic'], 5)
        self.authenticate('prkidb', 'prkidb')
        csrf = self._csrf(self.url_open('/my/online-exams').text)
        res = self.url_open('/my/online-exams/%s/start' % exam.id, data={'csrf_token': csrf})
        self.assertIn('belongs to another student', res.text)
        self.assertFalse(self.env['school.oe.attempt'].search([('student_id', '=', self.other.id)]))

    def test_closed_subject_and_bad_input(self):
        self.env['school.oe.practice.setting'].create(
            {'class_id': self.klass.id, 'subject_id': self.subject.id, 'practice_enabled': False})
        self.authenticate('prkida', 'prkida')
        page = self.url_open('/my/online-practice')
        self.assertNotIn('Whole subject', page.text)
        csrf = self._csrf(self.url_open('/my/online-exams').text)
        res = self.url_open('/my/online-practice/start', allow_redirects=True, data={
            'csrf_token': csrf, 'subject_id': self.subject.id, 'chapter_id': 0, 'topic_id': 0, 'n': 5})
        self.assertIn('not open', res.text)
        res = self.url_open('/my/online-practice/start', allow_redirects=True, data={
            'csrf_token': csrf, 'subject_id': 'abc', 'n': 'x'})
        self.assertIn('Invalid choice', res.text)
