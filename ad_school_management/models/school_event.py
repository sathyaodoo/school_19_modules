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

    # Student score points. By default every activity uses the values of
    # Settings > School Management > Student Activity Score; tick "Custom
    # Points" to give THIS activity its own values (e.g. a big annual event).
    school_score_custom = fields.Boolean(
        string='Custom Points',
        help='Give this activity its own student score points instead of the Settings values.')
    school_score_participation = fields.Integer(string='Participation Points', default=0)
    school_score_first = fields.Integer(string='First Place Points', default=0)
    school_score_second = fields.Integer(string='Second Place Points', default=0)
    school_score_third = fields.Integer(string='Third Place Points', default=0)

    school_participant_count = fields.Integer(compute='_compute_school_counts', string='No. of Participants')
    school_winner_count = fields.Integer(compute='_compute_school_counts', string='No. of Winners')
    # Editable on the activity's Winners tab: add a participant and choose
    # the position, change it, or delete the row to remove the prize. Every
    # change is written on the participant (event.registration.school_position).
    school_winner_registration_ids = fields.Many2many(
        'event.registration', compute='_compute_school_counts', inverse='_inverse_school_winners',
        string='Winners')

    @api.depends('registration_ids.state', 'registration_ids.school_position')
    def _compute_school_counts(self):
        for event in self:
            regs = event.registration_ids.filtered(lambda r: r.state != 'cancel' and r.student_id)
            winners = regs.filtered('school_position').sorted(
                lambda r: ([p[0] for p in POSITIONS].index(r.school_position), r.student_id.name or ''))
            event.school_participant_count = len(regs)
            event.school_winner_count = len(winners)
            event.school_winner_registration_ids = winners

    def _inverse_school_winners(self):
        for event in self:
            winners = event.school_winner_registration_ids
            others = winners.filtered(lambda r: r.event_id != event)
            if others:
                raise ValidationError(_(
                    "Only participants of this activity can be winners: %s",
                    ', '.join(others.mapped('name'))))
            no_position = winners.filtered(lambda r: not r.school_position)
            if no_position:
                raise ValidationError(_(
                    "Choose First, Second or Third Place for: %s",
                    ', '.join(no_position.mapped('name'))))
            # Rows deleted from the Winners tab: the student keeps taking part
            # in the activity, only the prize is removed.
            (event.registration_ids.filtered('school_position') - winners).write({'school_position': False})

    @api.constrains('school_score_participation', 'school_score_first',
                    'school_score_second', 'school_score_third')
    def _check_school_score_points(self):
        for event in self:
            if min(event.school_score_participation, event.school_score_first,
                   event.school_score_second, event.school_score_third) < 0:
                raise ValidationError(_("Student score points cannot be negative (use 0 to give no points)."))
    
    @api.onchange('school_score_custom')
    def _onchange_school_score_custom(self):
        """Start the custom points from the values saved in Settings."""
        if self.school_score_custom:
            values = (self.company_id or self.env.company).sudo()._school_student_score_values()
            self.school_score_participation = values['participation']
            self.school_score_first = values['place']['first']
            self.school_score_second = values['place']['second']
            self.school_score_third = values['place']['third']


    def _school_student_score_values(self):
        """Points a student earns in this activity: the activity's own values
        when "Custom Points" is ticked, otherwise the company's Settings."""
        self.ensure_one()
        if self.school_score_custom:
            return {
                'participation': self.school_score_participation,
                'place': {
                    'first': self.school_score_first,
                    'second': self.school_score_second,
                    'third': self.school_score_third,
                },
            }
        company = (self.company_id or self.env.company).sudo()
        return company._school_student_score_values()

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


