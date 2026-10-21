from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SchoolAlumniEvent(models.Model):
    """Alumni events: reunions, meet-ups, webinars, fund-raisers..."""
    _name = 'school.alumni.event'
    _description = 'Alumni Event'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char(string='Event', required=True, tracking=True)
    event_type = fields.Selection([
        ('reunion', 'Reunion'),
        ('meetup', 'Networking Meet-up'),
        ('webinar', 'Webinar'),
        ('fundraiser', 'Fund-raiser'),
        ('sports', 'Sports'),
        ('cultural', 'Cultural'),
        ('other', 'Other'),
    ], string='Type', required=True, default='reunion', tracking=True)
    date_start = fields.Datetime(string='Start', required=True, tracking=True)
    date_end = fields.Datetime(string='End')
    venue = fields.Char(string='Venue / Link')
    batch_years = fields.Char(string='For Batches', help='e.g. "2015-2020" or "All batches"')
    organizer_id = fields.Many2one('res.users', string='Organizer', default=lambda self: self.env.user)
    description = fields.Html(string='Description')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, group_expand=True)
    attendee_ids = fields.One2many('school.alumni.event.attendee', 'event_id', string='Participants')
    invited_count = fields.Integer(string='Invited', compute='_compute_counts', store=True)
    registered_count = fields.Integer(string='Registered', compute='_compute_counts', store=True)
    attended_count = fields.Integer(string='Attended', compute='_compute_counts', store=True)
    donation_ids = fields.One2many('school.alumni.donation', 'event_id', string='Donations')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    amount_raised = fields.Monetary(string='Amount Raised', compute='_compute_amount_raised',
                                    currency_field='currency_id')

    @api.depends('attendee_ids.status')
    def _compute_counts(self):
        for rec in self:
            statuses = rec.attendee_ids.mapped('status')
            rec.invited_count = len(statuses)
            rec.registered_count = len([s for s in statuses if s in ('registered', 'attended')])
            rec.attended_count = statuses.count('attended')

    @api.depends('donation_ids.amount', 'donation_ids.state')
    def _compute_amount_raised(self):
        for rec in self:
            rec.amount_raised = sum(rec.donation_ids.filtered(lambda d: d.state == 'received').mapped('amount'))

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError(_("The end cannot be before the start."))

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_done(self):
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_("Only a Confirmed event can be marked as done."))
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset(self):
        self.write({'state': 'draft'})

    def action_view_donations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Donations'),
            'res_model': 'school.alumni.donation',
            'view_mode': 'list,form',
            'domain': [('event_id', '=', self.id)],
            'context': {'default_event_id': self.id},
        }


class SchoolAlumniEventAttendee(models.Model):
    _name = 'school.alumni.event.attendee'
    _description = 'Alumni Event Participant'
    _order = 'event_id, alumni_id'

    event_id = fields.Many2one('school.alumni.event', string='Event', required=True, ondelete='cascade', index=True)
    alumni_id = fields.Many2one('school.alumni', string='Alumni', required=True, index=True)
    graduation_year = fields.Integer(related='alumni_id.graduation_year', store=True)
    email = fields.Char(related='alumni_id.email')
    phone = fields.Char(related='alumni_id.phone')
    status = fields.Selection([
        ('invited', 'Invited'),
        ('registered', 'Registered'),
        ('attended', 'Attended'),
        ('absent', 'Absent'),
    ], string='Status', default='invited', required=True)
    role = fields.Selection([('guest', 'Guest'), ('speaker', 'Speaker'), ('volunteer', 'Volunteer'),
                             ('host', 'Host')], string='Role', default='guest')

    _event_alumni_uniq = models.Constraint('unique(event_id, alumni_id)',
                                           'This alumni is already in the event!')