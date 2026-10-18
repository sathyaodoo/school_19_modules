# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .geo import behaviour_score, distance_to_polyline_m, eta_minutes, haversine_m


class SchoolTransportTrip(models.Model):
    """One run of a route (morning pickup / evening drop). While it is running every GPS ping is checked:
    geofences, approaching, ETA, deviation, stopped, harsh driving, speed."""
    _name = 'school.transport.trip'
    _description = 'Transport trip (live)'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    route_id = fields.Many2one('school.transport.route', string='Route', required=True, tracking=True)
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    trip_type = fields.Selection([('morning', 'Morning Pickup'), ('evening', 'Evening Drop')], string='Trip',
                                 required=True, default='morning')
    vehicle_id = fields.Many2one('school.vehicle', string='Vehicle', compute='_compute_vehicle_driver', store=True,
                                 readonly=False, precompute=True)
    driver_id = fields.Many2one('res.partner', string='Driver', compute='_compute_vehicle_driver', store=True,
                                readonly=False, precompute=True)
    caretaker_id = fields.Many2one('res.partner', string='Caretaker', compute='_compute_vehicle_driver', store=True,
                                   readonly=False, precompute=True)
    state = fields.Selection([('planned', 'Planned'), ('running', 'Running'), ('done', 'Finished'),
                              ('cancelled', 'Cancelled')], string='Status', default='planned', required=True,
                             tracking=True, index=True)
    started_at = fields.Datetime(string='Started', readonly=True)
    ended_at = fields.Datetime(string='Finished', readonly=True)
    attendance_id = fields.Many2one('school.transport.attendance', string='Attendance', ondelete='set null', readonly=True)
    stop_line_ids = fields.One2many('school.transport.trip.stop', 'trip_id', string='Stops')
    boarding_ids = fields.One2many('school.transport.boarding', 'trip_id', string='Boarding Records')
    event_ids = fields.One2many('school.transport.event', 'trip_id', string='Events & Alerts')

    # ---- live position / state of the checks ----
    last_latitude = fields.Float(digits=(10, 7), readonly=True)
    last_longitude = fields.Float(digits=(10, 7), readonly=True)
    last_speed = fields.Float(string='Speed (km/h)', readonly=True)
    last_ping_at = fields.Datetime(string='Last Ping', readonly=True)
    avg_speed_kmh = fields.Float(string='Average Moving Speed', readonly=True)
    max_speed = fields.Float(string='Top Speed (km/h)', readonly=True)
    distance_km = fields.Float(string='Distance (km)', readonly=True)
    deviation_pings = fields.Integer(readonly=True)
    deviation_active = fields.Boolean(readonly=True)
    stationary_since = fields.Datetime(readonly=True)
    stationary_alerted = fields.Boolean(readonly=True)
    in_campus = fields.Boolean(string='At School', readonly=True)
    eta_campus = fields.Datetime(string='Expected at School', readonly=True)
    next_stop_id = fields.Many2one('school.transport.stop', string='Next Stop', compute='_compute_next_stop')
    next_eta = fields.Datetime(string='Next Stop ETA', compute='_compute_next_stop')

    # ---- numbers ----
    expected_count = fields.Integer(string='Students on the Route', compute='_compute_expected')
    boarded_count = fields.Integer(string='Boarded', compute='_compute_boarding_counts', store=True)
    offboarded_count = fields.Integer(string='Dropped', compute='_compute_boarding_counts', store=True)
    on_board_count = fields.Integer(string='On Board Now', compute='_compute_boarding_counts', store=True)
    speeding_count = fields.Integer(string='Speeding Alerts', compute='_compute_event_counts', store=True)
    harsh_count = fields.Integer(string='Harsh Braking / Acceleration', compute='_compute_event_counts', store=True)
    deviation_count = fields.Integer(string='Route Deviations', compute='_compute_event_counts', store=True)
    breakdown_count = fields.Integer(string='Breakdowns', compute='_compute_event_counts', store=True)
    sos_count = fields.Integer(string='SOS', compute='_compute_event_counts', store=True)
    left_on_board_count = fields.Integer(string='Left on Board', compute='_compute_event_counts', store=True)
    behaviour_score = fields.Float(string='Behaviour Score', compute='_compute_event_counts', store=True,
                                   aggregator='avg', help="100 minus points for speeding, harsh driving and route deviations.")
    open_alert_count = fields.Integer(string='Open Alerts', compute='_compute_open_alerts')

    _trip_uniq = models.Constraint('unique(route_id, date, trip_type)',
                                   'There is already a trip for this route, date and type!')

    # ------------------------------------------------------------------ computes
    @api.depends('route_id')
    def _compute_vehicle_driver(self):
        for trip in self:
            trip.vehicle_id = trip.route_id.effective_vehicle_id
            trip.driver_id = trip.route_id.effective_driver_id
            trip.caretaker_id = trip.route_id.effective_vehicle_id.caretaker_id

    @api.depends('route_id', 'date', 'trip_type')
    def _compute_display_name(self):
        types = dict(self._fields['trip_type'].selection)
        for trip in self:
            trip.display_name = '%s - %s - %s' % (trip.route_id.name or _('New'), trip.date or '', types.get(trip.trip_type, ''))

    @api.depends('stop_line_ids.arrived_at', 'stop_line_ids.eta', 'stop_line_ids.sequence')
    def _compute_next_stop(self):
        for trip in self:
            line = trip.stop_line_ids.filtered(lambda l: not l.arrived_at).sorted('sequence')[:1]
            trip.next_stop_id = line.stop_id
            trip.next_eta = line.eta

    def _compute_expected(self):
        for trip in self:
            trip.expected_count = len(trip.route_id.student_ids)

    @api.depends('boarding_ids.event_type')
    def _compute_boarding_counts(self):
        for trip in self:
            boarded = len(trip.boarding_ids.filtered(lambda b: b.event_type == 'board'))
            dropped = len(trip.boarding_ids.filtered(lambda b: b.event_type == 'offboard'))
            trip.boarded_count, trip.offboarded_count, trip.on_board_count = boarded, dropped, boarded - dropped

    @api.depends('event_ids.event_type')
    def _compute_event_counts(self):
        for trip in self:
            types = trip.event_ids.mapped('event_type')
            trip.speeding_count = types.count('speeding')
            trip.harsh_count = types.count('harsh_brake') + types.count('harsh_accel')
            trip.deviation_count = types.count('deviation')
            trip.breakdown_count = types.count('breakdown')
            trip.sos_count = types.count('sos')
            trip.left_on_board_count = types.count('left_on_board')
            trip.behaviour_score = behaviour_score(trip.speeding_count, trip.harsh_count, trip.deviation_count,
                                                   trip.left_on_board_count)

    def _compute_open_alerts(self):
        for trip in self:
            trip.open_alert_count = len(trip.event_ids.filtered(lambda e: e.severity != 'info' and e.state == 'open'))

    # ------------------------------------------------------------------ helpers
    def _event(self, event_type, message, **kw):
        self.ensure_one()
        return self.env['school.transport.event']._raise(self.vehicle_id, event_type, message, trip=self, **kw)

    def _fmt_time(self, dt):
        return fields.Datetime.context_timestamp(self, dt or fields.Datetime.now()).strftime('%H:%M')

    def _vehicle_label(self):
        self.ensure_one()
        return '%s (%s)' % (self.vehicle_id.name or '-', self.vehicle_id.vehicle_number or '-')

    def _students_at_stop(self, stop):
        self.ensure_one()
        return self.route_id.student_ids.filtered(lambda s: s.van_boarding_point_id == stop)

    def _corridor_points(self, cfg):
        """The line the van is expected to follow: the stops in order, ending at (or starting from) the school."""
        self.ensure_one()
        points = [(s.latitude, s.longitude) for s in self.stop_line_ids.sorted('sequence').mapped('stop_id') if s.has_location]
        if cfg.has_campus:
            campus = (cfg.campus_latitude, cfg.campus_longitude)
            points = points + [campus] if self.trip_type == 'morning' else [campus] + points
        return points

    def _at_known_place(self, cfg, lat, lon):
        if cfg.has_campus and haversine_m(lat, lon, cfg.campus_latitude, cfg.campus_longitude) <= cfg.campus_radius_m:
            return True
        return any(haversine_m(lat, lon, s.latitude, s.longitude) <= s._geofence_radius(cfg)
                   for s in self.stop_line_ids.mapped('stop_id') if s.has_location)

    # ------------------------------------------------------------------ GPS pipeline
    @api.model
    def _process_ping(self, vehicle, lat, lon, speed, at, prev):
        cfg = self.env['school.transport.config']._get()
        trip = self.search([('vehicle_id', '=', vehicle.id), ('state', '=', 'running')], limit=1)
        vehicle._check_speeding(cfg, speed, at, lat, lon, trip)
        if trip:
            trip._on_ping(cfg, lat, lon, speed, at, prev)

    def _on_ping(self, cfg, lat, lon, speed, at, prev):
        self.ensure_one()
        vals = {'last_latitude': lat, 'last_longitude': lon, 'last_speed': speed, 'last_ping_at': at}
        if self.last_ping_at and self.last_latitude:
            step = haversine_m(self.last_latitude, self.last_longitude, lat, lon)
            if step < 5000:
                vals['distance_km'] = self.distance_km + step / 1000.0
        if speed > self.max_speed:
            vals['max_speed'] = speed
        if speed >= 5:
            vals['avg_speed_kmh'] = speed if not self.avg_speed_kmh else 0.8 * self.avg_speed_kmh + 0.2 * speed
        self.write(vals)
        self._check_harsh(cfg, speed, at, lat, lon, prev)
        self._check_geofences(cfg, lat, lon, speed, at)
        self._check_deviation(cfg, lat, lon, speed, at)
        self._check_stationary(cfg, lat, lon, speed, at)
        self._update_etas(cfg, lat, lon, at)

    def _check_harsh(self, cfg, speed, at, lat, lon, prev):
        if not prev.get('at') or prev.get('speed') is None:
            return
        seconds = (at - prev['at']).total_seconds()
        if not 1 <= seconds <= 20:
            return
        rate = (speed - prev['speed']) / seconds
        if rate <= -cfg.harsh_brake_kmh_s:
            self._event('harsh_brake', _("Harsh braking: %(drop)d km/h in %(sec)d s.", drop=round(prev['speed'] - speed),
                                         sec=round(seconds)), lat=lat, lon=lon, speed=speed, at=at)
        elif rate >= cfg.harsh_accel_kmh_s:
            self._event('harsh_accel', _("Harsh acceleration: %(gain)d km/h in %(sec)d s.", gain=round(speed - prev['speed']),
                                         sec=round(seconds)), lat=lat, lon=lon, speed=speed, at=at)

    def _check_geofences(self, cfg, lat, lon, speed, at):
        # the school
        if cfg.has_campus:
            inside = haversine_m(lat, lon, cfg.campus_latitude, cfg.campus_longitude) <= cfg.campus_radius_m
            if inside != self.in_campus:
                self.in_campus = inside
                self._event('geofence_enter' if inside else 'geofence_exit',
                            _("%(vehicle)s entered the school.", vehicle=self.vehicle_id.name) if inside
                            else _("%(vehicle)s left the school.", vehicle=self.vehicle_id.name), lat=lat, lon=lon, speed=speed, at=at)
                if inside and self.trip_type == 'morning':
                    self._auto_offboard_at_school(lat, lon, at)
        # the stops, in order
        for line in self.stop_line_ids.sorted('sequence'):
            stop = line.stop_id
            if not stop.has_location:
                continue
            distance = haversine_m(lat, lon, stop.latitude, stop.longitude)
            radius = stop._geofence_radius(cfg)
            if not line.arrived_at:
                if distance <= radius:
                    line.arrived_at = at
                    self._event('geofence_enter', _("%(vehicle)s reached %(stop)s.", vehicle=self.vehicle_id.name, stop=stop.name),
                                stop=stop, lat=lat, lon=lon, speed=speed, at=at)
                    if not line.approach_notified:
                        line.approach_notified = True
                        self._tell_parents_approaching(cfg, line, 0.0, at)
                elif not line.approach_notified and distance <= cfg.approach_distance_m:
                    line.approach_notified = True
                    minutes = eta_minutes(distance, self.avg_speed_kmh or speed, cfg.road_factor, cfg.eta_default_speed_kmh)
                    self._tell_parents_approaching(cfg, line, minutes, at)
            elif not line.departed_at and distance > radius + 30:
                line.departed_at = at
                self._event('geofence_exit', _("%(vehicle)s left %(stop)s.", vehicle=self.vehicle_id.name, stop=stop.name),
                            stop=stop, lat=lat, lon=lon, speed=speed, at=at)

    def _tell_parents_approaching(self, cfg, line, minutes, at):
        stop = line.stop_id
        students = self._students_at_stop(stop)
        if not students:
            return
        minutes = int(round(minutes))
        if minutes <= 0:
            text = _("The van %(vehicle)s is at %(stop)s now.", vehicle=self._vehicle_label(), stop=stop.name)
        else:
            text = _("The van %(vehicle)s is approaching %(stop)s. Expected in about %(minutes)d minutes.",
                     vehicle=self._vehicle_label(), stop=stop.name, minutes=minutes)
        self._event('approaching', _("%(text)s (%(count)d student(s))", text=text, count=len(students)), stop=stop,
                    lat=self.last_latitude, lon=self.last_longitude, at=at)
        if cfg.notify_parent_approach:
            self.env['school.transport.notification']._notify_parents(
                students, 'approaching', _("Van approaching - %s", stop.name), text, trip=self)

    def _check_deviation(self, cfg, lat, lon, speed, at):
        points = self._corridor_points(cfg)
        if len(points) < 2:
            return
        distance = distance_to_polyline_m(lat, lon, points)
        if distance > cfg.deviation_distance_m:
            pings = self.deviation_pings + 1
            vals = {'deviation_pings': pings}
            if pings >= cfg.deviation_pings and not self.deviation_active:
                vals['deviation_active'] = True
                self._event('deviation', _("%(vehicle)s is about %(meters)d m away from its route.",
                                           vehicle=self.vehicle_id.name, meters=round(distance)),
                            lat=lat, lon=lon, speed=speed, at=at)
            self.write(vals)
        elif self.deviation_pings or self.deviation_active:
            if self.deviation_active:
                self._event('back_on_route', _("%(vehicle)s is back on its route.", vehicle=self.vehicle_id.name),
                            lat=lat, lon=lon, speed=speed, at=at)
            self.write({'deviation_pings': 0, 'deviation_active': False})

    def _check_stationary(self, cfg, lat, lon, speed, at):
        if speed < 2.0:
            if not self.stationary_since:
                self.stationary_since = at
                return
            minutes = (at - self.stationary_since).total_seconds() / 60.0
            if minutes >= cfg.stationary_minutes and not self.stationary_alerted and not self._at_known_place(cfg, lat, lon):
                self.stationary_alerted = True
                self._event('stationary', _("%(vehicle)s has not moved for %(minutes)d minutes, away from any stop or the "
                                            "school. Possible breakdown.", vehicle=self.vehicle_id.name, minutes=round(minutes)),
                            lat=lat, lon=lon, speed=speed, at=at)
        elif self.stationary_since or self.stationary_alerted:
            self.write({'stationary_since': False, 'stationary_alerted': False})

    def _update_etas(self, cfg, lat, lon, at):
        position, minutes = (lat, lon), 0.0
        speed = self.avg_speed_kmh
        for line in self.stop_line_ids.filtered(lambda l: not l.arrived_at).sorted('sequence'):
            stop = line.stop_id
            if not stop.has_location:
                line.eta = False
                continue
            distance = haversine_m(position[0], position[1], stop.latitude, stop.longitude)
            minutes += eta_minutes(distance, speed, cfg.road_factor, cfg.eta_default_speed_kmh)
            line.eta = at + timedelta(minutes=minutes)
            position = (stop.latitude, stop.longitude)
        if cfg.has_campus and self.trip_type == 'morning' and not self.in_campus:
            distance = haversine_m(position[0], position[1], cfg.campus_latitude, cfg.campus_longitude)
            minutes += eta_minutes(distance, speed, cfg.road_factor, cfg.eta_default_speed_kmh)
            self.eta_campus = at + timedelta(minutes=minutes)
        elif self.in_campus:
            self.eta_campus = False

    # ------------------------------------------------------------------ trip life
    def action_start(self):
        for trip in self:
            if trip.state != 'planned':
                raise UserError(_("Only a planned trip can be started."))
            if not trip.vehicle_id:
                raise UserError(_("The route has no vehicle."))
            other = self.search([('vehicle_id', '=', trip.vehicle_id.id), ('state', '=', 'running'), ('id', '!=', trip.id)], limit=1)
            if other:
                raise UserError(_("%(vehicle)s is already on another trip (%(trip)s). Finish that trip first.",
                                  vehicle=trip.vehicle_id.name, trip=other.display_name))
            Attendance = self.env['school.transport.attendance'].sudo()
            attendance = Attendance.search([('route_id', '=', trip.route_id.id), ('date', '=', trip.date),
                                            ('trip_type', '=', trip.trip_type)], limit=1)
            if not attendance:
                attendance = Attendance.create({'route_id': trip.route_id.id, 'date': trip.date,
                                                'trip_type': trip.trip_type, 'marked_source': 'driver_portal'})
            attendance.action_fetch_students()
            trip.write({
                'state': 'running', 'started_at': fields.Datetime.now(), 'attendance_id': attendance.id,
                'stop_line_ids': [Command.clear()] + [Command.create({'stop_id': stop.id, 'sequence': stop.sequence})
                                                       for stop in trip.route_id.stop_ids],
                'deviation_pings': 0, 'deviation_active': False, 'stationary_since': False, 'stationary_alerted': False,
                'in_campus': False})
            trip._event('trip_start', _("%(trip)s started.", trip=trip.display_name))

    def _on_board_students(self):
        self.ensure_one()
        boarded = self.boarding_ids.filtered(lambda b: b.event_type == 'board').mapped('student_id')
        dropped = self.boarding_ids.filtered(lambda b: b.event_type == 'offboard').mapped('student_id')
        return boarded - dropped

    def action_end(self):
        for trip in self:
            if trip.state != 'running':
                raise UserError(_("Only a running trip can be finished."))
            left = trip._on_board_students()
            if left:
                trip._event('left_on_board', _("Trip finished with %(count)d student(s) still on board: %(names)s.",
                                               count=len(left), names=', '.join(left.mapped('name'))))
            if trip.boarding_ids and trip.attendance_id:           # the boarding records decide who travelled
                boarded = trip.boarding_ids.filtered(lambda b: b.event_type == 'board').mapped('student_id')
                trip.attendance_id.line_ids.filtered(lambda l: l.student_id not in boarded).write({'status': 'absent'})
            trip.write({'state': 'done', 'ended_at': fields.Datetime.now()})
            trip._event('trip_end', _("%(trip)s finished.", trip=trip.display_name))

    def action_cancel(self):
        self.filtered(lambda t: t.state in ('planned', 'running')).write({'state': 'cancelled'})

    @api.model
    def _cron_close_stale_trips(self, hours=8):
        limit = fields.Datetime.now() - timedelta(hours=hours)
        for trip in self.search([('state', '=', 'running'), ('started_at', '<', limit)]):
            trip.action_end()

    # ------------------------------------------------------------------ boarding / off-boarding
    def action_board_student(self, student, source='driver', lat=None, lon=None, at=None):
        self.ensure_one()
        if self.state != 'running':
            raise UserError(_("Start the trip first."))
        if student not in self.route_id.student_ids:
            raise UserError(_("%s is not a student of this route.", student.name))
        existing = self.boarding_ids.filtered(lambda b: b.student_id == student and b.event_type == 'board')
        if existing:
            return existing[:1]
        return self._make_boarding(student, 'board', source, lat, lon, at)

    def action_offboard_student(self, student, source='driver', lat=None, lon=None, at=None):
        self.ensure_one()
        if self.state != 'running':
            raise UserError(_("Start the trip first."))
        if student not in self._on_board_students():
            existing = self.boarding_ids.filtered(lambda b: b.student_id == student and b.event_type == 'offboard')
            if existing:
                return existing[:1]
            raise UserError(_("%s is not on board.", student.name))
        return self._make_boarding(student, 'offboard', source, lat, lon, at)

    def _make_boarding(self, student, event_type, source, lat, lon, at):
        stop = student.van_boarding_point_id
        return self.env['school.transport.boarding'].sudo().create({
            'trip_id': self.id, 'student_id': student.id, 'event_type': event_type, 'source': source,
            'event_at': at or fields.Datetime.now(), 'stop_id': stop.id if stop else False,
            'latitude': lat if lat is not None else self.last_latitude,
            'longitude': lon if lon is not None else self.last_longitude,
            'confirmed_by': self.env.uid if source in ('driver', 'caretaker', 'office') else False})

    def _auto_offboard_at_school(self, lat, lon, at):
        for student in self._on_board_students():
            self.action_offboard_student(student, source='auto_geofence', lat=lat, lon=lon, at=at)

    # ------------------------------------------------------------------ breakdown / SOS
    def action_breakdown(self, note=None, source='driver', lat=None, lon=None):
        self.ensure_one()
        cfg = self.env['school.transport.config']._get()
        event = self._event('breakdown', _("%(vehicle)s has broken down.%(note)s", vehicle=self.vehicle_id.name,
                                           note=(' ' + note) if note else ''), lat=lat, lon=lon)
        if cfg.notify_parent_breakdown:
            event._inform_parents()
        return event

    def _raise_sos(self, source='driver', lat=None, lon=None, note=None):
        self.ensure_one()
        cfg = self.env['school.transport.config']._get()
        recent = self.event_ids.filtered(lambda e: e.event_type == 'sos' and
                                         fields.Datetime.now() - e.event_at < timedelta(seconds=60))
        if recent:
            return recent[:1]                                     # a held / double-pressed button is one alarm
        event = self._event('sos', _("EMERGENCY SOS from %(vehicle)s (%(source)s).%(note)s", vehicle=self.vehicle_id.name,
                                     source=source, note=(' ' + note) if note else ''), lat=lat, lon=lon)
        if cfg.notify_parent_sos:
            event._inform_parents()
        return event

    @api.model
    def _sos_without_trip(self, vehicle, source='device', lat=None, lon=None, note=None):
        """The SOS button of a GPS device outside any started trip: the school is alerted all the same."""
        Event = self.env['school.transport.event'].sudo()
        since = fields.Datetime.now() - timedelta(seconds=60)
        recent = Event.search([('vehicle_id', '=', vehicle.id), ('event_type', '=', 'sos'), ('event_at', '>=', since)], limit=1)
        if recent:
            return recent
        return Event._raise(vehicle, 'sos', _("EMERGENCY SOS from %(vehicle)s (%(source)s).%(note)s", vehicle=vehicle.name,
                                              source=source, note=(' ' + note) if note else ''), lat=lat, lon=lon)


class SchoolTransportTripStop(models.Model):
    _name = 'school.transport.trip.stop'
    _description = 'Stop of a trip'
    _order = 'trip_id, sequence, id'

    trip_id = fields.Many2one('school.transport.trip', required=True, ondelete='cascade', index=True)
    stop_id = fields.Many2one('school.transport.stop', string='Stop', required=True)
    sequence = fields.Integer(default=10)
    eta = fields.Datetime(string='ETA')
    arrived_at = fields.Datetime(string='Reached At')
    departed_at = fields.Datetime(string='Left At')
    approach_notified = fields.Boolean(string='Parents Told')
    student_count = fields.Integer(string='Students', compute='_compute_student_count')
    state = fields.Selection([('pending', 'Coming'), ('arrived', 'At the stop'), ('left', 'Passed')],
                             compute='_compute_state', string='Status')

    def _compute_student_count(self):
        for line in self:
            line.student_count = len(line.trip_id._students_at_stop(line.stop_id))

    @api.depends('arrived_at', 'departed_at')
    def _compute_state(self):
        for line in self:
            line.state = 'left' if line.departed_at else 'arrived' if line.arrived_at else 'pending'
