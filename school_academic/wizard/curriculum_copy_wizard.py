# -*- coding: utf-8 -*-
from odoo import fields, models, _


class SchoolCurriculumCopyWizard(models.TransientModel):
    _name = 'school.curriculum.copy.wizard'
    _description = 'Copy a curriculum to another academic year'

    curriculum_id = fields.Many2one('school.curriculum', string='Curriculum', required=True, readonly=True)
    source_year_id = fields.Many2one(related='curriculum_id.academic_year_id', string='From Academic Year')
    target_year_id = fields.Many2one('school.academic.year', string='To Academic Year', required=True)

    def action_copy(self):
        self.ensure_one()
        new = self.curriculum_id._copy_to_year(self.target_year_id)
        return {
            'type': 'ir.actions.act_window', 'name': _('Curriculum'), 'res_model': 'school.curriculum',
            'res_id': new.id, 'view_mode': 'form', 'target': 'current',
        }
