'''from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal

class SchoolCustomerPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super(SchoolCustomerPortal, self)._prepare_home_portal_values(counters)
        partner = request.env.user.partner_id
        
        students = request.env['school.student'].sudo().search([
            '|', ('partner_id', '=', partner.id), ('parent_ids.partner_id', '=', partner.id)
        ])
        
        if 'student_count' in counters:
            values['student_count'] = len(students)
        return values

    @http.route(['/my/school/students'], type='http', auth="user", website=True)
    def portal_my_students(self, **kw):
        partner = request.env.user.partner_id
        students = request.env['school.student'].sudo().search([
            '|', ('partner_id', '=', partner.id), ('parent_ids.partner_id', '=', partner.id)
        ])
        values = self._prepare_portal_layout_values()
        values.update({
            'students': students,
            'page_name': 'school_students',
        })
        return request.render("ad_school_management.portal_my_students", values)

    @http.route(['/my/school/student/<int:student_id>'], type='http', auth="user", website=True)
    def portal_my_student_profile(self, student_id, **kw):
        partner = request.env.user.partner_id
        student = request.env['school.student'].sudo().browse(student_id)
        
        if not student.exists() or (student.partner_id.id != partner.id and partner.id not in student.parent_ids.partner_id.ids):
            return request.redirect('/my')

        attendances = request.env['school.attendance'].sudo().search([('student_id', '=', student.id)], order='date desc', limit=15)
        results = request.env['school.exam.result'].sudo().search([('student_id', '=', student.id)])
        
        timetable = request.env['school.timetable'].sudo().search([
            ('class_id', '=', student.class_id.id),
            ('section_id', '=', student.section_id.id),
            ('academic_year_id', '=', student.academic_year_id.id)
        ], limit=1)
        
        invoices = request.env['account.move'].sudo().search([
            ('partner_id', '=', student.partner_id.id),
            ('move_type', '=', 'out_invoice')
        ])

        values = self._prepare_portal_layout_values()
        values.update({
            'student': student,
            'attendances': attendances,
            'results': results,
            'timetable': timetable,
            'invoices': invoices,
            'page_name': 'school_student_profile',
        })
        return request.render("ad_school_management.portal_my_student_profile", values)
'''

from odoo import http, fields, _
from odoo.exceptions import UserError, ValidationError, AccessError
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal


class SchoolCustomerPortal(CustomerPortal):

    # ------------------------------------------------------------------
    # Portal home counters
    # ------------------------------------------------------------------
    def _prepare_home_portal_values(self, counters):
        values = super(SchoolCustomerPortal, self)._prepare_home_portal_values(counters)
        partner = request.env.user.partner_id

        if 'student_count' in counters:
            students = request.env['school.student'].sudo().search([
                '|', ('partner_id', '=', partner.id), ('parent_ids.partner_id', '=', partner.id)
            ])
            values['student_count'] = len(students)

        if 'leave_count' in counters:
            employee = self._school_get_employee()
            values['leave_count'] = request.env['hr.leave'].sudo().search_count(
                self._school_leave_domain(employee)) if employee else 0
        return values

    # ------------------------------------------------------------------
    # Students (unchanged)
    # ------------------------------------------------------------------
    @http.route(['/my/school/students'], type='http', auth="user", website=True)
    def portal_my_students(self, **kw):
        partner = request.env.user.partner_id
        students = request.env['school.student'].sudo().search([
            '|', ('partner_id', '=', partner.id), ('parent_ids.partner_id', '=', partner.id)
        ])
        values = self._prepare_portal_layout_values()
        values.update({
            'students': students,
            'page_name': 'school_students',
        })
        return request.render("ad_school_management.portal_my_students", values)

    @http.route(['/my/school/student/<int:student_id>'], type='http', auth="user", website=True)
    def portal_my_student_profile(self, student_id, **kw):
        partner = request.env.user.partner_id
        student = request.env['school.student'].sudo().browse(student_id)

        if not student.exists() or (student.partner_id.id != partner.id and partner.id not in student.parent_ids.partner_id.ids):
            return request.redirect('/my')

        attendances = request.env['school.attendance'].sudo().search([('student_id', '=', student.id)], order='date desc, session', limit=30)
        # One row per day with Morning and Afternoon side by side (last 15 days).
        attendance_days = request.env['school.attendance']._get_daily_summary(student, days=15)
        results = request.env['school.exam.result'].sudo().search([('student_id', '=', student.id)])

        timetable = request.env['school.timetable'].sudo().search([
            ('class_id', '=', student.class_id.id),
            ('section_id', '=', student.section_id.id),
            ('academic_year_id', '=', student.academic_year_id.id)
        ], limit=1)

        invoices = request.env['account.move'].sudo().search([
            ('partner_id', '=', student.partner_id.id),
            ('move_type', '=', 'out_invoice')
        ])

        values = self._prepare_portal_layout_values()
        values.update({
            'student': student,
            'attendances': attendances,
            'attendance_days': attendance_days,
            'results': results,
            'timetable': timetable,
            'invoices': invoices,
            'page_name': 'school_student_profile',
        })
        return request.render("ad_school_management.portal_my_student_profile", values)

    # ------------------------------------------------------------------
    # Leave requests (teachers / staff)
    # ------------------------------------------------------------------
    def _school_get_employee(self):
        return request.env['hr.employee'].sudo().search([('user_id', '=', request.env.user.id)], limit=1)

    def _school_leave_domain(self, employee):
        return [('employee_id', '=', employee.id),
                ('holiday_status_id.school_approval_workflow', '=', True)]

    def _school_leave_types(self, employee):
        return request.env['hr.leave.type'].sudo().search([
            ('school_approval_workflow', '=', True),
            ('company_id', 'in', [False, employee.company_id.id]),
        ], order='sequence, name')

    @http.route(['/my/leaves'], type='http', auth="user", website=True)
    def portal_my_leaves(self, **kw):
        employee = self._school_get_employee()
        leaves = request.env['hr.leave'].sudo().search(
            self._school_leave_domain(employee), order='request_date_from desc, id desc'
        ) if employee else request.env['hr.leave']
        values = self._prepare_portal_layout_values()
        values.update({
            'employee': employee,
            'leaves': leaves,
            'stage_labels': dict(request.env['hr.leave']._fields['school_approval_stage'].selection),
            'submitted': kw.get('submitted'),
            'page_name': 'school_leaves',
        })
        return request.render("ad_school_management.portal_my_leaves", values)

    @http.route(['/my/leaves/new'], type='http', auth="user", methods=['GET', 'POST'], website=True)
    def portal_leave_new(self, **post):
        employee = self._school_get_employee()
        leave_types = self._school_leave_types(employee) if employee else request.env['hr.leave.type']
        error = False

        if request.httprequest.method == 'POST' and employee:
            try:
                leave_id = self._school_create_leave(employee, leave_types, post)
                if leave_id:
                    return request.redirect('/my/leaves?submitted=1')
            except (UserError, ValidationError, AccessError) as e:
                error = e.args[0] if e.args else str(e)
            except ValueError:
                error = _("Please enter valid dates.")

        values = self._prepare_portal_layout_values()
        values.update({
            'employee': employee,
            'leave_types': leave_types,
            'values': post if request.httprequest.method == 'POST' else {},
            'error': error,
            'page_name': 'school_leave_new',
        })
        return request.render("ad_school_management.portal_leave_new", values)

    def _school_create_leave(self, employee, leave_types, post):
        leave_type = leave_types.filtered(lambda lt: str(lt.id) == str(post.get('holiday_status_id')))
        if not leave_type:
            raise UserError(_("Please select a leave type."))

        date_from = fields.Date.to_date(post.get('request_date_from') or None)
        date_to = fields.Date.to_date(post.get('request_date_to') or None) or date_from
        if not date_from:
            raise UserError(_("Please enter the start date."))
        if date_to < date_from:
            raise UserError(_("The end date cannot be before the start date."))

        reason = (post.get('name') or '').strip()
        if not reason:
            raise UserError(_("Please enter the reason for the leave."))

        files = [f for f in request.httprequest.files.getlist('attachments') if f and f.filename]
        if leave_type.school_is_medical and not files:
            raise UserError(_("A medical certificate is required for medical leave. Please attach it."))

        with request.env.cr.savepoint():
            leave = request.env['hr.leave'].sudo().create({
                'employee_id': employee.id,
                'holiday_status_id': leave_type.id,
                'request_date_from': date_from,
                'request_date_to': date_to,
                'name': reason,
            })
            Attachment = request.env['ir.attachment'].sudo()
            for upload in files:
                Attachment.create({
                    'name': upload.filename,
                    'raw': upload.read(),
                    'mimetype': upload.mimetype,
                    'res_model': 'hr.leave',
                    'res_id': leave.id,
                })
        return leave.id