class EventEventHousePoints(models.Model):
    """House Championship: points earned automatically from school activities.

    * every participant (not cancelled) earns their house the Participation
      Points (Teamwork & Cooperation) - taking part counts, not only winning;
    * 1st / 2nd / 3rd place earns the First / Second / Third Place Points
      (Achievement);
    * group (house) events: each participating house earns the Group Event
      Participation Points, and the 1st / 2nd / 3rd place houses earn the
      First / Second / Third Place Points.
    All values come from Settings > School Management > House Championship.
    The activity's points are rebuilt whenever its participants, winners or
    places change (never duplicated)."""
    _inherit = 'event.event'

    house_point_ids = fields.One2many('school.house.point', 'event_id', string='House Points')

    _HOUSE_POINT_FIELDS = {'school_activity_type', 'school_participation', 'school_house_ids',
                           'school_first_house_id', 'school_second_house_id', 'school_third_house_id',
                           'is_school_activity', 'date_begin', 'name'}

    @api.model_create_multi
    def create(self, vals_list):
        events = super().create(vals_list)
        events._school_queue_house_points()
        return events

    def write(self, vals):
        result = super().write(vals)
        if self._HOUSE_POINT_FIELDS & set(vals):
            self._school_queue_house_points()
        return result

    def _school_queue_house_points(self):
        events = self.filtered('is_school_activity')
        if not events or self.env.context.get('install_mode'):
            return
        precommit = self.env.cr.precommit
        pending = precommit.data.setdefault('school_house_point_events', set())
        if not pending:
            precommit.add(self._school_run_house_point_sync)
        pending.update(events.ids)

    def _school_run_house_point_sync(self):
        ids = self.env.cr.precommit.data.pop('school_house_point_events', set())
        self.env['event.event'].sudo().browse(ids).exists()._school_sync_house_points()

    def _school_sync_house_points(self):
        from .school_house_point import ACTIVITY_CATEGORY
        Point = self.env['school.house.point'].sudo()
        place_labels = dict(POSITIONS)
        for event in self.sudo():
            Point.search([('event_id', '=', event.id), ('source', '=', 'activity')]).unlink()
            if not event.is_school_activity:
                continue
            # Values from Settings > School Management > House Championship
            values = (event.company_id or self.env.company)._school_house_point_values()
            PLACE_POINTS = values['place']
            PARTICIPATION_POINTS = values['participation']
            GROUP_PARTICIPATION_POINTS = values['group_participation']
            category = self.env['school.house.point.category']._get_by_code(
                ACTIVITY_CATEGORY.get(event.school_activity_type, 'cultural'))
            day = (event.date_begin or fields.Datetime.now()).date()
            vals_list = []
            if event.school_participation == 'group':
                for house in event.school_house_ids:
                    vals_list.append({'house_id': house.id, 'points': GROUP_PARTICIPATION_POINTS,
                                      'nature': 'cooperation',
                                      'name': _("Took part in %s", event.name)})
                for key, house in (('first', event.school_first_house_id),
                                   ('second', event.school_second_house_id),
                                   ('third', event.school_third_house_id)):
                    if house:
                        vals_list.append({'house_id': house.id, 'points': PLACE_POINTS[key],
                                          'nature': 'achievement',
                                          'name': _("%(place)s in %(event)s",
                                                    place=place_labels[key], event=event.name)})
            regs = event.registration_ids.filtered(
                lambda r: r.state != 'cancel' and r.student_id.house_id)
            for reg in regs:
                vals_list.append({'house_id': reg.student_id.house_id.id,
                                  'student_ids': [(6, 0, reg.student_id.ids)],
                                  'class_ids': [(6, 0, reg.student_id.class_id.ids)],
                                  'points': PARTICIPATION_POINTS, 'nature': 'cooperation',
                                  'name': _("Participation in %s", event.name)})
                if reg.school_position:
                    vals_list.append({'house_id': reg.student_id.house_id.id,
                                      'student_ids': [(6, 0, reg.student_id.ids)],
                                      'class_ids': [(6, 0, reg.student_id.class_id.ids)],
                                      'points': PLACE_POINTS[reg.school_position], 'nature': 'achievement',
                                      'name': _("%(place)s in %(event)s",
                                                place=place_labels[reg.school_position], event=event.name)})
            vals_list = [vals for vals in vals_list if vals['points'] > 0]  # 0 = no points
            for vals in vals_list:
                vals.update(category_id=category.id, date=day, source='activity', event_id=event.id,
                            awarded_by=event.user_id.id or self.env.uid)
            if vals_list:
                Point.create(vals_list)


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
    school_venue = fields.Char(related='event_id.school_venue', string='Venue')
    # Day of the activity (stored, so a student's history can be sorted by it).
    school_activity_date = fields.Date(
        string='Activity Date', compute='_compute_school_activity_date', store=True)

    # Student score earned in this activity (see Settings > Student Activity
    # Score). Stored, so the monthly / total score of a student is a plain sum.
    school_participation_points = fields.Integer(
        string='Participation Points', compute='_compute_school_score', store=True)
    school_prize_points = fields.Integer(
        string='Prize Points', compute='_compute_school_score', store=True)
    school_score = fields.Integer(
        string='Score', compute='_compute_school_score', store=True)

    @api.depends('event_id.date_begin', 'event_id.date_tz')
    def _compute_school_activity_date(self):
        for reg in self:
            begin = reg.event_id.date_begin
            if begin:
                tz_reg = reg.with_context(tz=reg.event_id.date_tz or self.env.user.tz or 'UTC')
                reg.school_activity_date = fields.Datetime.context_timestamp(tz_reg, begin).date()
            else:
                reg.school_activity_date = False

    @api.depends(
        'state', 'student_id', 'school_position',
        'event_id.is_school_activity', 'event_id.company_id',
        'event_id.school_score_custom', 'event_id.school_score_participation',
        'event_id.school_score_first', 'event_id.school_score_second', 'event_id.school_score_third',
        'event_id.company_id.student_score_participation', 'event_id.company_id.student_score_first',
        'event_id.company_id.student_score_second', 'event_id.company_id.student_score_third')
    def _compute_school_score(self):
        for reg in self:
            participation = prize = 0
            if reg.event_id.is_school_activity and reg.student_id and reg.state != 'cancel':
                values = reg.event_id._school_student_score_values()
                participation = values['participation']
                if reg.school_position:
                    prize = values['place'].get(reg.school_position, 0)
            reg.school_participation_points = participation
            reg.school_prize_points = prize
            reg.school_score = participation + prize

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
        registrations = super().create(vals_list)
        registrations.event_id._school_queue_house_points()
        return registrations

    def write(self, vals):
        events = self.event_id
        result = super().write(vals)
        if {'student_id', 'school_position', 'state', 'event_id', 'active'} & set(vals):
            (events | self.event_id)._school_queue_house_points()
        return result

    def unlink(self):
        events = self.event_id
        result = super().unlink()
        events.exists()._school_queue_house_points()
        return result

    @api.constrains('school_position', 'state')
    def _check_school_position(self):
        for reg in self:
            if reg.school_position and reg.state == 'cancel':
                raise ValidationError(_("A cancelled participant cannot be a winner."))
