# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, fields, models, _
from odoo.exceptions import UserError

from ..models.case import CATEGORIES


class SafeguardingReportWizard(models.TransientModel):
    """How a teacher / staff member reports a concern. The case is created for the Safeguarding team;
    the reporter cannot open the case afterwards, so nothing about the investigation reaches them."""
    _name = 'school.safeguarding.report.wizard'
    _description = 'Report a safeguarding concern'

    state = fields.Selection([('draft', 'Draft'), ('done', 'Sent')], default='draft')
    category = fields.Selection(CATEGORIES, string='Type of Concern', required=True, default='bullying')
    immediate_risk = fields.Boolean(string='Someone may be in danger right now')
    incident_date = fields.Date(string='When did it happen', default=fields.Date.context_today)
    location = fields.Char(string='Where')
    is_online = fields.Boolean(string='Online / Digital')
    platform = fields.Char(string='App / Platform')
    description = fields.Text(string='What happened', help="Write what you saw or heard. Facts, not opinions.")
    affected_student_ids = fields.Many2many('school.student', 'sg_wizard_affected_rel', 'wizard_id', 'student_id',
                                            string='Affected Student(s)')
    involved_student_ids = fields.Many2many('school.student', 'sg_wizard_involved_rel', 'wizard_id', 'student_id',
                                            string='Student(s) Involved')
    involved_other = fields.Char(string='Others Involved (names / roles)')
    is_anonymous = fields.Boolean(string='Report anonymously',
                                  help="Your name is not stored with the report.")
    result_reference = fields.Char(string='Reference', readonly=True)
    result_code = fields.Char(string='Code', readonly=True)

    def action_submit(self):
        self.ensure_one()
        if not (self.description or '').strip():
            raise UserError(_("Please write what happened."))
        vals = {
            'category': self.category, 'immediate_risk': self.immediate_risk, 'incident_date': self.incident_date,
            'location': self.location, 'is_online': self.is_online, 'platform': self.platform,
            'description': self.description.strip(), 'involved_other': self.involved_other,
            'affected_student_ids': [(6, 0, self.affected_student_ids.ids)],
            'involved_student_ids': [(6, 0, self.involved_student_ids.ids)],
        }
        if self.is_anonymous:
            vals['is_anonymous'] = True
        else:
            vals.update({'reporter_partner_id': self.env.user.partner_id.id, 'source': 'staff'})
        # created by the system user: the reporter is not the "creator" of the record, and can not read it back
        case = self.env['school.safeguarding.case'].with_user(SUPERUSER_ID).with_company(self.env.company).create(vals)
        self.write({'state': 'done', 'result_reference': case.name, 'result_code': case.access_code})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}
