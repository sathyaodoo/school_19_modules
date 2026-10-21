# -*- coding: utf-8 -*-
import re
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import HttpCase, TransactionCase, tagged

from odoo.addons.school_smart_transport.models.geo import offset_point

BASE = (11.0, 77.0)
T0 = datetime(2026, 9, 1, 7, 0, 0)


def _user(env, login, *xmlids):
    groups = [env.ref('base.group_user')] + [env.ref(x) for x in xmlids]
    return env['res.users'].create({'name': login, 'login': login, 'group_ids': [(6, 0, [g.id for g in groups])]})


class _World:
    """A van, a route with three stops on a north-south line (0 m, 2 km, 4 km) and the school 6 km north."""

    @classmethod
    def _build(cls):
        env = cls.env
        cls.driver = env['res.partner'].create({'name': 'Driver D', 'is_school_driver': True, 'phone': '9000000001'})
        cls.caretaker = env['res.partner'].create({'name': 'Care C', 'is_school_caretaker': True, 'phone': '9000000002'})
        cls.vehicle = env['school.vehicle'].create({'name': 'Van 1', 'vehicle_number': 'TN01ST0001', 'driver_id': cls.driver.id,
                                                    'caretaker_id': cls.caretaker.id})
        cls.vehicle.action_generate_gps_token()
        cls.points = [offset_point(*BASE, north_m=m) for m in (0, 2000, 4000)]
        cls.campus = offset_point(*BASE, north_m=6000)
        cls.route = env['school.transport.route'].create({
            'name': 'Route A', 'vehicle_id': cls.vehicle.id,
            'stop_ids': [(0, 0, {'name': 'Stop %s' % (i + 1), 'sequence': 10 * (i + 1), 'latitude': p[0], 'longitude': p[1]})
                         for i, p in enumerate(cls.points)]})
        cls.stop1, cls.stop2, cls.stop3 = cls.route.stop_ids.sorted('sequence')
        klass = env['school.class'].create({'name': 'ST Class', 'code': 'STC1'})
        sec = env['school.section'].create({'name': 'A', 'class_id': klass.id, 'capacity': 40})
        year = env['school.academic.year'].create(
            {'name': 'ST Year', 'code': 'STY', 'date_start': '2026-01-01', 'date_end': '2026-12-31'})

        def student(name, route, stop):
            return env['school.student'].create({
                'name': name, 'class_id': klass.id, 'section_id': sec.id, 'academic_year_id': year.id,
                'transport_route_id': route.id if route else False, 'van_boarding_point_id': stop.id if stop else False})
        cls.s1, cls.s2 = student('Asha', cls.route, cls.stop1), student('Bala', cls.route, cls.stop1)
        cls.s3 = student('Charu', cls.route, cls.stop2)
        cls.outsider = student('Outsider', False, False)
        cls.parent_a = env['school.parent'].create({'name': 'Parent A', 'relation': 'father', 'phone': '9000000010',
                                                    'email': 'a@test.example', 'student_ids': [(6, 0, (cls.s1 | cls.s2).ids)]})
        cls.parent_b = env['school.parent'].create({'name': 'Parent B', 'relation': 'mother', 'phone': '9000000011',
                                                    'email': 'b@test.example', 'student_ids': [(6, 0, cls.s3.ids)]})
        cls.cfg = env['school.transport.config']._get()
        cls.cfg.write({'campus_latitude': cls.campus[0], 'campus_longitude': cls.campus[1], 'campus_radius_m': 200})
        cls.staff = _user(env, 'st_staff', 'ad_school_management.group_school_admin')
        cls.principal = _user(env, 'st_principal', 'ad_school_management.group_school_principal')
        cls.teacher = _user(env, 'st_teacher', 'ad_school_management.group_school_teacher')


