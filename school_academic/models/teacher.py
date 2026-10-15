# -*- coding: utf-8 -*-
from odoo import api, models


class SchoolTeacher(models.Model):
    """A teacher's NAME is not private. The school module adds private HR fields to the employee, so a
    teacher login without HR rights could not even read another teacher's name (Odoo refuses with
    "not available for employee public profiles"). The display name is therefore read with sudo."""
    _inherit = 'school.teacher'

    @api.depends('employee_id.name')
    def _compute_display_name(self):
        for teacher in self:
            teacher.display_name = teacher.sudo().employee_id.name or ''
