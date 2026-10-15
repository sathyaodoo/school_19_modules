# -*- coding: utf-8 -*-
import re
from datetime import timedelta

from odoo import fields
from odoo.tests.common import HttpCase, tagged

PDF = b'%PDF-1.4\n%answer sheet\n'


@tagged('post_install', '-at_install', 'school_online_exam')
class TestAssignmentPortal(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.klass = env['school.class'].create({'name': 'AP Class', 'code': 'APC1'})
        cls.sec_a = env['school.section'].create({'name': 'A', 'class_id': cls.klass.id, 'capacity': 30})
        cls.sec_b = env['school.section'].create({'name': 'B', 'class_id': cls.klass.id, 'capacity': 30})
        year = env['school.academic.year'].create(
            {'name': 'AP Year', 'code': 'APY', 'date_start': '2026-01-01', 'date_end': '2026-12-31'})
        cls.subject = env['school.subject'].create(
            {'name': 'AP Science', 'code': 'APS', 'class_ids': [(6, 0, cls.klass.ids)]})
        cls.kid_a = env['school.student'].create({
            'name': 'AP Kid A', 'class_id': cls.klass.id, 'section_id': cls.sec_a.id, 'academic_year_id': year.id})
        cls.kid_b = env['school.student'].create({
            'name': 'AP Kid B', 'class_id': cls.klass.id, 'section_id': cls.sec_b.id, 'academic_year_id': year.id})
        portal = env.ref('base.group_portal')
        for st, login in ((cls.kid_a, 'apkida'), (cls.kid_b, 'apkidb')):
            env['res.users'].create({'name': st.name, 'login': login, 'password': login,
                                     'partner_id': st.partner_id.id, 'group_ids': [(6, 0, [portal.id])]})
        cls.work = env['school.oe.assignment'].create({
            'name': 'Portal Science Paper', 'class_id': cls.klass.id, 'section_id': cls.sec_a.id,
            'subject_id': cls.subject.id, 'max_marks': 50.0, 'instructions': 'Answer all questions.',
            'due_datetime': fields.Datetime.now() + timedelta(days=1)})
        cls.work.action_publish()
        qatt = env['ir.attachment'].create({'name': 'questions.pdf', 'raw': PDF, 'mimetype': 'application/pdf'})
        cls.work.question_attachment_ids = [(4, qatt.id)]
        cls.qatt = qatt

    def _csrf(self, html):
        m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
        self.assertTrue(m)
        return m.group(1)

    def test_student_journey_upload_submit_feedback(self):
        self.authenticate('apkida', 'apkida')
        # link from the MCQ exam page
        self.assertIn('/my/online-assignments', self.url_open('/my/online-exams').text)

        lst = self.url_open('/my/online-assignments')
        self.assertEqual(lst.status_code, 200)
        self.assertIn('Portal Science Paper', lst.text)
        page = self.url_open('/my/online-assignments/%s' % self.work.id)
        self.assertIn('Answer all questions.', page.text)
        self.assertIn('questions.pdf', page.text)
        csrf = self._csrf(page.text)

        # teacher's question paper can be downloaded
        dl = self.url_open('/my/online-assignments/%s/file/%s' % (self.work.id, self.qatt.id))
        self.assertEqual(dl.status_code, 200)
        self.assertEqual(dl.content, PDF)
        self.assertIn('attachment', dl.headers.get('Content-Disposition', ''))

        # a bad file is refused with a message, nothing is saved
        r = self.url_open('/my/online-assignments/%s/upload' % self.work.id,
                          data={'csrf_token': csrf}, files={'files': ('virus.exe', b'MZ\x90', 'application/octet-stream')})
        self.assertIn('Only PDF, JPG and PNG', r.text)
        sub = self.work._submission_for(self.kid_a)
        self.assertFalse(sub and sub.attachment_ids)

        # a real PDF is accepted
        r = self.url_open('/my/online-assignments/%s/upload' % self.work.id,
                          data={'csrf_token': csrf, 'note': 'my answers'},
                          files={'files': ('my_answers.pdf', PDF, 'application/pdf')})
        self.assertIn('Files uploaded', r.text)
        sub = self.work._submission_for(self.kid_a)
        self.assertEqual(len(sub.attachment_ids), 1)
        self.assertIn('my_answers.pdf', r.text)

        # own uploaded file downloads
        att = sub.attachment_ids[0]
        dl = self.url_open('/my/online-assignments/%s/file/%s' % (self.work.id, att.id))
        self.assertEqual(dl.content, PDF)

        # submit
        r = self.url_open('/my/online-assignments/%s/submit' % self.work.id, data={'csrf_token': csrf})
        self.assertIn('Submitted successfully', r.text)
        sub.invalidate_recordset()
        self.assertEqual(sub.state, 'submitted')
        # locked: another upload is refused
        r = self.url_open('/my/online-assignments/%s/upload' % self.work.id,
                          data={'csrf_token': csrf}, files={'files': ('x.pdf', PDF, 'application/pdf')})
        self.assertIn('already submitted', r.text)

        # teacher evaluates -> student sees marks + feedback
        sub.marks = 44.0
        sub.feedback = 'Neat handwriting, well done'
        sub.action_evaluate()
        r = self.url_open('/my/online-assignments/%s' % self.work.id)
        self.assertIn('Neat handwriting, well done', r.text)
        self.assertIn('44', r.text)

    def test_other_section_student_cannot_see_or_download(self):
        self.authenticate('apkidb', 'apkidb')          # section B, work is for section A
        lst = self.url_open('/my/online-assignments')
        self.assertNotIn('Portal Science Paper', lst.text)
        r = self.url_open('/my/online-assignments/%s' % self.work.id, allow_redirects=False)
        self.assertIn(r.status_code, (301, 302, 303))
        r = self.url_open('/my/online-assignments/%s/file/%s' % (self.work.id, self.qatt.id))
        self.assertEqual(r.status_code, 404)

    def test_student_cannot_download_other_students_file(self):
        sub = self.work._submission_for(self.kid_a, create=True)
        sub.add_files([('private.pdf', PDF)])
        att = sub.attachment_ids[0]
        # make the work visible to the whole class so kid_b passes the visibility check
        self.work.section_id = False
        self.authenticate('apkidb', 'apkidb')
        r = self.url_open('/my/online-assignments/%s/file/%s' % (self.work.id, att.id))
        self.assertEqual(r.status_code, 404)

    def test_timed_work_needs_start(self):
        self.work.duration_minutes = 5
        self.authenticate('apkida', 'apkida')
        page = self.url_open('/my/online-assignments/%s' % self.work.id)
        self.assertIn('Start', page.text)
        csrf = self._csrf(page.text)
        r = self.url_open('/my/online-assignments/%s/upload' % self.work.id,
                          data={'csrf_token': csrf}, files={'files': ('a.pdf', PDF, 'application/pdf')})
        self.assertIn('Press Start first', r.text)
        r = self.url_open('/my/online-assignments/%s/start' % self.work.id, data={'csrf_token': csrf})
        self.assertIn('oe_as_timer', r.text)
        self.assertIn('data-remaining=', r.text)
