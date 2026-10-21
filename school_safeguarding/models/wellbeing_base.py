# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError

DEFAULT_HELPLINE = ("If you feel unsafe, or you want to hurt yourself, tell a trusted adult right now. "
                    "In India you can also call CHILDLINE 1098 or Tele-MANAS 14416 (free, open 24 hours).")


def counsellor_users(env, lead_only=False):
    """The counsellors (a Lead counts as a counsellor). Nobody else is ever told."""
    group = env.ref('school_safeguarding.group_wb_lead' if lead_only else 'school_safeguarding.group_wb_counsellor')
    return env['res.users'].sudo().search([('all_group_ids', 'in', group.ids), ('share', '=', False)])


class WellbeingConfidential(models.AbstractModel):
    """Common rule of every well-being record: it can be exported only by the Well-being Lead."""
    _name = 'school.wellbeing.confidential'
    _description = 'Confidential well-being record'

    def _is_lead(self):
        return self.env.su or self.env.user.has_group('school_safeguarding.group_wb_lead')

    def export_data(self, fields_to_export):
        if not self._is_lead():
            raise AccessError(_("Only the Well-being Lead can export well-being records."))
        return super().export_data(fields_to_export)


class WellbeingConfig(models.Model):
    """Settings of one school (company)."""
    _name = 'school.wellbeing.config'
    _description = 'Well-being settings'
    _rec_name = 'company_id'

    company_id = fields.Many2one('res.company', string='School / Board', required=True, default=lambda self: self.env.company)
    checkin_interval_days = fields.Integer(string='Check-in every (days)', default=7,
                                           help="A student sees 'time for your check-in' when the last one is older.")
    struggling_streak = fields.Integer(string='Alert after this many "Struggling" check-ins in a row', default=2)
    auto_case_need_help = fields.Boolean(string='Open a case when a student says "Need help"', default=True)
    retention_years = fields.Integer(string='Keep closed cases for (years)', default=7)
    helpline_text = fields.Text(string='Help text shown to students', default=DEFAULT_HELPLINE,
                                help="Shown after a 'Struggling' or 'Need help' check-in. Edit it for your country.")

    _company_uniq = models.Constraint('unique(company_id)', 'There is already a well-being setting for this school.')

    @api.model
    def _get(self, company=None):
        company = company or self.env.company
        return self.sudo().search([('company_id', '=', company.id)], limit=1) or self.sudo().create({'company_id': company.id})

    @api.model
    def _ensure_default_config(self):
        """The settings of the main school exist (a row that is already there, e.g. left by an older install, is kept)."""
        self._get(self.env.ref('base.main_company'))

    @api.model
    def _repair_case_references(self):
        """The reference sequence belongs to no company, and the cases that got the reference 'New' (created from another
        company's portal before) receive a real one."""
        seq = self.env.ref('school_safeguarding.seq_wb_case', raise_if_not_found=False)
        if not seq:
            return
        seq.sudo().company_id = False
        for case in self.env['school.wellbeing.case'].sudo().search([('name', '=', 'New')], order='id'):
            case.name = seq.sudo().next_by_id()

    @api.model
    def _ensure_default_lead(self):
        """Somebody must be the Well-being Lead, or nobody could open the records: if the group is empty, the administrator is."""
        group = self.env.ref('school_safeguarding.group_wb_lead')
        if not group.sudo().user_ids:
            group.sudo().write({'user_ids': [(4, self.env.ref('base.user_root').id), (4, self.env.ref('base.user_admin').id)]})

    @api.model
    def action_open_settings(self):
        cfg = self._get()
        return {'type': 'ir.actions.act_window', 'name': 'Well-being Settings', 'res_model': self._name,
                'res_id': cfg.id, 'view_mode': 'form', 'target': 'current'}


class WellbeingArea(models.Model):
    """What the concern is about (tags). The school can add its own."""
    _name = 'school.wellbeing.area'
    _description = 'Well-being concern area'
    _order = 'sequence, id'

    name = fields.Char(string='Area', required=True, translate=True)
    sequence = fields.Integer(default=10)
    for_parents = fields.Boolean(string='Offered to parents', default=True,
                                 help="Parents can choose this area when they share a concern in the portal.")
