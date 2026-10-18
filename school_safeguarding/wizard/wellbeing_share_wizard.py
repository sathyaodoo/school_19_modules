# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, _, fields, models
from odoo.exceptions import UserError

from ..models.case import CATEGORIES, SEVERITIES


class WellbeingShareWizard(models.TransientModel):
    """The counsellor decides to tell the Safeguarding team (e.g. bullying, a child in danger). Only the summary typed here
    goes to them: the counselling notes, sessions and check-ins are never copied."""
    _name = 'school.wellbeing.share.wizard'
    _description = 'Share a well-being case with Safeguarding'

    case_id = fields.Many2one('school.wellbeing.case', string='Well-being case', required=True, readonly=True)
    student_id = fields.Many2one(related='case_id.student_id', string='Student')
    category = fields.Selection(CATEGORIES, string='Type of Concern', required=True, default='bullying')
    severity = fields.Selection(SEVERITIES, string='Severity', required=True, default='medium')
    immediate_risk = fields.Boolean(string='Someone may be in danger right now')
    description = fields.Text(string='What the Safeguarding team needs to know', required=True)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Sent')], default='draft')
    reference = fields.Char(readonly=True)

    def action_submit(self):
        self.ensure_one()
        case = self.case_id
        if case.safeguarding_ref:
            raise UserError(_("This case was already shared with Safeguarding (%s).", case.safeguarding_ref))
        if len((self.description or '').strip()) < 10:
            raise UserError(_("Write what the Safeguarding team needs to know."))
        sg_case = self.env['school.safeguarding.case'].with_user(SUPERUSER_ID).create({
            'category': self.category, 'severity': self.severity, 'immediate_risk': self.immediate_risk,
            'description': self.description.strip(), 'source': 'staff', 'reporter_partner_id': self.env.user.partner_id.id,
            'affected_student_ids': [(6, 0, case.student_id.ids)], 'company_id': case.company_id.id})
        case.sudo().write({'safeguarding_ref': sg_case.name})
        case._log(_("Shared with Safeguarding (%s). Counselling notes were not copied.", sg_case.name))
        self.write({'state': 'done', 'reference': sg_case.name})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form', 'target': 'new'}
