from odoo import models, fields, api, _


class SchoolResignationEmergencyExit(models.TransientModel):
    """Skip Notice Period: the employee cannot serve the 3-month notice
    period. Records the reason and the last working day, then moves the
    resignation to Handover."""
    _name = 'school.resignation.emergency.exit'
    _description = 'Skip Notice Period'

    resignation_id = fields.Many2one('school.staff.resignation', string='Resignation',
                                     required=True, readonly=True)
    employee_id = fields.Many2one(related='resignation_id.employee_id', string='Employee')
    # Editable: starts with the resignation's notice period start; the date
    # entered here is saved on the resignation when confirming.
    notice_period_start = fields.Date(string='Notice Period Started On', required=True)
    normal_last_day = fields.Date(string='Normal Last Working Day (3 months)',
                                  compute='_compute_normal_last_day')
    last_working_day = fields.Date(string='Last Working Day', required=True)
    reason = fields.Text(string='Reason for Skipping', required=True)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        resignation = self.env['school.staff.resignation'].browse(values.get('resignation_id'))
        today = fields.Date.context_today(self)
        start = resignation.notice_period_start or today
        if 'notice_period_start' in fields_list and not values.get('notice_period_start'):
            values['notice_period_start'] = start
        if 'last_working_day' in fields_list and not values.get('last_working_day'):
            # never propose a last day before the notice period start
            values['last_working_day'] = max(today, start)
        return values

    @api.depends('notice_period_start')
    def _compute_normal_last_day(self):
        for wiz in self:
            start = wiz.notice_period_start
            wiz.normal_last_day = fields.Date.add(start, months=3) if start else False

    @api.onchange('notice_period_start')
    def _onchange_notice_period_start(self):
        if self.notice_period_start and self.last_working_day and self.last_working_day < self.notice_period_start:
            self.last_working_day = self.notice_period_start

    def action_confirm(self):
        self.ensure_one()
        self.resignation_id._do_emergency_exit(
            self.reason, self.last_working_day, start=self.notice_period_start)
        return {'type': 'ir.actions.act_window_close'}