# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

PDF = b'%PDF-1.4\n%answer sheet\n'
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 20


@tagged('post_install', '-at_install', 'school_online_exam')
class TestAssignment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.klass = env['school.class'].create({'name': 'AS Class', 'code': 'ASC1'})
        cls.sec_a = env['school.section'].create({'name': 'A', 'class_id': cls.klass.id, 'capacity': 30})
        cls.sec_b = env['school.section'].create({'name': 'B', 'class_id': cls.klass.id, 'capacity': 30})
        cls.year = env['school.academic.year'].create(
            {'name': 'AS Year', 'code': 'ASY', 'date_start': '2026-01-01', 'date_end': '2026-12-31'})
        cls.subject = env['school.subject'].create(
            {'name': 'AS Science', 'code': 'ASS', 'class_ids': [(6, 0, cls.klass.ids)]})
        cls.student = env['school.student'].create({
            'name': 'AS Kid A', 'class_id': cls.klass.id, 'section_id': cls.sec_a.id,
            'academic_year_id': cls.year.id})
        cls.kid_b = env['school.student'].create({
            'name': 'AS Kid B', 'class_id': cls.klass.id, 'section_id': cls.sec_b.id,
            'academic_year_id': cls.year.id})
        cls.assignment = env['school.oe.assignment'].create({
            'name': 'Science Answer Paper', 'kind': 'descriptive', 'class_id': cls.klass.id,
            'subject_id': cls.subject.id, 'max_marks': 50.0,
            'due_datetime': fields.Datetime.now() + timedelta(days=1)})
        cls.assignment.action_publish()

    def _sub(self):
        return self.assignment._submission_for(self.student, create=True)

    def test_upload_submit_evaluate(self):
        sub = self._sub()
        self.assertEqual(sub.add_files([('ans1.pdf', PDF), ('page2.png', PNG)]), 2)
        self.assertEqual(sub.file_count, 2)
        sub.submit_work(note='done')
        self.assertEqual(sub.state, 'submitted')
        self.assertFalse(sub.is_late)
        with self.assertRaises(UserError):                        # locked after submit
            sub.add_files([('more.pdf', PDF)])
        sub.marks = 42.0
        sub.feedback = 'Good, improve diagrams'
        sub.action_evaluate()
        self.assertEqual(sub.state, 'evaluated')
        self.assertEqual(sub.evaluated_by, self.env.user)
        self.assertTrue(sub.evaluated_datetime)

    def test_marks_must_be_within_max(self):
        sub = self._sub()
        sub.add_files([('a.pdf', PDF)])
        sub.submit_work()
        with self.assertRaises(ValidationError):
            sub.marks = 51.0
        with self.assertRaises(ValidationError):
            sub.marks = -1.0

    def test_bad_files_are_rejected_and_nothing_is_saved(self):
        sub = self._sub()
        for name, data in [('virus.exe', b'MZ\x90\x00'), ('fake.pdf', b'MZ not a pdf'),
                           ('empty.png', b''), ('notes.txt', b'hello')]:
            with self.assertRaises(UserError):
                sub.add_files([(name, data)])
        with self.assertRaises(UserError):                         # one bad file blocks the batch
            sub.add_files([('ok.pdf', PDF), ('bad.exe', b'MZ')])
        self.assertEqual(sub.file_count, 0)

    def test_too_many_and_too_big(self):
        sub = self._sub()
        with self.assertRaises(UserError):
            sub.add_files([('f%s.pdf' % i, PDF) for i in range(11)])
        with self.assertRaises(UserError):
            sub.add_files([('big.pdf', b'%PDF-' + b'0' * (5 * 1024 * 1024 + 1))])

    def test_submit_needs_a_file(self):
        with self.assertRaises(UserError):
            self._sub().submit_work()

    def test_remove_file(self):
        sub = self._sub()
        sub.add_files([('a.pdf', PDF), ('b.pdf', PDF)])
        sub.remove_file(sub.attachment_ids[0].id)
        self.assertEqual(sub.file_count, 1)

    def test_late_not_allowed_then_allowed(self):
        self.assignment.due_datetime = fields.Datetime.now() - timedelta(hours=1)
        sub = self._sub()
        self.assertFalse(sub.is_open())
        with self.assertRaises(UserError):
            sub.add_files([('a.pdf', PDF)])
        self.assignment.allow_late = True
        self.assertTrue(sub.is_open())
        sub.add_files([('a.pdf', PDF)])
        sub.submit_work()
        self.assertTrue(sub.is_late)

    def test_timed_work_deadline(self):
        self.assignment.duration_minutes = 10
        sub = self._sub()
        self.assertTrue(sub.is_open())
        self.assertLessEqual(sub.remaining_seconds(), 600)
        self.assertGreater(sub.remaining_seconds(), 590)
        sub.started_datetime = fields.Datetime.now() - timedelta(minutes=20)   # 10 min limit passed
        self.assertEqual(sub.remaining_seconds(), 0)
        self.assertFalse(sub.is_open())

    def test_timer_never_goes_past_due_date(self):
        self.assignment.duration_minutes = 600                                  # 10 hours
        self.assignment.due_datetime = fields.Datetime.now() + timedelta(minutes=30)
        sub = self._sub()
        self.assertLessEqual(sub.remaining_seconds(), 30 * 60)

    def test_return_to_student_allows_resubmit(self):
        sub = self._sub()
        sub.add_files([('a.pdf', PDF)])
        sub.submit_work()
        sub.action_return_to_student()
        self.assertEqual(sub.state, 'draft')
        sub.add_files([('b.pdf', PDF)])
        sub.submit_work()
        self.assertEqual(sub.state, 'submitted')

    def test_section_visibility(self):
        sec_b_work = self.env['school.oe.assignment'].create({
            'name': 'Only B', 'class_id': self.klass.id, 'section_id': self.sec_b.id,
            'subject_id': self.subject.id, 'due_datetime': fields.Datetime.now() + timedelta(days=1)})
        sec_b_work.action_publish()
        self.assertTrue(sec_b_work._visible_for(self.kid_b))
        self.assertFalse(sec_b_work._visible_for(self.student))
        self.assertTrue(self.assignment._visible_for(self.student))      # whole class
        self.assertEqual(sec_b_work.student_ids, self.kid_b)

    def test_draft_assignment_not_visible(self):
        self.assignment.action_draft()
        self.assertFalse(self.assignment._visible_for(self.student))
