# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class SchoolTransportBoarding(models.Model):
    """The record of a student getting on (board) or off (offboard) the van, with time, place and who confirmed it."""
    _name = 'school.transport.boarding'
    _description = 'Student boarding / off-boarding record'
    _order = 'event_at desc, id desc'

    trip_id = fields.Many2one('school.transport.trip', string='Trip', required=True, ondelete='cascade', index=True)
    student_id = fields.Many2one('school.student', string='Student', required=True, ondelete='cascade', index=True)
    route_id = fields.Many2one(related='trip_id.route_id', store=True, string='Route')
    vehicle_id = fields.Many2one(related='trip_id.vehicle_id', store=True, string='Vehicle')
    date = fields.Date(related='trip_id.date', store=True, string='Date')
    trip_type = fields.Selection(related='trip_id.trip_type', store=True, string='Trip Type')
    event_type = fields.Selection([('board', 'Boarded'), ('offboard', 'Got off')], string='Record', required=True, index=True)
    event_at = fields.Datetime(string='When', required=True, default=fields.Datetime.now)
    stop_id = fields.Many2one('school.transport.stop', string="Student's Stop")
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    source = fields.Selection([('driver', 'Driver'), ('caretaker', 'Caretaker'), ('office', 'Office'),
                               ('auto_geofence', 'Automatic (van reached the school)')], string='Confirmed By Way Of',
                              required=True, default='driver')
    confirmed_by = fields.Many2one('res.users', string='Confirmed By')
    parent_notified = fields.Boolean(string='Parent Told', readonly=True)

    _boarding_uniq = models.Constraint('unique(trip_id, student_id, event_type)',
                                       'This student already has this record on this trip!')

    @api.depends('student_id', 'event_type', 'event_at')
    def _compute_display_name(self):
        types = dict(self._fields['event_type'].selection)
        for rec in self:
            rec.display_name = '%s - %s' % (rec.student_id.name or '', types.get(rec.event_type, ''))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._update_attendance()
            rec._tell_parents()
        return records

    def _update_attendance(self):
        self.ensure_one()
        line = self.trip_id.attendance_id.line_ids.filtered(lambda l: l.student_id == self.student_id)[:1]
        if line:
            if self.event_type == 'board':
                line.sudo().write({'status': 'boarded', 'boarded_at': self.event_at})
            else:
                line.sudo().write({'offboarded_at': self.event_at})

    def _tell_parents(self):
        """Parent notification when the child boards, and when the child reaches the stop / school."""
        self.ensure_one()
        cfg = self.env['school.transport.config']._get()
        trip = self.trip_id
        name, vehicle = self.student_id.name, trip._vehicle_label()
        when = trip._fmt_time(self.event_at)
        stop = self.stop_id.name or _('the stop')
        if self.event_type == 'board':
            if not cfg.notify_parent_board:
                return
            kind = 'boarded'
            if trip.trip_type == 'morning':
                text = _("%(name)s boarded the van %(vehicle)s at %(stop)s at %(time)s.", name=name, vehicle=vehicle, stop=stop, time=when)
            else:
                text = _("%(name)s boarded the van %(vehicle)s at school at %(time)s and is on the way home.",
                         name=name, vehicle=vehicle, time=when)
            subject = _("%s boarded the van", name)
        else:
            if not cfg.notify_parent_reached:
                return
            if trip.trip_type == 'morning':
                kind, subject = 'reached_school', _("%s reached school", name)
                text = _("%(name)s reached school at %(time)s.", name=name, time=when)
            else:
                kind, subject = 'reached_stop', _("%(name)s reached %(stop)s", name=name, stop=stop)
                text = _("%(name)s reached %(stop)s at %(time)s.", name=name, stop=stop, time=when)
        sent = self.env['school.transport.notification']._notify_parents(self.student_id, kind, subject, text, trip=trip)
        self.parent_notified = bool(sent)


class SchoolTransportAttendanceLine(models.Model):
    _inherit = 'school.transport.attendance.line'

    boarded_at = fields.Datetime(string='Boarded At', readonly=True)
    offboarded_at = fields.Datetime(string='Got Off At', readonly=True)
