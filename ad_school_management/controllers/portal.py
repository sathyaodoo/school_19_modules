import json
from datetime import datetime, timezone

from odoo import fields, http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal

class SchoolCustomerPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super(SchoolCustomerPortal, self)._prepare_home_portal_values(counters)
        partner = request.env.user.partner_id
        
        students = request.env['school.student'].sudo().search([
            '|', ('partner_id', '=', partner.id), ('parent_ids.partner_id', '=', partner.id)
        ])
        
        if 'student_count' in counters:
            values['student_count'] = len(students)
        if 'driver_route_count' in counters:
            values['driver_route_count'] = len(self._get_driver_routes())
        return values

    @http.route(['/my/school/students'], type='http', auth="user", website=True)
    def portal_my_students(self, **kw):
        partner = request.env.user.partner_id
        students = request.env['school.student'].sudo().search([
            '|', ('partner_id', '=', partner.id), ('parent_ids.partner_id', '=', partner.id)
        ])
        values = self._prepare_portal_layout_values()
        values.update({
            'students': students,
            'page_name': 'school_students',
        })
        return request.render("ad_school_management.portal_my_students", values)

    @http.route(['/my/school/student/<int:student_id>'], type='http', auth="user", website=True)
    def portal_my_student_profile(self, student_id, **kw):
        partner = request.env.user.partner_id
        student = request.env['school.student'].sudo().browse(student_id)
        
        if not student.exists() or (student.partner_id.id != partner.id and partner.id not in student.parent_ids.partner_id.ids):
            return request.redirect('/my')

        attendances = request.env['school.attendance'].sudo().search([('student_id', '=', student.id)], order='date desc', limit=15)
        results = request.env['school.exam.result'].sudo().search([('student_id', '=', student.id)])
        
        timetable = request.env['school.timetable'].sudo().search([
            ('class_id', '=', student.class_id.id),
            ('section_id', '=', student.section_id.id),
            ('academic_year_id', '=', student.academic_year_id.id)
        ], limit=1)
        
        invoices = request.env['account.move'].sudo().search([
            ('partner_id', '=', student.partner_id.id),
            ('move_type', '=', 'out_invoice')
        ])

        values = self._prepare_portal_layout_values()
        values.update({
            'student': student,
            'attendances': attendances,
            'results': results,
            'timetable': timetable,
            'invoices': invoices,
            'page_name': 'school_student_profile',
        })
        return request.render("ad_school_management.portal_my_student_profile", values)


    # ------------------------------------------------------------------
    # 1. Location ingestion (GPS device / provider / driver phone)
    # ------------------------------------------------------------------
    @http.route('/school/transport/gps', type='http', auth='public', methods=['GET', 'POST'], csrf=False)
    def gps_ping(self, **kw):
        """Provider-independent endpoint.

        Accepts query/form params or a JSON body:
            token     (required) vehicle GPS API token
            lat, lon  (required) also accepts latitude/longitude/lng
            speed     optional, km/h
            timestamp optional, unix seconds (UTC)
            source    optional: device / driver_app
        Example (Traccar-style forward URL):
            /school/transport/gps?token=XXX&lat={latitude}&lon={longitude}&speed={speed}&timestamp={fixTime}
        """
        data = dict(kw)
        if request.httprequest.content_type and 'json' in request.httprequest.content_type:
            try:
                data.update(json.loads(request.httprequest.get_data(as_text=True) or '{}'))
            except ValueError:
                return self._json({'ok': False, 'error': 'invalid_json'}, 400)

        token = data.get('token')
        if not token:
            return self._json({'ok': False, 'error': 'missing_token'}, 401)
        vehicle = request.env['school.vehicle'].sudo().search([('gps_api_token', '=', token)], limit=1)
        if not vehicle:
            return self._json({'ok': False, 'error': 'invalid_token'}, 401)

        try:
            lat = float(data.get('lat', data.get('latitude')))
            lon = float(data.get('lon', data.get('lng', data.get('longitude'))))
            speed = float(data.get('speed') or 0.0)
        except (TypeError, ValueError):
            return self._json({'ok': False, 'error': 'invalid_coordinates'}, 400)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return self._json({'ok': False, 'error': 'out_of_range'}, 400)

        recorded_at = None
        if data.get('timestamp'):
            try:
                ts = float(data['timestamp'])
                if ts > 1e12:  # milliseconds
                    ts /= 1000.0
                recorded_at = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
            except (TypeError, ValueError):
                recorded_at = None

        source = data.get('source') if data.get('source') in ('device', 'driver_app') else 'device'
        vehicle._register_location(lat, lon, speed=speed, recorded_at=recorded_at, source=source)
        return self._json({'ok': True, 'vehicle': vehicle.name})

    def _json(self, payload, status=200):
        return request.make_response(
            json.dumps(payload),
            headers=[('Content-Type', 'application/json')],
            status=status,
        )

    # ------------------------------------------------------------------
    # 2. Parent portal: live bus location for their own child only
    # ------------------------------------------------------------------
    @http.route('/my/school/student/<int:student_id>/bus', type='http', auth='user', website=True)
    def portal_student_bus(self, student_id, **kw):
        partner = request.env.user.partner_id
        student = request.env['school.student'].sudo().browse(student_id)
        if not student.exists() or (
                student.partner_id.id != partner.id and partner.id not in student.parent_ids.partner_id.ids):
            return request.redirect('/my')

        route = student.transport_route_id
        vehicle = student.vehicle_id  # follows the replacement vehicle automatically
        minutes_ago = None
        if vehicle.last_location_at:
            delta = fields.Datetime.now() - vehicle.last_location_at
            minutes_ago = int(delta.total_seconds() // 60)

        embed_url = False
        if vehicle.last_location_at:
            lat, lon = vehicle.last_latitude, vehicle.last_longitude
            pad = 0.01
            embed_url = (
                "https://www.openstreetmap.org/export/embed.html?bbox=%s,%s,%s,%s&layer=mapnik&marker=%s,%s"
                % (lon - pad, lat - pad, lon + pad, lat + pad, lat, lon))

        values = self._prepare_portal_layout_values()
        values.update({
            'student': student,
            'route': route,
            'vehicle': vehicle,
            'driver': route.effective_driver_id,
            'minutes_ago': minutes_ago,
            'embed_url': embed_url,
            'page_name': 'school_student_bus',
        })
        return request.render('ad_school_management.portal_student_bus', values)

    # ------------------------------------------------------------------
    # 3. Driver portal: own trips, mobile attendance, phone GPS
    # ------------------------------------------------------------------
    def _get_driver_routes(self):
        """Routes the logged-in user is currently driving (handles leave / replacement)."""
        partner = request.env.user.partner_id
        return request.env['school.transport.route'].sudo().search(
            [('effective_driver_id', '=', partner.id)])

    def _get_driver_route(self, route_id):
        route = request.env['school.transport.route'].sudo().browse(route_id)
        if not route.exists() or route.effective_driver_id != request.env.user.partner_id:
            return None
        return route

    @http.route('/my/driver', type='http', auth='user', website=True)
    def portal_driver_home(self, **kw):
        routes = self._get_driver_routes()
        today = fields.Date.context_today(request.env.user)
        attendances = request.env['school.transport.attendance'].sudo().search([
            ('route_id', 'in', routes.ids), ('date', '=', today)])
        done = {(a.route_id.id, a.trip_type): a for a in attendances}
        values = self._prepare_portal_layout_values()
        values.update({
            'routes': routes,
            'today': today,
            'done': done,
            'page_name': 'school_driver',
        })
        return request.render('ad_school_management.portal_driver_home', values)

    @http.route('/my/driver/trip/<int:route_id>/<string:trip_type>', type='http', auth='user', website=True)
    def portal_driver_trip(self, route_id, trip_type, **kw):
        route = self._get_driver_route(route_id)
        if not route or trip_type not in ('morning', 'evening'):
            return request.redirect('/my/driver')
        Attendance = request.env['school.transport.attendance'].sudo()
        today = fields.Date.context_today(request.env.user)
        attendance = Attendance.search([
            ('route_id', '=', route.id), ('date', '=', today), ('trip_type', '=', trip_type)], limit=1)
        if not attendance:
            attendance = Attendance.create({
                'route_id': route.id,
                'date': today,
                'trip_type': trip_type,
                'marked_source': 'driver_portal',
            })
        # add any student assigned to the route after the record was created
        attendance.action_fetch_students()
        values = self._prepare_portal_layout_values()
        values.update({
            'route': route,
            'attendance': attendance,
            'vehicle': route.effective_vehicle_id,
            'saved': kw.get('saved'),
            'page_name': 'school_driver_trip',
        })
        return request.render('ad_school_management.portal_driver_trip', values)

    @http.route('/my/driver/attendance/<int:attendance_id>/save', type='http', auth='user',
                methods=['POST'], website=True)
    def portal_driver_attendance_save(self, attendance_id, **post):
        attendance = request.env['school.transport.attendance'].sudo().browse(attendance_id)
        if not attendance.exists() or not self._get_driver_route(attendance.route_id.id):
            return request.redirect('/my/driver')
        for line in attendance.line_ids:
            status = post.get('status_%s' % line.id)
            if status in ('boarded', 'absent') and status != line.status:
                line.status = status
        attendance.write({
            'marked_by_id': request.env.user.id,
            'marked_source': 'driver_portal',
        })
        return request.redirect('/my/driver/trip/%s/%s?saved=1' % (attendance.route_id.id, attendance.trip_type))

    @http.route('/my/driver/location', type='http', auth='user', methods=['POST'], website=True)
    def portal_driver_location(self, **post):
        route = self._get_driver_route(int(post.get('route_id') or 0))
        if not route or not route.effective_vehicle_id:
            return self._json({'ok': False, 'error': 'not_your_route'}, 403)
        try:
            lat = float(post.get('lat'))
            lon = float(post.get('lon'))
            speed = float(post.get('speed') or 0.0)
        except (TypeError, ValueError):
            return self._json({'ok': False, 'error': 'invalid_coordinates'}, 400)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return self._json({'ok': False, 'error': 'out_of_range'}, 400)
        route.effective_vehicle_id._register_location(lat, lon, speed=speed, source='driver_app')
        return self._json({'ok': True, 'vehicle': route.effective_vehicle_id.name})