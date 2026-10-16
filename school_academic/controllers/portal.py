# -*- coding: utf-8 -*-
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal


class AcademicPortal(CustomerPortal):
    """Shared helper of the academic portal pages (the class diary).
    Curriculum and syllabus are not shown to students and parents."""

    def _ac_students(self):
        """(students, is_parent): a student login sees himself, a parent login the children."""
        partner = request.env.user.partner_id
        Student = request.env['school.student'].sudo()
        own = Student.search([('partner_id', '=', partner.id)])
        if own:
            return own, False
        kids = Student.search([('parent_ids.partner_id', '=', partner.id)])
        return kids, bool(kids)
