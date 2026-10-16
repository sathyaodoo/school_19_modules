# -*- coding: utf-8 -*-
from odoo import _, http
from odoo.http import request

from .portal_practice import OnlinePracticePortal


class OnlinePerformancePortal(OnlinePracticePortal):
    """'My Performance' for the student (parents see their child, read only)."""

    @http.route(['/my/online-performance'], type='http', auth='user', website=True)
    def portal_perf(self, student_id=None, **kw):
        students, is_parent = self._oe_students()
        if not students:
            return self._oe_error(_('No Student Record'), _('No student record is linked to your account.'))
        student = self._oe_pick_student(students, student_id)
        data = request.env['school.oe.attempt']._performance_data(student)
        values = self._prepare_portal_layout_values()
        values.update({'data': data, 'students': students, 'student': student,
                       'is_parent': is_parent, 'page_name': 'online_exam'})
        return request.render('school_online_exam.portal_oe_performance', values)
