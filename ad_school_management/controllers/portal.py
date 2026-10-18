import json
from datetime import datetime, timezone

from odoo import fields, http, _
from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal

from odoo.exceptions import UserError, ValidationError, AccessError


class SchoolCustomerPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super(SchoolCustomerPortal, self)._prepare_home_portal_values(counters)
        partner = request.env.user.partner_id
        
        students = request.env['school.student'].sudo().search([
            '|', ('partner_id', '=', partner.id), ('parent_ids.partner_id', '=', partner.id)
        ])
        

        if 'student_count' in counters:
            students = request.env['school.student'].sudo().search([
                '|', ('partner_id', '=', partner.id), ('parent_ids.partner_id', '=', partner.id)
            ])
            values['student_count'] = len(students)
        if 'driver_route_count' in counters:
            values['driver_route_count'] = len(self._get_driver_routes())
        if 'leave_count' in counters:
            employee = self._school_get_employee()
            values['leave_count'] = request.env['hr.leave'].sudo().search_count(
                self._school_leave_domain(employee)) if employee else 0

        if 'timetable_count' in counters:
            teacher = self._school_get_teacher()
            values['timetable_count'] = teacher.weekly_period_count if teacher else 0
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

        attendances = request.env['school.attendance'].sudo().search(
            [('student_id', '=', student.id), ('session', '=', 'morning')], order='date desc', limit=30)
        # One row per day: Present / Absent (last 15 days).
        attendance_days = request.env['school.attendance']._get_daily_summary(student, days=15)
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

        # Library: books out, reading profile, challenges, "Recommended for you"
        library_loans = request.env['school.book.issue'].sudo().search(
            [('student_id', '=', student.id), ('state', 'in', ('issued', 'overdue'))], order='due_date')
        reading_challenges = request.env['school.reading.challenge.participant'].sudo().search(
            [('student_id', '=', student.id), ('challenge_id.state', '=', 'running')])
        recommendations = student._get_recommended_books(limit=6)

        # Books read (returned) and the student's own reviews. Only the
        # STUDENT may write / edit a review; parents see them read-only.
        returned = request.env['school.book.issue'].sudo().search(
            [('student_id', '=', student.id), ('state', '=', 'returned')], order='return_date desc')
        reviews = request.env['school.book.review'].sudo().with_context(active_test=False).search(
            [('student_id', '=', student.id)])
        review_by_book = {r.book_id.id: r for r in reviews}
        books_read = []
        for issue in returned:
            if issue.book_id.id not in [b['book'].id for b in books_read]:
                books_read.append({'book': issue.book_id, 'returned_on': issue.return_date,
                                   'review': review_by_book.get(issue.book_id.id)})

        # Behaviour & participation reviews (published ones only)
        Behaviour = request.env['school.student.behaviour']
        behaviour_reviews = Behaviour.sudo().search(
            [('student_ids', 'in', student.id), ('portal_published', '=', True)],
            order='date desc, id desc')
        # this student's OWN self-reflection / parent-feedback line for each review
        behaviour_feedback = {f.review_id.id: f for f in request.env['school.student.behaviour.feedback'].sudo().search(
            [('student_id', '=', student.id), ('review_id', 'in', behaviour_reviews.ids)])}
        is_student = student.partner_id == partner
        is_parent = partner in student.parent_ids.partner_id

        values = self._prepare_portal_layout_values()
        values.update({
            'student': student,
            'behaviour_reviews': behaviour_reviews,
            'behaviour_feedback': behaviour_feedback,
            'behaviour_rating_labels': dict(Behaviour._fields['behaviour'].selection),
            'behaviour_period_labels': dict(Behaviour._fields['period'].selection),
            'behaviour_is_student': is_student,
            'behaviour_is_parent': is_parent,
            'behaviour_saved': kw.get('behaviour_saved'),
            'behaviour_error': kw.get('behaviour_error'),
            'attendances': attendances,
            'attendance_days': attendance_days,
            'results': results,
            'timetable': timetable,
            'invoices': invoices,
            'library_loans': library_loans,
            'reading_challenges': reading_challenges,
            'recommendations': recommendations,
            'books_read': books_read,
            'can_review': student.partner_id == partner,
            'active_tab': kw.get('tab') or 'profile',
            'review_saved': kw.get('review_saved'),
            'review_error': kw.get('review_error'),
            'page_name': 'school_student_profile',
        })
        return request.render("ad_school_management.portal_my_student_profile", values)
    
    @http.route(['/my/school/student/<int:student_id>/review'], type='http', auth="user",
                methods=['POST'], website=True)
    def portal_save_book_review(self, student_id, book_id=None, rating=None, review=None, **kw):
        """Save the student's own review. Only the student (not a parent or
        staff) may do this, and only for a book they have returned."""
        partner = request.env.user.partner_id
        student = request.env['school.student'].sudo().browse(student_id)
        if not student.exists() or student.partner_id != partner:
            return request.redirect('/my')
        url = '/my/school/student/%s?tab=library' % student.id
        try:
            book = request.env['school.book'].sudo().browse(int(book_id or 0))
            returned = request.env['school.book.issue'].sudo().search_count(
                [('student_id', '=', student.id), ('book_id', '=', book.id), ('state', '=', 'returned')])
            if not book.exists() or not returned:
                return request.redirect(url + '&review_error=not_returned')
            request.env['school.book.review']._portal_save_review(student, book, rating, review)
        except (ValueError, UserError, ValidationError):
            return request.redirect(url + '&review_error=invalid')
        return request.redirect(url + '&review_saved=1')

    @http.route(['/my/school/student/<int:student_id>/behaviour/<int:review_id>/feedback'],
                type='http', auth="user", methods=['POST'], website=True)
    def portal_save_behaviour_feedback(self, student_id, review_id, kind=None, feedback=None, **kw):
        """The student writes the self-reflection, a parent writes the feedback.
        Nothing else on the review can be changed from the portal."""
        partner = request.env.user.partner_id
        student = request.env['school.student'].sudo().browse(student_id)
        if not student.exists() or (student.partner_id != partner
                                    and partner not in student.parent_ids.partner_id):
            return request.redirect('/my')
        url = '/my/school/student/%s?tab=behaviour' % student.id
        review = request.env['school.student.behaviour'].sudo().browse(review_id)
        if not review.exists() or student not in review.student_ids:
            return request.redirect(url + '&behaviour_error=invalid')
        try:
            request.env['school.student.behaviour']._portal_save_feedback(review, student, partner, kind, feedback)
        except (AccessError, ValidationError, UserError):
            return request.redirect(url + '&behaviour_error=denied')
        return request.redirect(url + '&behaviour_saved=1')

    # ------------------------------------------------------------------
    # My Timetable (teachers)
    # ------------------------------------------------------------------
    def _school_get_teacher(self):
        return request.env['school.teacher'].sudo().search([('user_id', '=', request.env.user.id)], limit=1)

    @http.route(['/my/timetable'], type='http', auth="user", website=True)
    def portal_my_timetable(self, **kw):
        teacher = self._school_get_teacher()
        Teacher = request.env['school.teacher']
        values = self._prepare_portal_layout_values()
        # "Your timetable was updated" alert: shown once, then marked as seen.
        has_update = bool(teacher) and teacher.timetable_has_update
        updated_on = teacher.timetable_updated_on if teacher else False
        if has_update:
            teacher._school_mark_timetable_seen()
        values.update({
            'teacher': teacher,
            'has_update': has_update,
            'updated_on': updated_on,
            'grid': teacher._school_timetable_grid() if teacher else {'rows': [], 'days': [], 'count': 0, 'today': False},
            'today_periods': teacher._school_today_periods() if teacher else [],
            'substitutions': teacher._school_upcoming_substitutions() if teacher else [],
            'fmt': Teacher._school_format_time,
            'page_name': 'school_my_timetable',
        })
        return request.render("ad_school_management.portal_my_timetable", values)



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



