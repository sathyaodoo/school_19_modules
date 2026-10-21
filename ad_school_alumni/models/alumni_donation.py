from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SchoolAlumniDonation(models.Model):
    """A donation made by an alumni to the school."""
    _name = 'school.alumni.donation'
    _description = 'Alumni Donation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='Receipt No.', readonly=True, copy=False, default='/')
    alumni_id = fields.Many2one('school.alumni', string='Alumni', required=True, tracking=True, index=True)
    graduation_year = fields.Integer(related='alumni_id.graduation_year', store=True)
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, tracking=True)
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
                                  default=lambda self: self.env.company.currency_id)
    amount = fields.Monetary(string='Amount', required=True, tracking=True, currency_field='currency_id')
    purpose = fields.Selection([
        ('general', 'General Fund'),
        ('scholarship', 'Scholarship'),
        ('infrastructure', 'Infrastructure'),
        ('library', 'Library'),
        ('sports', 'Sports'),
        ('laboratory', 'Laboratory'),
        ('event', 'Event Sponsorship'),
        ('other', 'Other'),
    ], string='Purpose', required=True, default='general', tracking=True)
    payment_mode = fields.Selection([
        ('cash', 'Cash'),
        ('bank', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('online', 'Online / UPI'),
        ('other', 'Other'),
    ], string='Payment Mode', required=True, default='bank')
    payment_reference = fields.Char(string='Payment Reference')
    event_id = fields.Many2one('school.alumni.event', string='Event / Campaign')
    received_by = fields.Many2one('res.users', string='Received By', readonly=True, copy=False)
    received_date = fields.Date(string='Received On', readonly=True, copy=False)
    anonymous = fields.Boolean(string='Anonymous', help='Do not show the donor name in public lists.')
    notes = fields.Text(string='Notes')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pledged', 'Pledged'),
        ('received', 'Received'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, group_expand=True)

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_("The donation amount must be more than zero."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('school.alumni.donation') or '/'
        return super().create(vals_list)

    def action_pledge(self):
        self.filtered(lambda d: d.state == 'draft').write({'state': 'pledged'})

    def action_receive(self):
        for rec in self:
            if rec.state not in ('draft', 'pledged'):
                raise UserError(_("Only a Draft or Pledged donation can be marked as received."))
        self.write({'state': 'received', 'received_by': self.env.user.id,
                    'received_date': fields.Date.context_today(self)})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.filtered(lambda d: d.state == 'cancelled').write({'state': 'draft'})

    def action_print_receipt(self):
        if any(rec.state != 'received' for rec in self):
            raise UserError(_("A receipt can only be printed for a received donation."))
        return self.env.ref('ad_school_alumni.action_report_alumni_donation_receipt').report_action(self)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_received(self):
        if any(rec.state == 'received' for rec in self):
            raise UserError(_("A received donation cannot be deleted. Cancel it instead."))