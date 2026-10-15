from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

ACTIVITY_TYPES = [
    ('sports', 'Sports'),
    ('arts', 'Arts'),
    ('cultural', 'Cultural'),
    ('academic', 'Academic'),
]
POSITIONS = [
    ('first', 'First Place'),
    ('second', 'Second Place'),
    ('third', 'Third Place'),
]


class EventEvent(models.Model):
    """School Activities on top of the standard Odoo Event.

    Standard fields reused: name (Activity Name), date_begin / date_end
    (Date, Start and End Time), description, registration_ids (participants).
    """
    _inherit = 'event.event'

    is_school_activity = fields.Boolean(string='School Activity', index=True)
    school_activity_type = fields.Selection(ACTIVITY_TYPES, string='Activity Type', tracking=True)
    school_venue = fields.Char(string='Activity Venue', tracking=True,
                               help='Place in the school, e.g. Main Ground, Auditorium.')
    school_participation = fields.Selection(
        [('individual', 'Individual'), ('group', 'Group (House) Event')],
        string='Participation', default='individual')
    school_class_ids = fields.Many2many('school.class', string='Classes')
    school_house_ids = fields.Many2many('school.house', string='Participating Groups')

    # Winning groups (group-based events)
    school_first_house_id = fields.Many2one('school.house', string='1st Place Group')
    school_second_house_id = fields.Many2one('school.house', string='2nd Place Group')
    school_third_house_id = fields.Many2one('school.house', string='3rd Place Group')

    school_participant_count = fields.Integer(compute='_compute_school_counts', string='No. of Participants')
    school_winner_count = fields.Integer(compute='_compute_school_counts', string='No. of Winners')
    school_winner_registration_ids = fields.One2many(
        'event.registration', compute='_compute_school_counts', string='Winners')

    @api.depends('registration_ids.state', 'registration_ids.school_position')
    def _compute_school_counts(self):
        for event in self:
            regs = event.registration_ids.filtered(lambda r: r.state != 'cancel' and r.student_id)
            winners = regs.filtered('school_position').sorted(
                lambda r: ([p[0] for p in POSITIONS].index(r.school_position), r.student_id.name or ''))
            event.school_participant_count = len(regs)
            event.school_winner_count = len(winners)
            event.school_winner_registration_ids = winners

    @api.depends('event_type_id', 'is_school_activity')
    def _compute_event_mail_ids(self):
        # Odoo adds default email reminders to new events. School activities
        # do not email students unless a template (event type) says so.
        school = self.filtered(lambda e: e.is_school_activity and not e.event_type_id)
        super(EventEvent, self - school)._compute_event_mail_ids()
        for event in school:
            event.event_mail_ids = event.event_mail_ids.filtered(lambda m: m._origin.mail_done)

    @api.constrains('is_school_activity', 'school_activity_type')
    def _check_school_activity_type(self):
        for event in self:
            if event.is_school_activity and not event.school_activity_type:
                raise ValidationError(_("Please set the Activity Type (Sports, Arts, Cultural or Academic)."))

    @api.constrains('school_first_house_id', 'school_second_house_id', 'school_third_house_id')
    def _check_house_places(self):
        for event in self:
            places = [h for h in (event.school_first_house_id, event.school_second_house_id,
                                  event.school_third_house_id) if h]
            if len(places) != len(set(places)):
                raise ValidationError(_("A group can win only one place in an activity."))

    @api.model
    def _school_clear_sample_description(self):
        """Remove Odoo's sample event text ("Join us for this 24 hours
        Event...") from school activities. Only that exact sample is
        removed; any description written by the school is kept."""
        activities = self.with_context(active_test=False).search([
            ('is_school_activity', '=', True),
            ('description', 'ilike', 'Join us for this 24 hours Event'),
        ])
        activities.filtered(
            lambda e: 'invite our community, partners and end-users' in (e.description or '')
        ).write({'description': False})

    def action_school_add_participants(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Add Participants'),
            'res_model': 'school.activity.participant.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_event_id': self.id},
        }

    def action_school_view_participants(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'ad_school_management.action_school_activity_participants')
        action['domain'] = [('event_id', '=', self.id)]
        action['context'] = {'default_event_id': self.id}
        return action


class EventRegistration(models.Model):
    """A student taking part in a school activity."""
    _inherit = 'event.registration'

    student_id = fields.Many2one('school.student', string='Student', index=True)
    admission_no = fields.Char(related='student_id.admission_no', string='Admission No', store=True)
    school_class_id = fields.Many2one(related='student_id.class_id', string='Class', store=True)
    school_section_id = fields.Many2one(related='student_id.section_id', string='Section', store=True)
    school_house_id = fields.Many2one(related='student_id.house_id', string='Group', store=True)
    school_gender = fields.Selection(related='student_id.gender', string='Gender')
    school_position = fields.Selection(POSITIONS, string='Position', tracking=True)
    school_activity_type = fields.Selection(related='event_id.school_activity_type', store=True)
    is_school_activity = fields.Boolean(related='event_id.is_school_activity', store=True)

    _event_student_uniq = models.Constraint(
        'unique(event_id, student_id)', 'This student is already a participant of this activity!'
    )

    @api.onchange('student_id')
    def _onchange_student_id(self):
        if self.student_id:
            self.partner_id = self.student_id.partner_id
            self.name = self.student_id.name

    @api.model_create_multi
    def create(self, vals_list):
        students = self.env['school.student'].browse(
            [v['student_id'] for v in vals_list if v.get('student_id')])
        for vals in vals_list:
            if vals.get('student_id'):
                student = students.filtered(lambda s: s.id == vals['student_id'])
                vals.setdefault('partner_id', student.partner_id.id)
                vals.setdefault('name', student.name)
        return super().create(vals_list)

    @api.constrains('school_position', 'state')
    def _check_school_position(self):
        for reg in self:
            if reg.school_position and reg.state == 'cancel':
                raise ValidationError(_("A cancelled participant cannot be a winner."))