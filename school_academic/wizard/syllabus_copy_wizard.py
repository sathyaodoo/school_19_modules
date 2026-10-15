# -*- coding: utf-8 -*-
from odoo import fields, models, _


class SchoolSyllabusCopyWizard(models.TransientModel):
    _name = 'school.syllabus.copy.wizard'
    _description = 'Copy a syllabus to another academic year'

    syllabus_id = fields.Many2one('school.syllabus', string='Syllabus', required=True, readonly=True)
    source_year_id = fields.Many2one(related='syllabus_id.academic_year_id', string='From Academic Year')
    target_year_id = fields.Many2one('school.academic.year', string='To Academic Year', required=True)

    def action_copy(self):
        self.ensure_one()
        new = self.syllabus_id._copy_to_year(self.target_year_id)
        return {'type': 'ir.actions.act_window', 'name': _('Syllabus'), 'res_model': 'school.syllabus',
                'res_id': new.id, 'view_mode': 'form', 'target': 'current'}
