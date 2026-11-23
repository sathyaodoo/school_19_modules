# -*- coding: utf-8 -*-
from odoo import _, http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal


class SchoolRouteChangePortal(CustomerPortal):
    """Student / parent portal: see transport route change requests, send a new one, withdraw one."""

    def _route_change_student(self, student_id):
        partner = request.env.user.partner_id
        student = request.env['school.student'].sudo().browse(student_id).exists()
        if not student or (student.partner_id != partner and partner not in student.parent_ids.partner_id):
            return None
        return student

    def _route_change_url(self, student, **params):
        url = '/my/school/student/%s/route-change' % student.id
        return url + ('?' + '&'.join('%s=%s' % kv for kv in params.items()) if params else '')

    @http.route('/my/school/student/<int:student_id>/route-change', type='http', auth='user',
                methods=['GET', 'POST'], website=True)
    def portal_route_change(self, student_id, **post):
        student = self._route_change_student(student_id)
        if not student:
            return request.redirect('/my')
        Request = request.env['school.transport.route.change.request'].sudo()
        requests = Request.search([('student_id', '=', student.id)], order='request_date desc, id desc')
        pending = requests.filtered(lambda r: r.state in ('draft', 'submitted'))
        routes = request.env['school.transport.route'].sudo().search(
            [('id', '!=', student.transport_route_id.id)], order='name')
        error = success = False
        if request.httprequest.method == 'POST':
            route_id = int(post.get('requested_route_id') or 0)
            reason = (post.get('reason') or '').strip()
            route = routes.filtered(lambda r: r.id == route_id)
            if not route:
                error = _("Please choose the new route.")
            elif not reason:
                error = _("Please tell the school why the route should change.")
            else:
                if pending:
                    pending.action_withdraw()
                    for old in pending:
                        old.message_post(body=_("Replaced by a newer request from the portal (%s).",
                                                request.env.user.name))
                new = Request.create({'student_id': student.id, 'requested_route_id': route.id, 'reason': reason})
                new.action_submit()
                new.message_post(body=_("Sent from the portal by %s.", request.env.user.name))
                return request.redirect(self._route_change_url(student, sent=1))
        elif post.get('sent'):
            success = _("Your request has been sent to the school.")
        elif post.get('withdrawn'):
            success = _("Your request has been withdrawn.")
        values = self._prepare_portal_layout_values()
        values.update({
            'student': student, 'requests': requests, 'pending': pending, 'routes': routes,
            'error': error, 'success': success, 'post': post,
            'page_name': 'school_route_change',
        })
        return request.render('ad_school_management.portal_route_change', values)

    @http.route('/my/school/student/<int:student_id>/route-change/<int:request_id>/withdraw', type='http',
                auth='user', methods=['POST'], website=True)
    def portal_route_change_withdraw(self, student_id, request_id, **post):
        student = self._route_change_student(student_id)
        if not student:
            return request.redirect('/my')
        req = request.env['school.transport.route.change.request'].sudo().browse(request_id).exists()
        if req and req.student_id == student and req.state in ('draft', 'submitted'):
            req.action_withdraw()
            req.message_post(body=_("Withdrawn from the portal by %s.", request.env.user.name))
        return request.redirect(self._route_change_url(student, withdrawn=1))
