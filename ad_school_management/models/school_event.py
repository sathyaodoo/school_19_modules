from odoo import api, fields, models, _, Command
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

    # Winning groups (group-based events): calculated from the total Score of
    # each group's students (see _compute_school_winning_houses)
    school_first_house_id = fields.Many2one('school.house', string='1st Place Group',
                                            compute='_compute_school_winning_houses', store=True)
    school_second_house_id = fields.Many2one('school.house', string='2nd Place Group',
                                             compute='_compute_school_winning_houses', store=True)
    school_third_house_id = fields.Many2one('school.house', string='3rd Place Group',
                                            compute='_compute_school_winning_houses', store=True)
    school_first_house_total = fields.Integer(string='1st Place Total',
                                              compute='_compute_school_winning_houses', store=True)
    school_second_house_total = fields.Integer(string='2nd Place Total',
                                               compute='_compute_school_winning_houses', store=True)
    school_third_house_total = fields.Integer(string='3rd Place Total',
                                              compute='_compute_school_winning_houses', store=True)
    school_winning_note = fields.Text(string='Tie Note', compute='_compute_school_winning_houses', store=True)
    school_standings = fields.Char(string='Standings', compute='_compute_school_winning_houses', store=True)

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
    # students already on the activity: used by the Participants tab to leave
    # them out of the Student dropdown (recomputed live in the form)
    school_participant_student_ids = fields.Many2many(
        'school.student', compute='_compute_school_participant_student_ids', string='Participating Students')

    @api.depends('registration_ids.student_id')
    def _compute_school_participant_student_ids(self):
        for event in self:
            event.school_participant_student_ids = event.registration_ids.student_id

    def _school_student_mismatch(self, student):
        """Why `student` may not take part in this activity ("Who Takes Part"),
        or False when allowed. Classes: student must be in one of them (if
        set). Groups: only for group events with groups set. Both = both."""
        self.ensure_one()
        reasons = []
        if self.school_class_ids and student.class_id not in self.school_class_ids:
            reasons.append(_("not in the selected classes (%s)", ', '.join(self.school_class_ids.mapped('display_name'))))
        if self.school_participation == 'group' and self.school_house_ids \
                and student.house_id not in self.school_house_ids:
            reasons.append(_("not in the participating groups (%s)", ', '.join(self.school_house_ids.mapped('display_name'))))
        return ' and '.join(reasons) or False

    @api.onchange('school_class_ids', 'school_house_ids', 'school_participation')
    def _onchange_school_who_takes_part(self):
        """Non-blocking: warn when existing participants no longer match.
        They are neither removed nor blocked."""
        if not self.is_school_activity:
            return
        outside = self.registration_ids.filtered(
            lambda r: r.student_id and r.state != 'cancel' and self._school_student_mismatch(r.student_id))
        if outside:
            names = outside.student_id.mapped('name')
            more = _(" and %s more", len(names) - 10) if len(names) > 10 else ''
            return {'warning': {
                'title': _("Some participants no longer match"),
                'message': _("%(count)s participant(s) are outside the selected classes / groups: "
                             "%(names)s%(more)s.\nThey stay on the activity; remove them in the "
                             "Participants tab if needed.",
                             count=len(outside), names=', '.join(names[:10]), more=more),
                'type': 'notification',
            }}

    @api.depends('registration_ids.state', 'registration_ids.school_position')
    def _compute_school_counts(self):
        for event in self:
            regs = event.registration_ids.filtered(lambda r: r.state != 'cancel' and r.student_id)
            winners = regs.filtered('school_position').sorted(
                lambda r: ([p[0] for p in POSITIONS].index(r.school_position), r.student_id.name or ''))
            event.school_participant_count = len(regs)
            event.school_winner_count = len(winners)
            event.school_winner_registration_ids = winners

    # --- Winners tab: never let unsaved rows (virtual ids) reach the ORM ------
    # The Winners list is computed from registration_ids, so a participant added
    # but not saved yet shows up there with a virtual id ("virtual_79"); the web
    # client then sends it as a many2many command, which the ORM cannot browse
    # (ValueError: Expected singleton). Positions of such rows are saved through
    # registration_ids anyway, so these commands are dropped.
    @staticmethod
    def _school_is_real_id(value):
        return isinstance(value, int) and not isinstance(value, bool)

    @classmethod
    def _school_clean_winner_commands(cls, commands):
        clean = []
        for command in commands or []:
            if not isinstance(command, (list, tuple)):
                if cls._school_is_real_id(command):
                    clean.append(command)
            elif command[0] in (Command.CLEAR,):
                clean.append(command)
            elif command[0] == Command.SET:
                clean.append((Command.SET, 0, [i for i in command[2] if cls._school_is_real_id(i)]))
            elif command[0] != Command.CREATE and cls._school_is_real_id(command[1]):
                clean.append(command)
        return clean

    @api.model_create_multi
    def create(self, vals_list):
        # a new activity has no previous winners: positions come with the
        # participants (registration_ids); an (even empty) Winners value would
        # make the inverse clear them
        for vals in vals_list:
            vals.pop('school_winner_registration_ids', None)
        return super().create(vals_list)

    def write(self, vals):
        if 'school_winner_registration_ids' in vals:
            vals = dict(vals)
            commands = self._school_clean_winner_commands(vals['school_winner_registration_ids'])
            if commands:
                vals['school_winner_registration_ids'] = commands
                # the inverse only clears the prize of rows that were winners
                # before this save (never of participants added in this save)
                old = {event.id: event.school_winner_registration_ids.ids for event in self}
                return super(EventEvent, self.with_context(school_winner_old_ids=old)).write(vals)
            vals.pop('school_winner_registration_ids')
        return super().write(vals)

    def _inverse_school_winners(self):
        old_by_event = self.env.context.get('school_winner_old_ids') or {}
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
            if event.id in old_by_event:
                removed = self.env['event.registration'].browse(old_by_event[event.id]) - winners
            else:
                removed = event.registration_ids.filtered('school_position') - winners
            removed.filtered('school_position').write({'school_position': False})

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

    @api.depends('is_school_activity', 'school_participation', 'school_house_ids',
                 'registration_ids.school_score', 'registration_ids.state',
                 'registration_ids.school_house_id', 'registration_ids.student_id')
    def _compute_school_winning_houses(self):
        """Group events: each group's total = sum of its students' Score
        (non-cancelled participants). Only the Participating Groups count when
        they are set, otherwise every group with participants. Ranked highest
        first; a total of 0 is not ranked. An exact tie leaves the tied places
        empty (no house place points) with a note; the next group gets the
        place after the tied ones (two tied for 1st -> next group is 3rd)."""
        labels = {1: _("1st"), 2: _("2nd"), 3: _("3rd")}
        for event in self:
            places = {1: (False, 0), 2: (False, 0), 3: (False, 0)}
            notes = []
            standings = False
            if event.is_school_activity and event.school_participation == 'group':
                totals = {house: 0 for house in event.school_house_ids}
                for reg in event.registration_ids:
                    house = reg.school_house_id
                    if reg.state == 'cancel' or not reg.student_id or not house:
                        continue
                    if event.school_house_ids and house not in event.school_house_ids:
                        continue
                    totals[house] = totals.get(house, 0) + reg.school_score
                ordered = sorted(totals.items(), key=lambda ht: (-ht[1], ht[0].display_name or ''))
                standings = ' · '.join('%s %s' % (h.display_name, t) for h, t in ordered) or False
                ranked = [(h, t) for h, t in ordered if t > 0]
                rank, i = 1, 0
                while i < len(ranked) and rank <= 3:
                    total = ranked[i][1]
                    tied = [h for h, t in ranked if t == total]
                    if len(tied) == 1:
                        places[rank] = (tied[0], total)
                    else:
                        notes.append(_("Tie for %(place)s place between %(groups)s (%(total)s points each): "
                                       "places not awarded automatically. Change a student's position "
                                       "to break the tie.",
                                       place=labels[rank], groups=', '.join(h.display_name for h in tied),
                                       total=total))
                    rank += len(tied)
                    i += len(tied)
            event.school_first_house_id, event.school_first_house_total = places[1]
            event.school_second_house_id, event.school_second_house_total = places[2]
            event.school_third_house_id, event.school_third_house_total = places[3]
            event.school_winning_note = '\n'.join(notes) or False
            event.school_standings = standings

    @api.model
    def _school_recompute_winning_houses(self):
        """Run on every module update (data/school_activity_winners_recompute.xml).
        Safe to repeat: recalculates the places of group activities and rebuilds
        the house points only of activities whose places changed."""
        events = self.sudo().with_context(active_test=False).search(
            [('is_school_activity', '=', True), ('school_participation', '=', 'group')])
        if not events:
            return True
        place_fields = ('school_first_house_id', 'school_second_house_id', 'school_third_house_id')
        before = {e.id: tuple(e[f].id for f in place_fields) for e in events}
        for fname in ('school_first_house_id', 'school_second_house_id', 'school_third_house_id',
                      'school_first_house_total', 'school_second_house_total', 'school_third_house_total',
                      'school_winning_note', 'school_standings'):
            self.env.add_to_compute(self._fields[fname], events)
        events.flush_recordset()
        changed = events.filtered(lambda e: tuple(e[f].id for f in place_fields) != before[e.id])
        if changed:
            changed._school_queue_house_points()
        return True

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

    # The 1st / 2nd / 3rd Place Groups are computed (never in write() vals):
    # a participant change (position / state / student / delete) already
    # queues the rebuild, and the rebuild reads the recomputed places. The
    # activity's own score points change the students' Scores, hence the places.
    _HOUSE_POINT_FIELDS = {'school_activity_type', 'school_participation', 'school_house_ids',
                           'is_school_activity', 'date_begin', 'name',
                           'school_score_custom', 'school_score_participation',
                           'school_score_first', 'school_score_second', 'school_score_third'}

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
                # group events: place points go to the houses only through the
                # group ranking above; individual events: per winning student
                if reg.school_position and event.school_participation != 'group':
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

    @api.constrains('student_id', 'event_id')
    def _check_school_who_takes_part(self):
        """A student outside the activity's classes / groups cannot be added.
        Only checked when the student or activity of a row is set or changed,
        so existing participants stay when the classes / groups change later."""
        for reg in self:
            if reg.student_id and reg.event_id.is_school_activity:
                reason = reg.event_id._school_student_mismatch(reg.student_id)
                if reason:
                    raise ValidationError(_('%(student)s cannot take part in "%(activity)s": %(reason)s.',
                                            student=reg.student_id.name, activity=reg.event_id.name,
                                            reason=reason))

    @api.constrains('school_position', 'state')
    def _check_school_position(self):
        for reg in self:
            if reg.school_position and reg.state == 'cancel':
                raise ValidationError(_("A cancelled participant cannot be a winner."))
