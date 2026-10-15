# -*- coding: utf-8 -*-
from urllib.parse import quote

from odoo import _, fields, http
from odoo.exceptions import UserError
from odoo.http import content_disposition, request

from .portal import OnlineExamPortal


class OnlineAssignmentPortal(OnlineExamPortal):
    """Descriptive answer-sheet / assignment / project upload for students."""

    # ------------------------------------------------------------------ helpers
    def _as_visible(self, student):
        return request.env['school.oe.assignment'].sudo().search(
            [('state', '=', 'published'), ('class_id', '=', student.class_id.id)]
        ).filtered(lambda a: a._visible_for(student))

    def _as_get(self, assignment_id, student):
        assignment = request.env['school.oe.assignment'].sudo().browse(int(assignment_id)).exists()
        if not assignment or not assignment._visible_for(student):
            return None
        return assignment

    def _as_redirect(self, assignment, student, error=None, ok=None):
        url = '/my/online-assignments/%s?student_id=%s' % (assignment.id, student.id)
        if error:
            url += '&error=%s' % quote(error)
        if ok:
            url += '&ok=%s' % quote(ok)
        return request.redirect(url)

    # ------------------------------------------------------------------ list
    @http.route(['/my/online-assignments'], type='http', auth='user', website=True)
    def portal_as_list(self, student_id=None, **kw):
        students, is_parent = self._oe_students()
        if not students:
            return self._oe_error(_('No Student Record'), _('No student record is linked to your account.'))
        student = self._oe_pick_student(students, student_id)
        rows = []
        for a in self._as_visible(student):
            rows.append({'assignment': a, 'sub': a._submission_for(student)})
        values = self._prepare_portal_layout_values()
        values.update({'rows': rows, 'students': students, 'student': student,
                       'is_parent': is_parent, 'page_name': 'online_exam'})
        return request.render('school_online_exam.portal_oe_as_list', values)

    # ------------------------------------------------------------------ detail
    @http.route(['/my/online-assignments/<int:assignment_id>'], type='http', auth='user', website=True)
    def portal_as_detail(self, assignment_id, student_id=None, error=None, ok=None, **kw):
        students, is_parent = self._oe_students()
        if not students:
            return request.redirect('/my/online-assignments')
        student = self._oe_pick_student(students, student_id)
        assignment = self._as_get(assignment_id, student)
        if not assignment:
            return request.redirect('/my/online-assignments')
        sub = assignment._submission_for(student)
        values = self._prepare_portal_layout_values()
        values.update({
            'assignment': assignment, 'student': student, 'sub': sub, 'is_parent': is_parent,
            'can_edit': bool(sub) and not is_parent and sub.is_open(),
            'needs_start': (not is_parent and not sub and bool(assignment.duration_minutes)),
            'remaining': sub.remaining_seconds() if sub else 0,
            'error': error, 'ok': ok, 'page_name': 'online_exam',
        })
        return request.render('school_online_exam.portal_oe_as_detail', values)

    def _as_own_student_and_assignment(self, assignment_id):
        students, is_parent = self._oe_students()
        if not students or is_parent:
            return None, None
        student = students[0]
        return student, self._as_get(assignment_id, student)

    # ------------------------------------------------------------------ start (timed work)
    @http.route(['/my/online-assignments/<int:assignment_id>/start'], type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def portal_as_start(self, assignment_id, **kw):
        student, assignment = self._as_own_student_and_assignment(assignment_id)
        if not assignment:
            return request.redirect('/my/online-assignments')
        try:
            if assignment.state != 'published':
                raise UserError(_("This work is not open."))
            sub = assignment._submission_for(student, create=True)
            sub._ensure_open()
        except UserError as e:
            return self._as_redirect(assignment, student, error=str(e))
        return self._as_redirect(assignment, student)

    # ------------------------------------------------------------------ upload
    @http.route(['/my/online-assignments/<int:assignment_id>/upload'], type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def portal_as_upload(self, assignment_id, note=None, **kw):
        student, assignment = self._as_own_student_and_assignment(assignment_id)
        if not assignment:
            return request.redirect('/my/online-assignments')
        try:
            if assignment.duration_minutes and not assignment._submission_for(student):
                raise UserError(_("Press Start first."))
            sub = assignment._submission_for(student, create=True)
            sub._ensure_open()
            files = []
            for f in request.httprequest.files.getlist('files'):
                if not f or not f.filename:
                    continue
                files.append((f.filename, f.read(10 * 1024 * 1024 + 1)))
            if not files:
                raise UserError(_("Choose at least one file."))
            sub.add_files(files)
            if note is not None:
                sub.sudo().note = note
        except UserError as e:
            return self._as_redirect(assignment, student, error=str(e))
        return self._as_redirect(assignment, student, ok=_("Files uploaded."))

    @http.route(['/my/online-assignments/<int:assignment_id>/remove/<int:att_id>'], type='http',
                auth='user', website=True, methods=['POST'], csrf=True)
    def portal_as_remove(self, assignment_id, att_id, **kw):
        student, assignment = self._as_own_student_and_assignment(assignment_id)
        if not assignment:
            return request.redirect('/my/online-assignments')
        sub = assignment._submission_for(student)
        try:
            if sub:
                sub.remove_file(att_id)
        except UserError as e:
            return self._as_redirect(assignment, student, error=str(e))
        return self._as_redirect(assignment, student)

    @http.route(['/my/online-assignments/<int:assignment_id>/submit'], type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def portal_as_submit(self, assignment_id, note=None, **kw):
        student, assignment = self._as_own_student_and_assignment(assignment_id)
        if not assignment:
            return request.redirect('/my/online-assignments')
        sub = assignment._submission_for(student)
        try:
            if not sub:
                raise UserError(_("Upload your files first."))
            sub.submit_work(note=note)
        except UserError as e:
            return self._as_redirect(assignment, student, error=str(e))
        return self._as_redirect(assignment, student, ok=_("Submitted successfully."))

    # ------------------------------------------------------------------ download
    @http.route(['/my/online-assignments/<int:assignment_id>/file/<int:att_id>'], type='http',
                auth='user', website=True)
    def portal_as_file(self, assignment_id, att_id, student_id=None, **kw):
        students, _is_parent = self._oe_students()
        if not students:
            return request.not_found()
        student = self._oe_pick_student(students, student_id)
        assignment = self._as_get(assignment_id, student)
        if not assignment:
            return request.not_found()
        att = request.env['ir.attachment'].sudo().browse(att_id).exists()
        sub = assignment._submission_for(student)
        allowed = att and (att in assignment.question_attachment_ids or (sub and att in sub.attachment_ids))
        if not allowed:
            return request.not_found()
        return request.make_response(att.raw, headers=[
            ('Content-Type', att.mimetype or 'application/octet-stream'),
            ('Content-Disposition', content_disposition(att.name)),
            ('X-Content-Type-Options', 'nosniff'),
        ])
