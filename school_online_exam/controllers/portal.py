# -*- coding: utf-8 -*-
from odoo import fields, http, _
from odoo.exceptions import UserError
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal


class OnlineExamPortal(CustomerPortal):

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _oe_students(self):
        """(students, is_parent). A student login sees only himself;
        a parent login sees the linked children (read-only)."""
        partner = request.env.user.partner_id
        Student = request.env['school.student'].sudo()
        own = Student.search([('partner_id', '=', partner.id)])
        if own:
            return own, False
        kids = Student.search([('parent_ids.partner_id', '=', partner.id)])
        return kids, bool(kids)

    def _oe_pick_student(self, students, student_id=None):
        if student_id:
            try:
                sid = int(student_id)
            except (TypeError, ValueError):
                sid = 0
            match = students.filtered(lambda s: s.id == sid)
            if match:
                return match[0]
        return students[:1]

    def _oe_published_exams(self, students):
        exams = request.env['school.oe.exam'].sudo().search(
            [('state', '=', 'published'), ('exam_type', '!=', 'practice'),
             ('class_id', 'in', students.mapped('class_id').ids)])
        # an exam with a section is only for the students of that section
        return exams.filtered(
            lambda e: (not e.section_id or e.section_id in students.mapped('section_id'))
            and e.class_id in students.mapped('class_id'))

    def _oe_get_attempt(self, attempt_id, students):
        attempt = request.env['school.oe.attempt'].sudo().browse(int(attempt_id)).exists()
        if not attempt or attempt.student_id not in students:
            return None
        return attempt

    def _oe_error(self, title, message):
        return request.render('school_online_exam.portal_oe_message',
                              {'title': title, 'message': message})

    # ------------------------------------------------------------------
    # portal home card counter
    # ------------------------------------------------------------------
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'online_exam_count' in counters:
            students, _is_parent = self._oe_students()
            values['online_exam_count'] = len(self._oe_published_exams(students)) if students else 0
        return values

    # ------------------------------------------------------------------
    # exam list
    # ------------------------------------------------------------------
    def _oe_render_list(self, students, is_parent, student, error=None):
        exams = self._oe_published_exams(student) if student else request.env['school.oe.exam']
        Attempt = request.env['school.oe.attempt'].sudo()
        now = fields.Datetime.now()
        rows = []
        for exam in exams:
            attempts = Attempt.search([('exam_id', '=', exam.id), ('student_id', '=', student.id)])
            open_att = attempts.filtered(lambda a: a.state == 'in_progress' and a.deadline > now)[:1]
            done = attempts.filtered(lambda a: a.state != 'in_progress' or a.deadline <= now)
            final = exam._final_attempt(student)
            used = len(attempts)
            limit_hit = bool(exam.max_attempts) and used >= exam.max_attempts and not open_att
            window_ok = (not exam.date_start or now >= exam.date_start) and \
                        (not exam.date_end or now <= exam.date_end)
            rows.append({
                'exam': exam,
                'used': used,
                'done_count': len(done),
                'open_attempt': open_att,
                'final': final,
                'limit_hit': limit_hit,
                'window_ok': window_ok,
            })
        rows.sort(key=lambda r: r['exam'].exam_type == 'mock')      # real exams first, mock tests after
        values = self._prepare_portal_layout_values()
        values.update({
            'rows': rows, 'students': students, 'student': student,
            'is_parent': is_parent, 'error': error, 'page_name': 'online_exam',
        })
        return request.render('school_online_exam.portal_oe_exam_list', values)

    @http.route(['/my/online-exams'], type='http', auth='user', website=True)
    def portal_oe_exams(self, student_id=None, **kw):
        students, is_parent = self._oe_students()
        if not students:
            return self._oe_error(_('No Student Record'),
                                  _('No student record is linked to your account.'))
        student = self._oe_pick_student(students, student_id)
        return self._oe_render_list(students, is_parent, student)

    # ------------------------------------------------------------------
    # start / resume
    # ------------------------------------------------------------------
    @http.route(['/my/online-exams/<int:exam_id>/start'], type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def portal_oe_start(self, exam_id, **kw):
        students, is_parent = self._oe_students()
        if not students or is_parent:
            return self._oe_error(_('Not allowed'), _('Only the student can attend the exam.'))
        student = students[0]
        exam = request.env['school.oe.exam'].sudo().browse(exam_id).exists()
        if not exam:
            return request.redirect('/my/online-exams')
        try:
            attempt = exam._start_or_resume_attempt(student)
        except UserError as e:
            return self._oe_render_list(students, is_parent, student, error=str(e))
        return request.redirect('/my/online-exams/attempt/%s' % attempt.id)

    # ------------------------------------------------------------------
    # attempt page (question paper or result)
    # ------------------------------------------------------------------
    @http.route(['/my/online-exams/attempt/<int:attempt_id>'], type='http', auth='user', website=True)
    def portal_oe_attempt(self, attempt_id, **kw):
        students, is_parent = self._oe_students()
        attempt = self._oe_get_attempt(attempt_id, students)
        if not attempt:
            return request.redirect('/my/online-exams')
        if attempt.state == 'in_progress':
            if is_parent:
                return self._oe_error(_('Exam running'),
                                      _('This attempt is still in progress.'))
            attempt._auto_close_if_expired()
        values = self._prepare_portal_layout_values()
        values.update({'attempt': attempt, 'exam': attempt.exam_id,
                       'student': attempt.student_id, 'is_parent': is_parent,
                       'page_name': 'online_exam'})
        if attempt.state == 'in_progress':
            values['remaining'] = attempt.remaining_seconds()
            return request.render('school_online_exam.portal_oe_attempt_paper', values)
        values['can_retry'] = (not is_parent) and attempt.exam_id.state == 'published' and (
            not attempt.exam_id.max_attempts or
            request.env['school.oe.attempt'].sudo().search_count(
                [('exam_id', '=', attempt.exam_id.id), ('student_id', '=', attempt.student_id.id)]
            ) < attempt.exam_id.max_attempts)
        return request.render('school_online_exam.portal_oe_attempt_result', values)

    # ------------------------------------------------------------------
    # save one answer (called on every click)
    # ------------------------------------------------------------------
    @http.route(['/my/online-exams/attempt/<int:attempt_id>/answer'], type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def portal_oe_answer(self, attempt_id, line_id=None, option=None, **kw):
        students, is_parent = self._oe_students()
        attempt = None if is_parent else self._oe_get_attempt(attempt_id, students)
        if not attempt:
            return request.make_json_response({'ok': False, 'state': 'forbidden'})
        try:
            res = attempt.save_answer(int(line_id), option if option in ('a', 'b', 'c', 'd') else False)
        except (TypeError, ValueError):
            res = {'ok': False, 'state': attempt.state}
        return request.make_json_response(res)

    # ------------------------------------------------------------------
    # submit
    # ------------------------------------------------------------------
    @http.route(['/my/online-exams/attempt/<int:attempt_id>/submit'], type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def portal_oe_submit(self, attempt_id, **post):
        students, is_parent = self._oe_students()
        attempt = None if is_parent else self._oe_get_attempt(attempt_id, students)
        if not attempt:
            return request.redirect('/my/online-exams')
        answers = {}
        for line in attempt.line_ids:
            key = post.get('q_%s' % line.id)
            if key in ('a', 'b', 'c', 'd'):
                answers[line.id] = key
        attempt.submit(answers=answers, timeout=bool(post.get('timeout')))
        return request.redirect('/my/online-exams/attempt/%s' % attempt.id)

    # ------------------------------------------------------------------
    # attempt history
    # ------------------------------------------------------------------
    @http.route(['/my/online-exams/<int:exam_id>/history'], type='http', auth='user', website=True)
    def portal_oe_history(self, exam_id, student_id=None, **kw):
        students, is_parent = self._oe_students()
        if not students:
            return request.redirect('/my/online-exams')
        student = self._oe_pick_student(students, student_id)
        exam = request.env['school.oe.exam'].sudo().browse(exam_id).exists()
        if not exam:
            return request.redirect('/my/online-exams')
        attempts = request.env['school.oe.attempt'].sudo().search(
            [('exam_id', '=', exam.id), ('student_id', '=', student.id)], order='attempt_no desc')
        for att in attempts.filtered(lambda a: a.state == 'in_progress'):
            att._auto_close_if_expired()
        values = self._prepare_portal_layout_values()
        values.update({'exam': exam, 'student': student, 'attempts': attempts,
                       'final': exam._final_attempt(student), 'is_parent': is_parent,
                       'page_name': 'online_exam'})
        return request.render('school_online_exam.portal_oe_history', values)
