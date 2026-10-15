# -*- coding: utf-8 -*-
import re
from datetime import timedelta

from odoo import fields
from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install', 'school_online_exam')
class TestOnlineExamPortal(HttpCase):
    """Drives the real portal pages like a browser would."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.klass = env['school.class'].create({'name': 'Portal Class', 'code': 'PCL1'})
        sec = env['school.section'].create({'name': 'A', 'class_id': cls.klass.id, 'capacity': 30})
        year = env['school.academic.year'].create({
            'name': 'P Year', 'code': 'PY', 'date_start': '2026-01-01', 'date_end': '2026-12-31'})
        cls.subject = env['school.subject'].create({
            'name': 'Portal Maths', 'code': 'PMT', 'class_ids': [(6, 0, cls.klass.ids)]})
        cls.student = env['school.student'].create({
            'name': 'Portal Kid', 'class_id': cls.klass.id, 'section_id': sec.id,
            'academic_year_id': year.id})
        for i in range(1, 51):
            env['school.oe.question'].create({
                'name': 'PQ%s' % i, 'class_id': cls.klass.id, 'subject_id': cls.subject.id,
                'option_a': 'A%s' % i, 'option_b': 'B%s' % i, 'option_c': 'C%s' % i, 'option_d': 'D%s' % i,
                'correct_option': 'a'})
        cls.exam = env['school.oe.exam'].create({
            'name': 'Portal Exam', 'class_id': cls.klass.id, 'subject_id': cls.subject.id})
        cls.exam.action_publish()
        cls.user = env['res.users'].create({
            'name': 'Portal Kid', 'login': 'portalkid', 'password': 'portalkid',
            'partner_id': cls.student.partner_id.id,
            'group_ids': [(6, 0, [env.ref('base.group_portal').id,
                                  env.ref('ad_school_management.group_school_student').id])],
        })

    def _csrf(self, html):
        m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
        self.assertTrue(m, 'csrf token not found in page')
        return m.group(1)

    def test_full_student_journey(self):
        self.authenticate('portalkid', 'portalkid')

        # portal home shows the Online Exam card
        home = self.url_open('/my')
        self.assertEqual(home.status_code, 200)
        self.assertIn('Online Exam', home.text)
        self.assertIn('/my/online-exams', home.text)

        # list page
        lst = self.url_open('/my/online-exams')
        self.assertEqual(lst.status_code, 200)
        self.assertIn('Portal Exam', lst.text)
        self.assertIn('Start Exam', lst.text)
        csrf = self._csrf(lst.text)

        # start -> redirected to the question paper with 10 questions
        resp = self.url_open('/my/online-exams/%s/start' % self.exam.id,
                             data={'csrf_token': csrf}, allow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('oe_exam_form', resp.text)
        attempt = self.env['school.oe.attempt'].search([('student_id', '=', self.student.id)])
        self.assertEqual(len(attempt), 1)
        self.assertEqual(len(attempt.line_ids), 10)
        self.assertEqual(resp.text.count('type="radio"') // 4, 10)       # 10 questions x 4 options
        self.assertIn('/school_online_exam/static/src/js/exam_timer.js', resp.text)   # timer script is on the page
        self.assertIn('data-remaining=', resp.text)
        first_ids = attempt.line_ids.sorted('sequence').mapped('question_id').ids

        # answer one question (what every radio click does)
        line = attempt.line_ids.sorted('sequence')[0]
        ans = self.url_open('/my/online-exams/attempt/%s/answer' % attempt.id,
                            data={'csrf_token': csrf, 'line_id': line.id, 'option': 'a'})
        self.assertTrue(ans.json()['ok'])
        self.assertEqual(line.selected_option, 'a')

        # leave and "log in again": new session, list shows Resume, same attempt/questions
        self.logout()
        self.authenticate('portalkid', 'portalkid')
        lst2 = self.url_open('/my/online-exams')
        self.assertIn('Resume Exam', lst2.text)
        csrf2 = self._csrf(lst2.text)
        resp2 = self.url_open('/my/online-exams/%s/start' % self.exam.id,
                              data={'csrf_token': csrf2}, allow_redirects=True)
        self.assertIn('oe_exam_form', resp2.text)
        self.assertEqual(self.env['school.oe.attempt'].search_count(
            [('student_id', '=', self.student.id)]), 1)
        self.assertEqual(attempt.line_ids.sorted('sequence').mapped('question_id').ids, first_ids)
        self.assertIn('checked', resp2.text)                              # earlier answer still ticked

        # submit
        sub = self.url_open('/my/online-exams/attempt/%s/submit' % attempt.id,
                            data={'csrf_token': csrf2, 'q_%s' % line.id: 'a'}, allow_redirects=True)
        self.assertEqual(sub.status_code, 200)
        attempt.invalidate_recordset()
        self.assertEqual(attempt.state, 'submitted')
        self.assertEqual(attempt.score, 1.0)
        self.assertIn('Review', sub.text)

        # history page + second attempt gets different questions
        hist = self.url_open('/my/online-exams/%s/history' % self.exam.id)
        self.assertEqual(hist.status_code, 200)
        self.assertIn('#1', hist.text)
        resp3 = self.url_open('/my/online-exams/%s/start' % self.exam.id,
                              data={'csrf_token': csrf2}, allow_redirects=True)
        self.assertIn('oe_exam_form', resp3.text)
        attempts = self.env['school.oe.attempt'].search(
            [('student_id', '=', self.student.id)], order='attempt_no')
        self.assertEqual(attempts.mapped('attempt_no'), [1, 2])
        q1 = set(attempts[0].line_ids.mapped('question_id').ids)
        q2 = set(attempts[1].line_ids.mapped('question_id').ids)
        self.assertFalse(q1 & q2)                                         # no repeats in round 1

    def test_expired_attempt_on_return_shows_result(self):
        self.authenticate('portalkid', 'portalkid')
        lst = self.url_open('/my/online-exams')
        csrf = self._csrf(lst.text)
        self.url_open('/my/online-exams/%s/start' % self.exam.id, data={'csrf_token': csrf})
        attempt = self.env['school.oe.attempt'].search([('student_id', '=', self.student.id)])
        attempt.write({'deadline': fields.Datetime.now() - timedelta(minutes=3)})
        page = self.url_open('/my/online-exams/attempt/%s' % attempt.id)
        self.assertEqual(page.status_code, 200)
        attempt.invalidate_recordset()
        self.assertEqual(attempt.state, 'auto_submitted')
        self.assertIn('Time was over', page.text)

    def test_other_students_attempt_is_not_accessible(self):
        other_sec = self.env['school.section'].search([('class_id', '=', self.klass.id)], limit=1)
        other = self.env['school.student'].create({
            'name': 'Other Kid', 'class_id': self.klass.id, 'section_id': other_sec.id,
            'academic_year_id': self.student.academic_year_id.id})
        att = self.exam._start_or_resume_attempt(other)
        self.authenticate('portalkid', 'portalkid')
        r = self.url_open('/my/online-exams/attempt/%s' % att.id, allow_redirects=False)
        self.assertIn(r.status_code, (301, 302, 303))                     # bounced to the list

    def test_section_exam_visible_only_to_its_section(self):
        sec_b = self.env['school.section'].create(
            {'name': 'B', 'class_id': self.klass.id, 'capacity': 30})
        exam_b = self.env['school.oe.exam'].create({
            'name': 'Only Section B Exam', 'class_id': self.klass.id, 'section_id': sec_b.id,
            'subject_id': self.subject.id})
        exam_b.action_publish()
        self.authenticate('portalkid', 'portalkid')          # portalkid is in section A
        page = self.url_open('/my/online-exams')
        self.assertIn('Portal Exam', page.text)               # whole-class exam: visible
        self.assertNotIn('Only Section B Exam', page.text)    # other section: hidden

    def test_mock_test_in_portal(self):
        mock = self.env['school.oe.exam'].create({
            'name': 'Practice Mock', 'exam_type': 'mock', 'class_id': self.klass.id,
            'subject_id': self.subject.id, 'show_answers': False, 'questions_per_attempt': 5})
        mock.action_publish()
        self.authenticate('portalkid', 'portalkid')
        lst = self.url_open('/my/online-exams')
        self.assertIn('Mock Test - practice only', lst.text)
        # real exam is listed before the mock test
        self.assertLess(lst.text.index('Portal Exam'), lst.text.index('Practice Mock'))
        csrf = self._csrf(lst.text)
        self.url_open('/my/online-exams/%s/start' % mock.id, data={'csrf_token': csrf})
        att = self.env['school.oe.attempt'].search([('exam_id', '=', mock.id)])
        res = self.url_open('/my/online-exams/attempt/%s/submit' % att.id,
                            data={'csrf_token': csrf}, allow_redirects=True)
        self.assertIn('mock test', res.text)
        self.assertIn('Review', res.text)                       # answers shown even though show_answers is off
