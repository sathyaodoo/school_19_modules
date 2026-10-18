# -*- coding: utf-8 -*-
import hmac

from odoo import _, fields, http
from odoo.http import request
from odoo.addons.ad_school_management.controllers.portal import SchoolCustomerPortal


class SmartTransportPortal(SchoolCustomerPortal):
    """Driver live trip page (start, board / drop, breakdown, SOS, end), the parent's trip page and the
    SOS endpoint of the GPS device. Drivers and parents only see their own route / child."""

    # ------------------------------------------------------------------ driver AND caretaker
    def _get_driver_routes(self):
        """The routes of the logged-in driver and the routes of the vehicle he looks after as caretaker.
        This feeds "My Trips", the attendance pages and the GPS push of the existing module as well."""
        routes = super()._get_driver_routes()
        partner = request.env.user.partner_id
        return routes | request.env['school.transport.route'].sudo().search(
            [('effective_vehicle_id.caretaker_id', '=', partner.id)])

    def _get_driver_route(self, route_id):
        route = super()._get_driver_route(route_id)
        if route:
            return route
        route = request.env['school.transport.route'].sudo().browse(route_id).exists()
        partner = request.env.user.partner_id
        if route and route.effective_vehicle_id.caretaker_id == partner:
            return route
        return None

    def _crew_role(self, route):
        """'driver' or 'caretaker': how the logged-in user belongs to this route (recorded with every confirmation)."""
        return 'driver' if route.effective_driver_id == request.env.user.partner_id else 'caretaker'

    def _live_trip(self, route_id, trip_type):
        route = self._get_driver_route(route_id)
        if not route or trip_type not in ('morning', 'evening'):
            return None
        Trip = request.env['school.transport.trip'].sudo()
        today = fields.Date.context_today(request.env.user)
        trip = Trip.search([('route_id', '=', route.id), ('date', '=', today), ('trip_type', '=', trip_type)], limit=1)
        return trip or Trip.create({'route_id': route.id, 'date': today, 'trip_type': trip_type})

    def _own_trip(self, trip_id):
        trip = request.env['school.transport.trip'].sudo().browse(trip_id).exists()
        if not trip or not self._get_driver_route(trip.route_id.id):
            return None
        return trip

    def _back(self, trip, message=None, error=None):
        url = '/my/driver/live/%s/%s' % (trip.route_id.id, trip.trip_type)
        params = [p for p in (('msg=%s' % message) if message else '', ('err=%s' % error) if error else '') if p]
        return request.redirect(url + ('?' + '&'.join(params) if params else ''))

    @http.route('/my/driver/live/<int:route_id>/<string:trip_type>', type='http', auth='user', website=True)
    def portal_driver_live(self, route_id, trip_type, msg=None, err=None, **kw):
        trip = self._live_trip(route_id, trip_type)
        if not trip:
            return request.redirect('/my/driver')
        lines = {l.stop_id.id: l for l in trip.stop_line_ids}
        stops = [{'stop': stop, 'line': lines.get(stop.id), 'students': trip._students_at_stop(stop)}
                 for stop in trip.route_id.stop_ids.sorted('sequence')]
        on_board = trip._on_board_students()
        boarded = trip.boarding_ids.filtered(lambda b: b.event_type == 'board').mapped('student_id')
        no_stop = trip.route_id.student_ids.filtered(lambda s: not s.van_boarding_point_id)
        values = self._prepare_portal_layout_values()
        values.update({'trip': trip, 'route': trip.route_id, 'vehicle': trip.vehicle_id, 'stops': stops,
                       'on_board': on_board, 'boarded': boarded, 'no_stop': no_stop, 'msg': msg, 'err': err,
                       'role': self._crew_role(trip.route_id), 'driver': trip.route_id.effective_driver_id,
                       'caretaker': trip.route_id.effective_vehicle_id.caretaker_id,
                       'page_name': 'smart_driver_live'})
        return request.render('school_smart_transport.portal_driver_live', values)

    @http.route('/my/driver/trip-action/<int:trip_id>/<string:action>', type='http', auth='user', methods=['POST'], website=True)
    def portal_driver_live_action(self, trip_id, action, **post):
        trip = self._own_trip(trip_id)
        if not trip or action not in ('start', 'end', 'sos', 'breakdown'):
            return request.redirect('/my/driver')
        try:
            if action == 'start':
                trip.action_start()
                return self._back(trip, message='started')
            if action == 'end':
                if trip._on_board_students() and not post.get('confirm'):
                    return self._back(trip, error='students_on_board')
                trip.action_end()
                return self._back(trip, message='ended')
            if action == 'sos':
                trip._raise_sos(source=self._crew_role(trip.route_id), note=(post.get('note') or '')[:200] or None)
                return self._back(trip, message='sos_sent')
            trip.action_breakdown(note=(post.get('note') or '')[:200] or None, source=self._crew_role(trip.route_id))
            return self._back(trip, message='breakdown_sent')
        except Exception as error:                                   # a clear message instead of an error page
            return self._back(trip, error=str(getattr(error, 'args', [''])[0])[:120].replace(' ', '_'))

    @http.route('/my/driver/trip-action/<int:trip_id>/student/<int:student_id>/<string:action>', type='http', auth='user',
                methods=['POST'], website=True)
    def portal_driver_live_student(self, trip_id, student_id, action, **post):
        trip = self._own_trip(trip_id)
        student = request.env['school.student'].sudo().browse(student_id).exists()
        if not trip or not student or action not in ('board', 'offboard'):
            return request.redirect('/my/driver')
        try:
            role = self._crew_role(trip.route_id)
            if action == 'board':
                trip.action_board_student(student, source=role)
            else:
                trip.action_offboard_student(student, source=role)
        except Exception as error:
            return self._back(trip, error=str(getattr(error, 'args', [''])[0])[:120].replace(' ', '_'))
        return self._back(trip, message='%s_%s' % (action, student.id))

    # ------------------------------------------------------------------ parent
    @http.route('/my/school/student/<int:student_id>/transport', type='http', auth='user', website=True)
    def portal_student_transport(self, student_id, **kw):
        partner = request.env.user.partner_id
        student = request.env['school.student'].sudo().browse(student_id)
        if not student.exists() or (student.partner_id.id != partner.id and partner.id not in student.parent_ids.partner_id.ids):
            return request.redirect('/my')
        today = fields.Date.context_today(request.env.user)
        trips = request.env['school.transport.trip'].sudo().search(
            [('route_id', '=', student.transport_route_id.id), ('date', '=', today)], order='trip_type')
        rows = []
        for trip in trips:
            records = trip.boarding_ids.filtered(lambda b: b.student_id == student)
            line = trip.stop_line_ids.filtered(lambda l: l.stop_id == student.van_boarding_point_id)[:1]
            minutes = None
            if trip.state == 'running' and line and not line.arrived_at and line.eta:
                minutes = max(0, int((line.eta - fields.Datetime.now()).total_seconds() // 60))
            rows.append({'trip': trip, 'board': records.filtered(lambda b: b.event_type == 'board')[:1],
                         'offboard': records.filtered(lambda b: b.event_type == 'offboard')[:1],
                         'line': line, 'minutes': minutes})
        notices = request.env['school.transport.notification'].sudo().search([('student_id', '=', student.id)], limit=20)
        # one row per message, not one per parent
        seen, unique = set(), []
        for note in notices:
            key = (note.kind, note.message, note.sent_at)
            if key not in seen:
                seen.add(key)
                unique.append(note)
        values = self._prepare_portal_layout_values()
        values.update({'student': student, 'rows': rows, 'notices': unique, 'page_name': 'smart_student_transport'})
        return request.render('school_smart_transport.portal_student_transport', values)

    # ------------------------------------------------------------------ GPS device panic button
    @http.route('/school/transport/sos', type='http', auth='public', methods=['GET', 'POST'], csrf=False)
    def device_sos(self, **kw):
        token = kw.get('token') or ''
        vehicle = request.env['school.vehicle'].sudo().search([('gps_api_token', '=', token)], limit=1) if token else None
        if not vehicle or not hmac.compare_digest(vehicle.gps_api_token or '', token):
            return self._json({'ok': False, 'error': 'invalid_token'}, 401)
        try:
            lat = float(kw['lat']) if kw.get('lat') else None
            lon = float(kw['lon']) if kw.get('lon') else None
        except ValueError:
            return self._json({'ok': False, 'error': 'invalid_coordinates'}, 400)
        vehicle._raise_sos(source='GPS device', lat=lat, lon=lon)
        return self._json({'ok': True})
