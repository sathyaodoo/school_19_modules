from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SchoolAcademicYear(models.Model):
    _name = 'school.academic.year'
    _description = 'Academic Year'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc'

    name = fields.Char(string='Academic Year', required=True, tracking=True)
    code = fields.Char(string='Code', required=True, tracking=True)
    date_start = fields.Date(string='Start Date', required=True, tracking=True)
    date_end = fields.Date(string='End Date', required=True, tracking=True)
    active = fields.Boolean(string='Active', default=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Open'),
        ('closed', 'Closed')
    ], string='Status', default='draft', required=True, tracking=True)

    _name_uniq = models.Constraint(
        'unique(name)', 'The name of the Academic Year must be unique!'
    )
    _code_uniq = models.Constraint(
        'unique(code)', 'The code of the Academic Year must be unique!'
    )

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for record in self:
            if record.date_start and record.date_end and record.date_start >= record.date_end:
                raise ValidationError(_("The start date must be before the end date!"))

    def action_open(self):
        open_years = self.search([('state', '=', 'open')])
        if open_years:
            raise ValidationError(_("There is already an open Academic Year. Please close it first."))
        self.write({'state': 'open'})

    def action_close(self):
        self.write({'state': 'closed'})

    def action_draft(self):
        self.write({'state': 'draft'})