@tagged('post_install', '-at_install', 'school_smart_transport')
class TestSmartTransport(_World, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._build()

    def setUp(self):
        super().setUp()
        self.clock = T0
        self.Trip = self.env['school.transport.trip']
        self.Event = self.env['school.transport.event']

    # ---------------------------------------------------------------- helpers
    def _ping(self, point, speed=20.0, north=0.0, east=0.0, seconds=20, at=None):
        lat, lon = offset_point(point[0], point[1], north_m=north, east_m=east)
        self.clock = at or (self.clock + timedelta(seconds=seconds))
        self.vehicle._register_location(lat, lon, speed=speed, recorded_at=self.clock)

    def _trip(self, trip_type='morning', start=True):
        trip = self.Trip.create({'route_id': self.route.id, 'date': '2026-09-01', 'trip_type': trip_type})
        if start:
            trip.action_start()
        return trip

    def _events(self, trip, event_type):
        return trip.event_ids.filtered(lambda e: e.event_type == event_type)

    def _mails(self, user_or_partner):
        partner = getattr(user_or_partner, 'partner_id', user_or_partner)
        return self.env['mail.message'].sudo().search([('partner_ids', 'in', partner.ids)], order='id')

    def _notes(self, student=None, kind=None):
        domain = ([('student_id', '=', student.id)] if student else []) + ([('kind', '=', kind)] if kind else [])
        return self.env['school.transport.notification'].sudo().search(domain)

    # ---------------------------------------------------------------- geofencing data
    def test_stop_coordinates(self):
        stop = self.env['school.transport.stop'].new({'name': 'New stop'})
        stop.coordinates_text = '11.0168, 76.9558'
        stop._onchange_coordinates_text()
        self.assertEqual((stop.latitude, stop.longitude), (11.0168, 76.9558))
        stop.coordinates_text = 'not coordinates'
        stop._onchange_coordinates_text()
        self.assertEqual((stop.latitude, stop.longitude), (11.0168, 76.9558))                      # a bad paste changes nothing
        self.assertTrue(self.stop1.has_location)
        self.assertIn('openstreetmap.org', self.stop1.map_url)
        self.assertEqual(self.stop1._geofence_radius(self.cfg), self.cfg.arrival_radius_m)           # no own radius: the default
        self.stop1.radius_m = 150
        self.assertEqual(self.stop1._geofence_radius(self.cfg), 150)
        with self.assertRaises(ValidationError):
            self.stop1.latitude = 123.0
        with self.assertRaises(ValidationError):
            self.stop1.radius_m = -5

    # ---------------------------------------------------------------- trip life
    def test_trip_start_rules(self):
        trip = self._trip(start=False)
        self.assertEqual((trip.state, trip.vehicle_id, trip.driver_id, trip.caretaker_id),
                         ('planned', self.vehicle, self.driver, self.caretaker))
        trip.action_start()
        self.assertEqual(trip.state, 'running')
        self.assertEqual(trip.stop_line_ids.mapped('stop_id'), self.stop1 | self.stop2 | self.stop3)
        self.assertEqual(trip.expected_count, 3)
        self.assertEqual(sorted(trip.attendance_id.line_ids.mapped('student_id').ids), sorted((self.s1 | self.s2 | self.s3).ids))
        self.assertEqual(len(self._events(trip, 'trip_start')), 1)
        with self.assertRaises(UserError):
            trip.action_start()                                                                       # already running
        evening = self._trip('evening', start=False)
        with self.assertRaises(UserError):
            evening.action_start()                                                                    # the van is on another trip
        with self.assertRaises(Exception):                                                            # one trip per route, day and type
            with self.env.cr.savepoint():
                self._trip('morning', start=False)
        trip.action_end()
        evening.action_start()                                                                        # free again
        self.assertEqual(evening.state, 'running')

    def test_a_planned_trip_without_a_vehicle_cannot_start(self):
        route = self.env['school.transport.route'].create({'name': 'No van route'})
        trip = self.Trip.create({'route_id': route.id, 'date': '2026-09-01'})
        with self.assertRaises(UserError):
            trip.action_start()

    # ---------------------------------------------------------------- van approaching
    def test_van_approaching_tells_the_parents_of_that_stop_only(self):
        trip = self._trip()
        self._ping(self.points[0], north=2500, speed=25)
        self.assertFalse(self._events(trip, 'approaching'))                                           # still far away
        self.assertFalse(self._notes(kind='approaching'))
        self._ping(self.points[0], north=450, speed=25)                                               # inside 500 m
        self.assertEqual(len(self._events(trip, 'approaching')), 1)
        notes = self._notes(kind='approaching')
        self.assertEqual(sorted(notes.mapped('student_id').ids), sorted((self.s1 | self.s2).ids))     # Stop 1 only
        self.assertEqual(set(notes.mapped('partner_id')), {self.parent_a.partner_id})                 # not parent B
        self.assertIn('Stop 1', notes[0].message)
        self.assertRegex(notes[0].message, r'about \d+ minutes')
        self.assertTrue(all(notes.mapped('inbox_sent')))
        self.assertTrue(self._mails(self.parent_a.partner_id).filtered(lambda m: 'approaching' in (m.body or '')))
        self.assertFalse(self._mails(self.parent_b.partner_id).filtered(lambda m: 'approaching' in (m.body or '')))
        self.assertTrue(trip.stop_line_ids.filtered(lambda l: l.stop_id == self.stop1).approach_notified)
        self._ping(self.points[0], north=300, speed=25)                                               # closer: no second message
        self.assertEqual(len(self._events(trip, 'approaching')), 1)
        self.assertEqual(len(self._notes(kind='approaching')), 2)

    def test_approaching_message_can_be_switched_off(self):
        self.cfg.notify_parent_approach = False
        trip = self._trip()
        self._ping(self.points[0], north=300)
        self.assertEqual(len(self._events(trip, 'approaching')), 1)                                   # still logged for the school
        self.assertFalse(self._notes(kind='approaching'))                                             # but no parent is told

    def test_arrival_and_departure_geofence(self):
        trip = self._trip()
        line = trip.stop_line_ids.filtered(lambda l: l.stop_id == self.stop1)
        self._ping(self.points[0], north=40, speed=10)                                                # straight into the circle
        self.assertTrue(line.arrived_at)
        self.assertEqual(line.state, 'arrived')
        self.assertTrue(line.approach_notified)                                                       # parents told "at your stop"
        self.assertIn('at Stop 1 now', self._notes(kind='approaching')[0].message)
        enter = self._events(trip, 'geofence_enter').filtered(lambda e: e.stop_id == self.stop1)
        self.assertEqual(len(enter), 1)
        self._ping(self.points[0], north=60, speed=5)                                                 # still inside: nothing new
        self.assertEqual(len(self._events(trip, 'geofence_enter').filtered(lambda e: e.stop_id == self.stop1)), 1)
        self._ping(self.points[0], north=300, speed=20)
        self.assertTrue(line.departed_at)
        self.assertEqual(line.state, 'left')
        self.assertEqual(len(self._events(trip, 'geofence_exit').filtered(lambda e: e.stop_id == self.stop1)), 1)
        self.assertEqual(trip.next_stop_id, self.stop2)

    # ---------------------------------------------------------------- boarding / off-boarding
    def test_boarding_record_and_parent_notification(self):
        trip = self._trip()
        record = trip.action_board_student(self.s1)
        self.assertEqual((record.event_type, record.student_id, record.stop_id, record.source), ('board', self.s1, self.stop1, 'driver'))
        self.assertEqual(record.confirmed_by, self.env.user)
        self.assertEqual((trip.boarded_count, trip.on_board_count, trip.offboarded_count), (1, 1, 0))
        line = trip.attendance_id.line_ids.filtered(lambda l: l.student_id == self.s1)
        self.assertEqual((line.status, bool(line.boarded_at)), ('boarded', True))                     # the attendance follows
        note = self._notes(self.s1, 'boarded')
        self.assertEqual(len(note), 1)
        self.assertIn('Asha boarded the van', note.message)
        self.assertIn('Stop 1', note.message)
        self.assertTrue(record.parent_notified)
        self.assertEqual(trip.action_board_student(self.s1), record)                                  # a second tap is the same record
        self.assertEqual(len(self._notes(self.s1, 'boarded')), 1)
        with self.assertRaises(UserError):
            trip.action_board_student(self.outsider)                                                  # not on this route
        with self.assertRaises(UserError):
            trip.action_offboard_student(self.s2)                                                     # never boarded

    def test_boarding_needs_a_running_trip(self):
        trip = self._trip(start=False)
        with self.assertRaises(UserError):
            trip.action_board_student(self.s1)
        trip.action_start()
        trip.action_board_student(self.s1)
        trip.action_end()
        with self.assertRaises(UserError):
            trip.action_offboard_student(self.s1)

    def test_evening_drop_tells_the_parent_when_the_child_reaches_the_stop(self):
        trip = self._trip('evening')
        trip.action_board_student(self.s3)
        self.assertIn('at school', self._notes(self.s3, 'boarded').message)                           # evening: boarded at school
        record = trip.action_offboard_student(self.s3)
        self.assertEqual(record.event_type, 'offboard')
        note = self._notes(self.s3, 'reached_stop')
        self.assertEqual(len(note), 1)
        self.assertIn('Charu reached Stop 2', note.message)
        self.assertEqual(trip.attendance_id.line_ids.filtered(lambda l: l.student_id == self.s3).offboarded_at, record.event_at)
        self.assertEqual((trip.on_board_count, trip.offboarded_count), (0, 1))
        self.assertEqual(trip.action_offboard_student(self.s3), record)                               # idempotent

    def test_morning_van_reaching_school_drops_everybody_and_tells_the_parents(self):
        trip = self._trip()
        trip.action_board_student(self.s1)
        trip.action_board_student(self.s3)
        self._ping(self.points[2], north=1000, speed=30)                                              # on the way
        self.assertEqual(trip.on_board_count, 2)
        self._ping(self.campus, north=100, speed=15)                                                  # inside the school circle
        self.assertTrue(trip.in_campus)
        self.assertEqual(trip.on_board_count, 0)
        records = trip.boarding_ids.filtered(lambda r: r.event_type == 'offboard')
        self.assertEqual(sorted(records.mapped('student_id').ids), sorted((self.s1 | self.s3).ids))
        self.assertEqual(set(records.mapped('source')), {'auto_geofence'})
        self.assertEqual(len(self._notes(kind='reached_school')), 2)
        self.assertIn('reached school', self._notes(self.s1, 'reached_school').message)
        self.assertEqual(len(self._events(trip, 'geofence_enter').filtered(lambda e: not e.stop_id)), 1)
        self._ping(self.campus, north=800, speed=15)
        self.assertFalse(trip.in_campus)
        self.assertEqual(len(self._events(trip, 'geofence_exit').filtered(lambda e: not e.stop_id)), 1)

    def test_boarding_messages_can_be_switched_off(self):
        self.cfg.write({'notify_parent_board': False, 'notify_parent_reached': False})
        trip = self._trip()
        record = trip.action_board_student(self.s1)
        trip.action_offboard_student(self.s1)
        self.assertFalse(self._notes())
        self.assertFalse(record.parent_notified)
        self.assertEqual(len(trip.boarding_ids), 2)                                                   # the records are kept anyway

    def test_a_whatsapp_copy_follows_the_school_template(self):
        account = self.env['school.whatsapp.account'].create({'name': 'WA', 'test_mode': True})
        trip = self._trip()
        trip.action_board_student(self.s3)
        note = self._notes(self.s3, 'boarded')
        self.assertEqual(note.whatsapp_state, 'test')
        log = self.env['school.whatsapp.message'].sudo().search([('account_id', '=', account.id)])
        self.assertEqual(len(log), 1)
        self.assertEqual(log.template_name, account.transport_template)
        self.assertIn('Charu boarded the van', log.parameters)

    # ---------------------------------------------------------------- speed
    def test_excessive_speed_alert_with_noise_filter_and_pause(self):
        self.assertFalse(self.Event.search([('event_type', '=', 'speeding')]))
        self._ping(self.points[0], speed=70, north=-3000)                                             # one fast ping: GPS noise
        self.assertFalse(self.Event.search([('event_type', '=', 'speeding')]))
        self._ping(self.points[0], speed=72, north=-3000)                                             # second in a row: alert
        alert = self.Event.search([('event_type', '=', 'speeding')])
        self.assertEqual((len(alert), alert.severity, alert.state, alert.vehicle_id), (1, 'warning', 'open', self.vehicle))
        self.assertIn('72 km/h', alert.message)
        self.assertTrue(alert.staff_notified)
        for user in (self.staff, self.principal):
            self.assertTrue(self._mails(user).filtered(lambda m: 'Excessive speed' in (m.subject or '')), user.login)
        self.assertFalse(self._mails(self.teacher).filtered(lambda m: 'Excessive speed' in (m.subject or '')))
        self._ping(self.points[0], speed=75, north=-3000)                                             # inside the pause
        self.assertEqual(self.Event.search_count([('event_type', '=', 'speeding')]), 1)
        self._ping(self.points[0], speed=50, north=-3000)                                             # back under: the count restarts
        self.assertEqual(self.vehicle.over_speed_count, 0)
        self._ping(self.points[0], speed=80, north=-3000, seconds=400)
        self._ping(self.points[0], speed=80, north=-3000)
        self.assertEqual(self.Event.search_count([('event_type', '=', 'speeding')]), 2)               # after the pause: again

    def test_a_vehicle_can_have_its_own_speed_limit(self):
        self.vehicle.speed_limit_kmh = 30
        self._ping(self.points[0], speed=40, north=-3000)
        self._ping(self.points[0], speed=41, north=-3000)
        self.assertEqual(self.Event.search_count([('event_type', '=', 'speeding')]), 1)

    def test_speeding_is_counted_in_the_running_trip(self):
        trip = self._trip()
        self._ping(self.points[0], speed=70, north=1000)
        self._ping(self.points[0], speed=70, north=1000)
        self.assertEqual((trip.speeding_count, trip.max_speed), (1, 70))
        self.assertEqual(trip.behaviour_score, 95.0)

    # ---------------------------------------------------------------- harsh driving
    def test_harsh_braking_and_acceleration(self):
        trip = self._trip()
        self._ping(self.points[0], speed=45, north=1000)
        self._ping(self.points[0], speed=5, north=1000, seconds=2)                                     # -40 km/h in 2 s
        self.assertEqual(len(self._events(trip, 'harsh_brake')), 1)
        self._ping(self.points[0], speed=50, north=1000, seconds=3)                                    # +45 km/h in 3 s
        self.assertEqual(len(self._events(trip, 'harsh_accel')), 1)
        self._ping(self.points[0], speed=30, north=1000, seconds=3)                                    # -20 in 3 s = 6.7/s: normal
        self.assertEqual(len(self._events(trip, 'harsh_brake')), 1)
        self._ping(self.points[0], speed=2, north=1000, seconds=40)                                    # a big drop over 40 s: normal
        self.assertEqual(len(self._events(trip, 'harsh_brake')), 1)
        self.assertEqual((trip.harsh_count, trip.behaviour_score), (2, 96.0))
        self.assertTrue(all(e.state == 'resolved' for e in self._events(trip, 'harsh_brake')))         # behaviour, not an alert

    def test_harsh_driving_needs_a_running_trip(self):
        self._ping(self.points[0], speed=45, north=1000)
        self._ping(self.points[0], speed=5, north=1000, seconds=2)
        self.assertFalse(self.Event.search([('event_type', '=', 'harsh_brake')]))

    # ---------------------------------------------------------------- route deviation
    def test_route_deviation_alert_and_return(self):
        trip = self._trip()
        self._ping(self.points[1], east=100, speed=30)                                                 # on the route (100 m aside)
        self.assertFalse(self._events(trip, 'deviation'))
        self._ping(self.points[1], east=900, speed=30)                                                 # off the route: the first ping
        self.assertFalse(self._events(trip, 'deviation'))
        self._ping(self.points[1], east=950, speed=30)                                                 # the second one: alert
        alert = self._events(trip, 'deviation')
        self.assertEqual((len(alert), alert.severity, alert.state), (1, 'warning', 'open'))
        self.assertTrue(alert.staff_notified)
        self.assertTrue(trip.deviation_active)
        self._ping(self.points[1], east=1000, speed=30)                                                # still off: no second alert
        self.assertEqual(len(self._events(trip, 'deviation')), 1)
        self._ping(self.points[1], east=50, speed=30)                                                  # back
        self.assertFalse(trip.deviation_active)
        self.assertEqual(len(self._events(trip, 'back_on_route')), 1)
        self._ping(self.points[1], east=1200, speed=30)
        self._ping(self.points[1], east=1200, speed=30)                                                # off again: a new alert
        self.assertEqual((len(self._events(trip, 'deviation')), trip.deviation_count), (2, 2))
        self.assertEqual(trip.behaviour_score, 90.0)

    def test_the_route_runs_on_to_the_school(self):
        trip = self._trip()
        self._ping(self.campus, north=-1000, east=50, speed=30)                                        # between the last stop and school
        self._ping(self.campus, north=-900, east=50, speed=30)
        self.assertFalse(self._events(trip, 'deviation'))

    # ---------------------------------------------------------------- stopped for long
    def test_stopped_away_from_a_stop_is_a_possible_breakdown(self):
        trip = self._trip()
        self._ping(self.points[0], north=1000, speed=0)                                                # between stop 1 and 2
        self._ping(self.points[0], north=1000, speed=0, seconds=300)                                   # 5 minutes: not yet
        self.assertFalse(self._events(trip, 'stationary'))
        self._ping(self.points[0], north=1000, speed=0, seconds=400)                                   # 11+ minutes
        alert = self._events(trip, 'stationary')
        self.assertEqual((len(alert), alert.severity, alert.staff_notified), (1, 'warning', True))
        self._ping(self.points[0], north=1000, speed=0, seconds=60)                                    # still stopped: only one alert
        self.assertEqual(len(self._events(trip, 'stationary')), 1)
        self._ping(self.points[0], north=1100, speed=20)                                               # moving again resets
        self.assertFalse(trip.stationary_since)

    def test_waiting_at_a_stop_or_the_school_is_normal(self):
        trip = self._trip()
        self._ping(self.points[0], north=20, speed=0)
        self._ping(self.points[0], north=20, speed=0, seconds=900)
        self.assertFalse(self._events(trip, 'stationary'))
        self._ping(self.campus, north=10, speed=0, seconds=60)
        self._ping(self.campus, north=10, speed=0, seconds=900)
        self.assertFalse(self._events(trip, 'stationary'))

    # ---------------------------------------------------------------- estimated arrival time
    def test_estimated_arrival_times(self):
        trip = self._trip()
        lines = trip.stop_line_ids.sorted('sequence')
        self._ping(self.points[0], north=-1500, speed=26)                                              # 1.5 km before stop 1
        etas = lines.mapped('eta')
        self.assertTrue(all(etas))
        self.assertEqual(etas, sorted(etas))                                                           # later stops later
        first_minutes = (lines[0].eta - self.clock).total_seconds() / 60.0
        self.assertAlmostEqual(first_minutes, 1500 * 1.3 / 1000 / 26 * 60, delta=0.5)                  # distance x road factor / speed
        self.assertAlmostEqual((lines[1].eta - lines[0].eta).total_seconds() / 60.0, 2000 * 1.3 / 1000 / 26 * 60, delta=0.5)
        self.assertTrue(trip.eta_campus)
        self.assertGreater(trip.eta_campus, lines[2].eta)
        self.assertEqual((trip.next_stop_id, trip.next_eta), (self.stop1, lines[0].eta))
        far = lines[0].eta
        self._ping(self.points[0], north=-500, speed=26)                                               # closer: sooner
        self.assertLess(lines[0].eta - self.clock, far - (self.clock - timedelta(seconds=20)))
        self._ping(self.points[0], north=30, speed=5)                                                  # arrived: the next stop is next
        self.assertEqual(trip.next_stop_id, self.stop2)
        self.assertGreater(lines[1].eta, self.clock)

    # ---------------------------------------------------------------- breakdown
    def test_driver_reported_breakdown(self):
        trip = self._trip()
        trip.action_board_student(self.s1)
        event = trip.action_breakdown(note='Engine overheated', source='driver')
        self.assertEqual((event.event_type, event.severity, event.state), ('breakdown', 'critical', 'open'))
        self.assertIn('Engine overheated', event.message)
        self.assertTrue(event.staff_notified)
        self.assertEqual(trip.breakdown_count, 1)
        notes = self._notes(kind='breakdown')                                                          # the parents of the route
        self.assertEqual(sorted(notes.mapped('student_id').ids), sorted((self.s1 | self.s2 | self.s3).ids))
        self.assertIn('replacement', notes[0].message)
        self.assertTrue(event.parents_notified)
        with self.assertRaises(UserError):
            event.action_inform_parents()                                                              # only once
        self.assertEqual(event.action_open_route()['res_id'], self.route.id)                           # to replace the vehicle

    def test_breakdown_parent_message_can_wait_for_the_school(self):
        self.cfg.notify_parent_breakdown = False
        trip = self._trip()
        event = trip.action_breakdown()
        self.assertFalse(self._notes(kind='breakdown'))
        event.action_inform_parents()                                                                  # the school decides
        self.assertTrue(self._notes(kind='breakdown'))

    def test_critical_events_need_a_note_to_be_resolved(self):
        trip = self._trip()
        event = trip.action_breakdown()
        event.with_user(self.staff).action_acknowledge()
        self.assertEqual((event.state, event.handled_by), ('acknowledged', self.staff))
        with self.assertRaises(UserError):
            event.with_user(self.staff).action_resolve()
        event.note = 'Replacement van sent, parents informed.'
        event.with_user(self.staff).action_resolve()
        self.assertEqual(event.state, 'resolved')

    # ---------------------------------------------------------------- SOS
    def test_driver_sos_alerts_the_school_first(self):
        trip = self._trip()
        event = trip._raise_sos(source='driver', note='Accident ahead')
        self.assertEqual((event.event_type, event.severity, event.state), ('sos', 'critical', 'open'))
        self.assertTrue(event.staff_notified)
        for user in (self.staff, self.principal):
            self.assertTrue(self._mails(user).filtered(lambda m: 'SOS' in (m.subject or '') or 'Emergency SOS' in (m.body or '')))
        self.assertFalse(self._notes(kind='sos'))                                                      # parents: only on the school's say
        self.assertEqual(trip._raise_sos(source='driver'), event)                                      # a double press is one alarm
        self.assertEqual(self.Event.search_count([('event_type', '=', 'sos')]), 1)
        event.action_inform_parents()
        self.assertTrue(self._notes(kind='sos'))
        self.assertEqual(trip.sos_count, 1)

    def test_sos_can_also_inform_the_parents_automatically(self):
        self.cfg.notify_parent_sos = True
        trip = self._trip()
        trip._raise_sos(source='driver')
        self.assertEqual(len(self._notes(kind='sos')), 3)                                              # one per child and parent

    def test_sos_from_the_device_works_without_a_started_trip(self):
        event = self.vehicle._raise_sos(source='GPS device', lat=11.01, lon=77.01)
        self.assertEqual((event.severity, event.trip_id, event.latitude), ('critical', self.Trip, 11.01))
        self.assertTrue(event.staff_notified)
        self.assertEqual(self.vehicle._raise_sos(source='GPS device'), event)

    # ---------------------------------------------------------------- end of the trip
    def test_students_left_on_board_are_reported(self):
        trip = self._trip()
        trip.action_board_student(self.s1)
        trip.action_board_student(self.s2)
        trip.action_offboard_student(self.s1)
        trip.action_end()
        alert = self._events(trip, 'left_on_board')
        self.assertEqual((len(alert), alert.severity, alert.staff_notified), (1, 'critical', True))
        self.assertIn('Bala', alert.message)
        self.assertNotIn('Asha', alert.message)
        self.assertEqual((trip.state, trip.left_on_board_count, trip.behaviour_score), ('done', 1, 80.0))
        self.assertTrue(trip.ended_at)

    def test_the_boarding_records_decide_who_travelled(self):
        trip = self._trip()
        trip.action_board_student(self.s1)
        trip.action_offboard_student(self.s1)
        trip.action_end()
        status = {l.student_id: l.status for l in trip.attendance_id.line_ids}
        self.assertEqual(status, {self.s1: 'boarded', self.s2: 'absent', self.s3: 'absent'})
        # a trip where nobody used the boarding buttons keeps the attendance the way the driver marked it
        evening = self._trip('evening')
        evening.action_end()
        self.assertEqual(set(evening.attendance_id.line_ids.mapped('status')), {'boarded'})
        self.assertFalse(self._events(evening, 'left_on_board'))

    def test_a_finished_trip_is_not_touched_by_later_pings(self):
        trip = self._trip()
        trip.action_end()
        events = len(trip.event_ids)
        self._ping(self.points[0], north=300, speed=20)
        self.assertEqual(len(trip.event_ids), events)
        self.assertFalse(trip.last_ping_at)

    def test_stale_running_trips_are_closed_by_the_cron(self):
        old = self._trip()
        old.started_at = fields.Datetime.now() - timedelta(hours=10)
        self.Trip._cron_close_stale_trips(hours=8)
        self.assertEqual(old.state, 'done')
        fresh = self._trip('evening')
        self.Trip._cron_close_stale_trips(hours=8)
        self.assertEqual(fresh.state, 'running')

    # ---------------------------------------------------------------- driver behaviour report
    def test_driver_behaviour_numbers_per_driver(self):
        trip = self._trip()
        self._ping(self.points[0], speed=70, north=-3000)
        self._ping(self.points[0], speed=70, north=-3000)
        self._ping(self.points[1], east=900, speed=30)
        self._ping(self.points[1], east=950, speed=30)
        trip.action_end()
        rows = self.Trip._read_group([('state', '=', 'done')], ['driver_id'],
                                     ['speeding_count:sum', 'deviation_count:sum', 'behaviour_score:avg', 'distance_km:sum'])
        driver, speeding, deviations, score, distance = rows[0]
        self.assertEqual((driver, speeding, deviations, score), (self.driver, 1, 1, 90.0))
        self.assertGreater(distance, 0)

    # ---------------------------------------------------------------- robustness
    def test_a_late_ping_is_stored_but_raises_nothing(self):
        self._ping(self.points[0], speed=70, north=-3000)
        before = self.env['school.vehicle.location'].search_count([('vehicle_id', '=', self.vehicle.id)])
        self._ping(self.points[0], speed=90, north=-3000, at=self.clock - timedelta(minutes=5))        # older than the last ping
        self.assertEqual(self.env['school.vehicle.location'].search_count([('vehicle_id', '=', self.vehicle.id)]), before + 1)
        self.assertFalse(self.Event.search([('event_type', '=', 'speeding')]))

    def test_an_alert_check_that_fails_never_loses_the_gps_ping(self):
        with patch.object(type(self.Trip), '_process_ping', side_effect=RuntimeError('boom')):
            self._ping(self.points[0], speed=33, north=-3000)
        self.assertEqual(self.vehicle.last_speed, 33)
        self.assertTrue(self.vehicle.last_location_at)

    # ---------------------------------------------------------------- who sees what
    def test_only_admin_and_principal_see_trips_alerts_and_records(self):
        trip = self._trip()
        trip._raise_sos()
        trip.action_board_student(self.s1)
        for user in (self.staff, self.principal):
            self.assertTrue(self.Trip.with_user(user).search([]))
            self.assertTrue(self.Event.with_user(user).search([]))
            self.assertTrue(self.env['school.transport.boarding'].with_user(user).search([]))
        for model in ('school.transport.trip', 'school.transport.event', 'school.transport.boarding',
                      'school.transport.notification', 'school.transport.config'):
            with self.assertRaises(AccessError, msg=model):
                self.env[model].with_user(self.teacher).search([])
        with self.assertRaises(AccessError):
            self.env['school.transport.ping.wizard'].with_user(self.principal).create({'vehicle_id': self.vehicle.id})

    # ---------------------------------------------------------------- the test tool
    def test_gps_test_wizard_makes_a_real_approaching_alert(self):
        trip = self._trip()
        wizard = self.env['school.transport.ping.wizard'].with_user(self.staff).create({
            'vehicle_id': self.vehicle.id, 'mode': 'stop', 'stop_id': self.stop1.id, 'meters_before': 400, 'speed': 20,
            'ping_at': self.clock + timedelta(minutes=1)})
        result = wizard.action_send()
        self.assertIn('Van approaching a stop', result['params']['message'])
        self.assertEqual(len(self._events(trip, 'approaching')), 1)
        school = self.env['school.transport.ping.wizard'].with_user(self.staff).create({
            'vehicle_id': self.vehicle.id, 'mode': 'campus', 'speed': 10, 'ping_at': self.clock + timedelta(minutes=5)})
        school.action_send()
        self.assertTrue(trip.in_campus)
        no_stop = self.env['school.transport.ping.wizard'].with_user(self.staff).create({'vehicle_id': self.vehicle.id, 'mode': 'stop'})
        with self.assertRaises(UserError):
            no_stop.action_send()
        self.cfg.campus_latitude = 0.0
        with self.assertRaises(UserError):
            school.action_send()

    def test_settings_record_per_school(self):
        self.assertEqual(self.env['school.transport.config']._get(), self.cfg)
        action = self.env['school.transport.config'].with_user(self.staff).action_open_settings()
        self.assertEqual(action['res_id'], self.cfg.id)
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.env['school.transport.config'].create({'company_id': self.env.company.id})


@tagged('post_install', '-at_install', 'school_smart_transport')
class TestSmartTransportPortal(_World, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._build()
        env = cls.env
        portal = env.ref('base.group_portal')
        make = lambda name, partner: env['res.users'].create({                                          # noqa: E731
            'name': name, 'login': name, 'password': name, 'partner_id': partner.id, 'group_ids': [(6, 0, [portal.id])]})
        cls.driver_user = make('stdriver', cls.driver)
        other_driver = env['res.partner'].create({'name': 'Other Driver', 'is_school_driver': True})
        cls.other_driver_user = make('stdriver2', other_driver)
        cls.care_user = make('stcare', cls.caretaker)
        cls.other_caretaker = env['res.partner'].create({'name': 'Other Care', 'is_school_caretaker': True})
        cls.other_care_user = make('stcare2', cls.other_caretaker)
        cls.parent_user = make('stparent', cls.parent_a.partner_id)
        cls.other_parent_user = make('stparent2', cls.parent_b.partner_id)
        cls.Trip = env['school.transport.trip']

    def _csrf(self, html):
        return re.search(r'name="csrf_token"\s+value="([^"]+)"', html).group(1)

    def _post(self, url, **data):
        data['csrf_token'] = self._csrf(self.url_open('/my/account').text)
        return self.url_open(url, data=data)

    def _trip(self):
        return self.Trip.sudo().search([('route_id', '=', self.route.id), ('trip_type', '=', 'morning')], limit=1)

    def test_driver_page_runs_a_whole_trip(self):
        self.authenticate('stdriver', 'stdriver')
        home = self.url_open('/my/driver')
        self.assertIn('/my/driver/live/%s/morning' % self.route.id, home.text)                          # the new button
        page = self.url_open('/my/driver/live/%s/morning' % self.route.id)
        self.assertEqual(page.status_code, 200)
        for text in ('Start Trip', 'Route A', 'Stop 1', 'Asha', 'Bala', 'Charu'):
            self.assertIn(text, page.text)
        self.assertNotIn('EMERGENCY SOS', page.text)                                                    # only while running
        trip = self._trip()
        self.assertEqual(trip.state, 'planned')
        self._post('/my/driver/trip-action/%s/start' % trip.id)
        self.assertEqual(trip.state, 'running')
        page = self.url_open('/my/driver/live/%s/morning' % self.route.id)
        for text in ('EMERGENCY SOS', 'Report Vehicle Breakdown', 'Finish Trip', 'Start Sharing Location', 'Boarded'):
            self.assertIn(text, page.text)
        self._post('/my/driver/trip-action/%s/student/%s/board' % (trip.id, self.s1.id))
        self.assertEqual(trip.boarding_ids.student_id, self.s1)
        self.assertEqual(trip.boarding_ids.confirmed_by, self.driver_user)
        self.assertTrue(self.env['school.transport.notification'].sudo().search([('student_id', '=', self.s1.id), ('kind', '=', 'boarded')]))
        self.assertIn('On board', self.url_open('/my/driver/live/%s/morning' % self.route.id).text)
        # finishing with a student on board asks first
        refused = self._post('/my/driver/trip-action/%s/end' % trip.id)
        self.assertEqual(trip.state, 'running')
        self.assertIn('Students are still on board', refused.text)
        self._post('/my/driver/trip-action/%s/student/%s/offboard' % (trip.id, self.s1.id))
        self.assertEqual(trip.on_board_count, 0)
        self._post('/my/driver/trip-action/%s/end' % trip.id)
        self.assertEqual(trip.state, 'done')

    def test_finishing_anyway_reports_the_student_left_on_board(self):
        self.authenticate('stdriver', 'stdriver')
        self.url_open('/my/driver/live/%s/morning' % self.route.id)
        trip = self._trip()
        self._post('/my/driver/trip-action/%s/start' % trip.id)
        self._post('/my/driver/trip-action/%s/student/%s/board' % (trip.id, self.s2.id))
        self._post('/my/driver/trip-action/%s/end' % trip.id, confirm='1')
        self.assertEqual(trip.state, 'done')
        self.assertEqual(len(trip.event_ids.filtered(lambda e: e.event_type == 'left_on_board')), 1)

    def test_driver_page_sos_and_breakdown(self):
        self.authenticate('stdriver', 'stdriver')
        self.url_open('/my/driver/live/%s/morning' % self.route.id)
        trip = self._trip()
        self._post('/my/driver/trip-action/%s/start' % trip.id)
        self._post('/my/driver/trip-action/%s/breakdown' % trip.id, note='Flat tyre')
        self._post('/my/driver/trip-action/%s/sos' % trip.id, note='Need help')
        events = trip.event_ids
        self.assertIn('Flat tyre', events.filtered(lambda e: e.event_type == 'breakdown').message)
        self.assertIn('Need help', events.filtered(lambda e: e.event_type == 'sos').message)
        self.assertEqual((trip.breakdown_count, trip.sos_count), (1, 1))

    def test_another_driver_cannot_see_or_run_this_trip(self):
        self.authenticate('stdriver2', 'stdriver2')
        page = self.url_open('/my/driver/live/%s/morning' % self.route.id)
        self.assertNotIn('Start Trip', page.text)
        self.assertNotIn('Asha', page.text)
        self.assertFalse(self._trip())                                                                  # nothing was created for him
        self.authenticate('stdriver', 'stdriver')
        self.url_open('/my/driver/live/%s/morning' % self.route.id)
        trip = self._trip()
        self.authenticate('stdriver2', 'stdriver2')
        csrf = self._csrf(self.url_open('/my/account').text)
        self.url_open('/my/driver/trip-action/%s/start' % trip.id, data={'csrf_token': csrf})
        self.url_open('/my/driver/trip-action/%s/sos' % trip.id, data={'csrf_token': csrf})
        self.assertEqual(trip.state, 'planned')
        self.assertFalse(trip.event_ids)

    def test_parent_sees_own_childs_trip_and_messages(self):
        self.authenticate('stdriver', 'stdriver')
        self.url_open('/my/driver/live/%s/morning' % self.route.id)
        trip = self._trip()
        trip.date = fields.Date.today()
        self._post('/my/driver/trip-action/%s/start' % trip.id)
        self._post('/my/driver/trip-action/%s/student/%s/board' % (trip.id, self.s1.id))
        self.vehicle._register_location(*offset_point(*self.points[0], north_m=-2000), speed=26, recorded_at=fields.Datetime.now())
        self.authenticate('stparent', 'stparent')
        page = self.url_open('/my/school/student/%s/transport' % self.s1.id)
        self.assertEqual(page.status_code, 200)
        for text in ('Transport - Asha', 'Stop: Stop 1', 'On the way', 'Boarded at', 'The van is expected at', 'Asha boarded the van'):
            self.assertIn(text, page.text)
        self.assertNotIn('Charu', page.text)
        self.assertEqual(self.url_open('/my/school/student/%s/transport' % self.s3.id, allow_redirects=False).status_code, 303)  # not his child
        self.authenticate('stparent2', 'stparent2')
        other = self.url_open('/my/school/student/%s/transport' % self.s3.id)
        self.assertIn('Transport - Charu', other.text)
        self.assertNotIn('Asha boarded', other.text)

    def test_device_sos_endpoint(self):
        token = self.vehicle.sudo().gps_api_token
        self.assertEqual(self.url_open('/school/transport/sos?token=wrong').status_code, 401)
        self.assertEqual(self.url_open('/school/transport/sos').status_code, 401)
        ok = self.url_open('/school/transport/sos?token=%s&lat=11.05&lon=77.02' % token)
        self.assertEqual((ok.status_code, ok.json()), (200, {'ok': True}))
        events = self.env['school.transport.event'].sudo().search([('vehicle_id', '=', self.vehicle.id), ('event_type', '=', 'sos')])
        self.assertEqual((len(events), events.severity, events.latitude), (1, 'critical', 11.05))
        self.url_open('/school/transport/sos?token=%s' % token)                                         # pressed again at once
        self.assertEqual(self.env['school.transport.event'].sudo().search_count([('event_type', '=', 'sos')]), 1)
        self.assertEqual(self.url_open('/school/transport/sos?token=%s&lat=abc' % token).status_code, 400)

    def test_the_existing_gps_endpoint_now_feeds_the_alerts(self):
        self.authenticate('stdriver', 'stdriver')
        self.url_open('/my/driver/live/%s/morning' % self.route.id)
        trip = self._trip()
        self._post('/my/driver/trip-action/%s/start' % trip.id)
        token = self.vehicle.sudo().gps_api_token
        lat, lon = offset_point(*self.points[0], north_m=300)
        response = self.url_open('/school/transport/gps?token=%s&lat=%s&lon=%s&speed=20' % (token, lat, lon))
        self.assertEqual(response.json(), {'ok': True, 'vehicle': 'Van 1'})
        self.assertEqual(len(trip.event_ids.filtered(lambda e: e.event_type == 'approaching')), 1)       # the provider's ping did it

    # ---------------------------------------------------------------- the caretaker works like the driver
    def test_caretaker_runs_a_trip_from_my_trips(self):
        self.authenticate('stcare', 'stcare')
        home = self.url_open('/my')
        self.assertIn('My Trips (Driver / Caretaker)', home.text)                                       # the card says so
        page = self.url_open('/my/driver')
        self.assertIn('/my/driver/live/%s/morning' % self.route.id, page.text)                          # his route, his live trip button
        live = self.url_open('/my/driver/live/%s/morning' % self.route.id)
        for text in ('Start Trip', 'Route A', 'Asha'):
            self.assertIn(text, live.text)
        crew = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', live.text))
        self.assertRegex(crew, r'Driver: %s \S+ Caretaker: %s \S+ You are the caretaker' % (self.driver.name, self.caretaker.name))
        trip = self._trip()
        self._post('/my/driver/trip-action/%s/start' % trip.id)
        self.assertEqual(trip.state, 'running')
        self._post('/my/driver/trip-action/%s/student/%s/board' % (trip.id, self.s1.id))
        record = trip.boarding_ids
        self.assertEqual((record.student_id, record.source, record.confirmed_by), (self.s1, 'caretaker', self.care_user))
        self.assertTrue(self.env['school.transport.notification'].sudo().search([('student_id', '=', self.s1.id), ('kind', '=', 'boarded')]))
        self._post('/my/driver/trip-action/%s/sos' % trip.id, note='Child unwell')
        sos = trip.event_ids.filtered(lambda e: e.event_type == 'sos')
        self.assertIn('caretaker', sos.message)
        self.assertIn('Child unwell', sos.message)
        self._post('/my/driver/trip-action/%s/breakdown' % trip.id, note='Puncture')
        self.assertEqual(trip.breakdown_count, 1)
        self._post('/my/driver/trip-action/%s/student/%s/offboard' % (trip.id, self.s1.id))
        self._post('/my/driver/trip-action/%s/end' % trip.id)
        self.assertEqual(trip.state, 'done')

    def test_driver_and_caretaker_share_one_trip(self):
        self.authenticate('stdriver', 'stdriver')
        self.url_open('/my/driver/live/%s/morning' % self.route.id)
        trip = self._trip()
        self._post('/my/driver/trip-action/%s/start' % trip.id)                                         # the driver starts it
        self._post('/my/driver/trip-action/%s/student/%s/board' % (trip.id, self.s1.id))
        self.authenticate('stcare', 'stcare')
        page = self.url_open('/my/driver/live/%s/morning' % self.route.id)
        self.assertIn('EMERGENCY SOS', page.text)                                                       # the same running trip
        self.assertIn('On board', page.text)
        self._post('/my/driver/trip-action/%s/student/%s/board' % (trip.id, self.s2.id))                 # the caretaker boards the next
        by = {r.student_id: r.source for r in trip.boarding_ids}
        self.assertEqual(by, {self.s1: 'driver', self.s2: 'caretaker'})                                 # who did what is recorded
        self.assertEqual(self.env['school.transport.boarding'].sudo().search([('student_id', '=', self.s2.id)]).confirmed_by, self.care_user)

    def test_a_caretaker_of_another_van_has_no_access(self):
        self.authenticate('stcare2', 'stcare2')
        page = self.url_open('/my/driver')
        self.assertNotIn('/my/driver/live/%s/morning' % self.route.id, page.text)
        live = self.url_open('/my/driver/live/%s/morning' % self.route.id)
        self.assertNotIn('Start Trip', live.text)
        self.assertNotIn('Asha', live.text)
        self.assertFalse(self._trip())
        self.authenticate('stcare', 'stcare')
        self.url_open('/my/driver/live/%s/morning' % self.route.id)
        trip = self._trip()
        self.authenticate('stcare2', 'stcare2')
        self._post('/my/driver/trip-action/%s/start' % trip.id)
        self._post('/my/driver/trip-action/%s/sos' % trip.id)
        self.assertEqual(trip.state, 'planned')
        self.assertFalse(trip.event_ids)

    def test_the_caretaker_of_the_replacement_van_gets_the_access(self):
        new_caretaker = self.env['res.partner'].create({'name': 'New Care', 'is_school_caretaker': True})
        new_user = self.env['res.users'].create({'name': 'stcare3', 'login': 'stcare3', 'password': 'stcare3',
                                                 'partner_id': new_caretaker.id,
                                                 'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])]})
        spare = self.env['school.vehicle'].create({'name': 'Spare Van', 'vehicle_number': 'TN01SP0001',
                                                   'driver_id': self.driver.id, 'caretaker_id': new_caretaker.id})
        self.authenticate('stcare3', 'stcare3')
        self.assertNotIn('/my/driver/live/%s/morning' % self.route.id, self.url_open('/my/driver').text)
        self.route.sudo().write({'replacement_vehicle_id': spare.id, 'is_vehicle_replaced': True})      # the van is replaced
        self.assertEqual(self.route.effective_vehicle_id, spare)
        self.assertIn('/my/driver/live/%s/morning' % self.route.id, self.url_open('/my/driver').text)  # new caretaker: access
        self.authenticate('stcare', 'stcare')
        self.assertNotIn('/my/driver/live/%s/morning' % self.route.id, self.url_open('/my/driver').text)  # old caretaker: none

    def test_the_caretaker_also_reaches_the_existing_attendance_page(self):
        self.authenticate('stcare', 'stcare')
        page = self.url_open('/my/driver/trip/%s/morning' % self.route.id)
        self.assertEqual(page.status_code, 200)
        self.assertIn('Asha', page.text)
        self.authenticate('stcare2', 'stcare2')
        self.assertNotIn('Asha', self.url_open('/my/driver/trip/%s/morning' % self.route.id).text)      # not his van

