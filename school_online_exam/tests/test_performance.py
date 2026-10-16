# -*- coding: utf-8 -*-
from odoo.tests.common import HttpCase, TransactionCase, tagged

from .test_practice import _setup


def _take(exam, student, correct):
    """One finished attempt where the first `correct` questions are answered right."""
    att = exam._start_or_resume_attempt(student)
    lines = att.line_ids.sorted('sequence')
    att.submit(answers={l.id: 'a' for l in lines[:correct]})
    return att


def _make_data(cls):
    Exam = cls.env['school.oe.exam']
    mk = lambda name, chapter, n: Exam.create({            # noqa: E731
        'name': name, 'class_id': cls.klass.id, 'subject_id': cls.subject.id,
        'chapter_ids': [(6, 0, chapter.ids)], 'questions_per_attempt': n})
    cls.exam1 = mk('PF Exam Ch1', cls.ch1, 5)
    cls.exam2 = mk('PF Exam Ch2', cls.ch2, 4)
    cls.exam3 = mk('PF Exam Ch2 short', cls.ch2, 2)
    for e in (cls.exam1, cls.exam2, cls.exam3):
        e.action_publish()
    # student: ch1 3/5 + 1/5 (= 4 of 10 -> 40 %), ch2 4/4 (= 100 %)
    _take(cls.exam1, cls.student, 3)
    _take(cls.exam1, cls.student, 1)
    _take(cls.exam2, cls.student, 4)
    # other student: ch1 5/5, ch2 0/2 (only 2 questions answered)
    _take(cls.exam1, cls.other, 5)
    _take(cls.exam3, cls.other, 0)


@tagged('post_install', '-at_install', 'school_online_exam')
class TestPerformance(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _setup(cls)
        _make_data(cls)
        cls.Attempt = cls.env['school.oe.attempt']
        cls.Line = cls.env['school.oe.attempt.line']

    def test_student_summary(self):
        d = self.Attempt._performance_data(self.student)
        self.assertEqual(d['attempts'], 3)
        self.assertAlmostEqual(d['avg'], 60.0)                   # (60 + 20 + 100) / 3
        self.assertAlmostEqual(d['best'], 100.0)
        types = {t['key']: t for t in d['by_type']}
        self.assertEqual(types['exam']['count'], 3)
        self.assertEqual(types['mock']['count'], 0)
        self.assertEqual(len(d['trend']), 3)

    def test_subject_vs_class_average(self):
        d = self.Attempt._performance_data(self.student)
        self.assertEqual(len(d['subjects']), 1)
        row = d['subjects'][0]
        self.assertEqual(row['subject'], self.subject)
        self.assertAlmostEqual(row['avg'], 60.0)
        # class: 60, 20, 100 (student) + 100, 0 (other) -> 56
        self.assertAlmostEqual(row['class_avg'], 56.0)

    def test_chapter_accuracy_and_weak_areas(self):
        d = self.Attempt._performance_data(self.student)
        by_chapter = {c['chapter'].id: c for c in d['chapters']}
        self.assertAlmostEqual(by_chapter[self.ch1.id]['accuracy'], 40.0)
        self.assertEqual(by_chapter[self.ch1.id]['count'], 10)
        self.assertTrue(by_chapter[self.ch1.id]['weak'])
        self.assertAlmostEqual(by_chapter[self.ch2.id]['accuracy'], 100.0)
        self.assertFalse(by_chapter[self.ch2.id]['weak'])
        self.assertEqual([c['chapter'] for c in d['chapters']], [self.ch1, self.ch2])   # weakest first
        self.assertEqual([c['chapter'] for c in d['weak']], [self.ch1])

    def test_too_few_answers_is_not_called_weak(self):
        d = self.Attempt._performance_data(self.other)
        ch2 = [c for c in d['chapters'] if c['chapter'] == self.ch2][0]
        self.assertAlmostEqual(ch2['accuracy'], 0.0)
        self.assertEqual(ch2['count'], 2)
        self.assertFalse(ch2['weak'])                            # only 2 questions: not enough to judge
        self.assertEqual(d['weak'], [])

    def test_running_attempt_is_not_counted(self):
        before = self.Attempt._performance_data(self.student)
        self.exam2._start_or_resume_attempt(self.student)         # started, not submitted
        after = self.Attempt._performance_data(self.student)
        self.assertEqual(before['attempts'], after['attempts'])
        self.assertEqual(before['chapters'], after['chapters'])

    def test_report_fields_for_pivot_and_graph(self):
        line = self.Line.search([('student_id', '=', self.student.id)], limit=1)
        self.assertTrue(line.chapter_id and line.subject_id and line.class_id and line.exam_type)
        self.assertEqual(line.attempt_state, 'submitted')
        for l in self.Line.search([('student_id', '=', self.student.id)]):
            self.assertEqual(l.accuracy, 100.0 if l.is_correct else 0.0)
        # what the chapter pivot / graph computes
        rows = self.Line._read_group(
            [('student_id', '=', self.student.id), ('attempt_state', '!=', 'in_progress')],
            ['chapter_id'], ['accuracy:avg'])
        self.assertEqual({c.id: round(a) for c, a in rows}, {self.ch1.id: 40, self.ch2.id: 100})
        # what the student pivot computes (average of percentage)
        rows = self.Attempt._read_group(
            [('student_id', '=', self.student.id), ('state', '!=', 'in_progress')],
            ['subject_id'], ['percentage:avg'])
        self.assertEqual([round(a) for _s, a in rows], [60])

    def test_question_difficulty_report(self):
        rows = self.Line._read_group(
            [('attempt_state', '!=', 'in_progress')], ['question_id'], ['accuracy:avg', '__count'])
        self.assertTrue(rows)
        for question, accuracy, count in rows:
            self.assertTrue(0.0 <= accuracy <= 100.0)
            self.assertGreaterEqual(count, 1)


@tagged('post_install', '-at_install', 'school_online_exam')
class TestPerformancePortal(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _setup(cls)
        portal = cls.env.ref('base.group_portal')
        for st, login in ((cls.student, 'pfkida'), (cls.other, 'pfkidb')):
            cls.env['res.users'].create({
                'name': st.name, 'login': login, 'password': login,
                'partner_id': st.partner_id.id, 'group_ids': [(6, 0, [portal.id])]})

    def test_empty_report(self):
        self.authenticate('pfkida', 'pfkida')
        page = self.url_open('/my/online-performance')
        self.assertEqual(page.status_code, 200)
        self.assertIn('No finished attempts yet', page.text)

    def test_report_page(self):
        _make_data(self)
        self.authenticate('pfkida', 'pfkida')
        self.assertIn('/my/online-performance', self.url_open('/my/online-exams').text)
        page = self.url_open('/my/online-performance')
        self.assertEqual(page.status_code, 200)
        for text in ('My Performance', 'PR Science', 'Chapter One', 'Chapter Two', 'Weak',
                     'Needs more practice', '40%', '100%', 'Class', 'Last 3 attempts'):
            self.assertIn(text, page.text)
        # the other student's report does not mix in
        self.authenticate('pfkidb', 'pfkidb')
        other = self.url_open('/my/online-performance')
        self.assertNotIn('Needs more practice', other.text)
