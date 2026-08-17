from odoo import http, _
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