class SchoolCustomerPortal(CustomerPortal):

    # ------------------------------------------------------------------
    # Portal home counters
    # ------------------------------------------------------------------
    def _prepare_home_portal_values(self, counters):
        values = super(SchoolCustomerPortal, self)._prepare_home_portal_values(counters)
        partner = request.env.user.partner_id

        if 'student_count' in counters:
            students = request.env['school.student'].sudo().search([
                '|', ('partner_id', '=', partner.id), ('parent_ids.partner_id', '=', partner.id)
            ])
            values['student_count'] = len(students)

        if 'leave_count' in counters:
            employee = self._school_get_employee()
            values['leave_count'] = request.env['hr.leave'].sudo().search_count(
                self._school_leave_domain(employee)) if employee else 0
        return values

    # ------------------------------------------------------------------
    # Students (unchanged)
    # ------------------------------------------------------------------
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

        attendances = request.env['school.attendance'].sudo().search([('student_id', '=', student.id)], order='date desc, session', limit=30)
        # One row per day with Morning and Afternoon side by side (last 15 days).
        attendance_days = request.env['school.attendance']._get_daily_summary(student, days=15)
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
            'attendance_days': attendance_days,
            'results': results,
            'timetable': timetable,
            'invoices': invoices,
            'page_name': 'school_student_profile',
        })
        return request.render("ad_school_management.portal_my_student_profile", values)

    # ------------------------------------------------------------------
    # Leave requests (teachers / staff)
    # ------------------------------------------------------------------
    def _school_get_employee(self):
        return request.env['hr.employee'].sudo().search([('user_id', '=', request.env.user.id)], limit=1)

    def _school_leave_domain(self, employee):
        return [('employee_id', '=', employee.id),
                ('holiday_status_id.school_approval_workflow', '=', True)]

    def _school_leave_types(self, employee):
        return request.env['hr.leave.type'].sudo().search([
            ('school_approval_workflow', '=', True),
            ('company_id', 'in', [False, employee.company_id.id]),
        ], order='sequence, name')

    @http.route(['/my/leaves'], type='http', auth="user", website=True)
    def portal_my_leaves(self, **kw):
        employee = self._school_get_employee()
        leaves = request.env['hr.leave'].sudo().search(
            self._school_leave_domain(employee), order='request_date_from desc, id desc'
        ) if employee else request.env['hr.leave']
        values = self._prepare_portal_layout_values()
        values.update({
            'employee': employee,
            'leaves': leaves,
            'stage_labels': dict(request.env['hr.leave']._fields['school_approval_stage'].selection),
            'submitted': kw.get('submitted'),
            'page_name': 'school_leaves',
        })
        return request.render("ad_school_management.portal_my_leaves", values)

    @http.route(['/my/leaves/new'], type='http', auth="user", methods=['GET', 'POST'], website=True)
    def portal_leave_new(self, **post):
        employee = self._school_get_employee()
        leave_types = self._school_leave_types(employee) if employee else request.env['hr.leave.type']
        error = False

        if request.httprequest.method == 'POST' and employee:
            try:
                leave_id = self._school_create_leave(employee, leave_types, post)
                if leave_id:
                    return request.redirect('/my/leaves?submitted=1')
            except (UserError, ValidationError, AccessError) as e:
                error = e.args[0] if e.args else str(e)
            except ValueError:
                error = _("Please enter valid dates.")

        values = self._prepare_portal_layout_values()
        values.update({
            'employee': employee,
            'leave_types': leave_types,
            'values': post if request.httprequest.method == 'POST' else {},
            'error': error,
            'page_name': 'school_leave_new',
        })
        return request.render("ad_school_management.portal_leave_new", values)

    def _school_create_leave(self, employee, leave_types, post):
        leave_type = leave_types.filtered(lambda lt: str(lt.id) == str(post.get('holiday_status_id')))
        if not leave_type:
            raise UserError(_("Please select a leave type."))

        date_from = fields.Date.to_date(post.get('request_date_from') or None)
        date_to = fields.Date.to_date(post.get('request_date_to') or None) or date_from
        if not date_from:
            raise UserError(_("Please enter the start date."))
        if date_to < date_from:
            raise UserError(_("The end date cannot be before the start date."))

        reason = (post.get('name') or '').strip()
        if not reason:
            raise UserError(_("Please enter the reason for the leave."))

        files = [f for f in request.httprequest.files.getlist('attachments') if f and f.filename]
        if leave_type.school_is_medical and not files:
            raise UserError(_("A medical certificate is required for medical leave. Please attach it."))

        with request.env.cr.savepoint():
            leave = request.env['hr.leave'].sudo().create({
                'employee_id': employee.id,
                'holiday_status_id': leave_type.id,
                'request_date_from': date_from,
                'request_date_to': date_to,
                'name': reason,
            })
            Attachment = request.env['ir.attachment'].sudo()
            for upload in files:
                Attachment.create({
                    'name': upload.filename,
                    'raw': upload.read(),
                    'mimetype': upload.mimetype,
                    'res_model': 'hr.leave',
                    'res_id': leave.id,
                })
        return leave.id
