# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, _, fields, models
from odoo.exceptions import UserError


class WellbeingConcernWizard(models.TransientModel):
    """A teacher / staff member tells the counsellor about a student. After sending, the teacher cannot read it again."""
    _name = 'school.wellbeing.concern.wizard'
    _description = 'Raise a well-being concern'

    student_id = fields.Many2one('school.student', string='Student', required=True)
    area_ids = fields.Many2many('school.wellbeing.area', 'wb_wizard_area_rel', 'wizard_id', 'area_id', string='What is it about?')
    level = fields.Selection([('low', 'Low'), ('medium', 'Medium'), ('high', 'High - please see the student soon')],
                             string='How worried are you?', default='medium', required=True)
    description = fields.Text(string='What did you notice?', required=True)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Sent')], default='draft')
    reference = fields.Char(readonly=True)

    def action_submit(self):
        self.ensure_one()
        if len((self.description or '').strip()) < 10:
            raise UserError(_("Please write a few words about what you noticed."))
        case = self.env['school.wellbeing.case'].with_user(SUPERUSER_ID).create({
            'student_id': self.student_id.id, 'level': self.level, 'source': 'teacher', 'area_ids': [(6, 0, self.area_ids.ids)],
            'concern_text': self.description, 'reporter_partner_id': self.env.user.partner_id.id,
            'company_id': self.student_id.sudo().company_id.id or self.env.company.id})
        self.write({'state': 'done', 'reference': case.name})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form', 'target': 'new'}
