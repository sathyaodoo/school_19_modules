from odoo import models, fields, api, _, Command
import logging
import re
import secrets

import requests
from datetime import timedelta
from markupsafe import Markup
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)

class SchoolVehicle(models.Model):
    _name = 'school.vehicle'
    _description = 'School Vehicle'

    name = fields.Char(string='Vehicle Name', required=True)
    vehicle_number = fields.Char(string='Vehicle Number', required=True)
    capacity = fields.Integer(string='Passenger Capacity', default=40, required=True)
    driver_id = fields.Many2one('res.partner', string='Driver', domain="[('is_school_driver', '=', True)]")
    caretaker_id = fields.Many2one('res.partner', string='Caretaker', domain="[('is_school_caretaker', '=', True)]")
    gps_tracking_url = fields.Char(
        string='GPS Tracking Link',
        help="Live tracking link from the GPS provider. Shared with parents in transport notifications.")
    # --- Built-in GPS tracking (provider independent) ---
    gps_device_id = fields.Char(string='GPS Device ID', help="IMEI / device ID given by the GPS provider.")
    gps_api_token = fields.Char(string='GPS API Token', copy=False, readonly=True, groups='ad_school_management.group_school_admin',
                                help="Secret token the GPS device/provider uses to send locations to Odoo.")
    last_latitude = fields.Float(string='Last Latitude', digits=(10, 7), readonly=True)
    last_longitude = fields.Float(string='Last Longitude', digits=(10, 7), readonly=True)
    last_speed = fields.Float(string='Last Speed (km/h)', readonly=True)
    last_location_at = fields.Datetime(string='Last Location Time', readonly=True)
    location_map_url = fields.Char(string='Map', compute='_compute_location_map_url')
    location_ids = fields.One2many('school.vehicle.location', 'vehicle_id', string='Location History')
    route_ids = fields.One2many('school.transport.route', 'vehicle_id', string='Routes')
    student_ids = fields.One2many('school.student', 'vehicle_id', string='Students', readonly=True)
    student_count = fields.Integer(string='Students', compute='_compute_student_count')
    is_over_capacity = fields.Boolean(compute='_compute_student_count')

    _number_uniq = models.Constraint(
        'unique(vehicle_number)', 'Vehicle number must be unique!'
    )

    @api.depends('last_latitude', 'last_longitude', 'last_location_at')
    def _compute_location_map_url(self):
        for rec in self:
            if rec.last_location_at:
                rec.location_map_url = "https://www.openstreetmap.org/?mlat=%s&mlon=%s#map=16/%s/%s" % (
                    rec.last_latitude, rec.last_longitude, rec.last_latitude, rec.last_longitude)
            else:
                rec.location_map_url = False

    def action_generate_gps_token(self):
        for rec in self:
            rec.sudo().gps_api_token = secrets.token_urlsafe(24)

    def _register_location(self, latitude, longitude, speed=0.0, recorded_at=None, source='device'):
        """Store a GPS ping and update the vehicle's last known position."""
        self.ensure_one()
        recorded_at = recorded_at or fields.Datetime.now()
        self.env['school.vehicle.location'].sudo().create({
            'vehicle_id': self.id,
            'latitude': latitude,
            'longitude': longitude,
            'speed': speed,
            'recorded_at': recorded_at,
            'source': source,
        })
        if not self.last_location_at or recorded_at >= self.last_location_at:
            self.sudo().write({
                'last_latitude': latitude,
                'last_longitude': longitude,
                'last_speed': speed,
                'last_location_at': recorded_at,
            })

    @api.depends('student_ids', 'capacity')
    def _compute_student_count(self):
        for rec in self:
            rec.student_count = len(rec.student_ids)
            rec.is_over_capacity = rec.student_count > rec.capacity

    @api.constrains('capacity')
    def _check_capacity(self):
        for rec in self:
            if rec.capacity <= 0:
                raise ValidationError(_("Vehicle capacity must be greater than zero."))

    def write(self, vals):
        # Permanent driver / caretaker change on the vehicle form -> notify parents of the
        # routes whose CURRENT (effective) driver or caretaker actually changes.
        watch = 'driver_id' in vals or 'caretaker_id' in vals
        routes = self.env['school.transport.route']
        before = {}
        if watch:
            routes = routes.search(['|', ('vehicle_id', 'in', self.ids), ('effective_vehicle_id', 'in', self.ids)])
            before = {r.id: (r.effective_driver_id, r.effective_vehicle_id.caretaker_id) for r in routes}
        res = super().write(vals)
        if watch and routes:
            driver_routes = routes.filtered(lambda r: r.effective_driver_id != before[r.id][0])
            caretaker_routes = (routes - driver_routes).filtered(
                lambda r: r.effective_vehicle_id.caretaker_id != before[r.id][1])
            if driver_routes:
                driver_routes._notify_parents_transport_change('driver')
            if caretaker_routes:
                caretaker_routes._notify_parents_transport_change('caretaker')
        return res

class SchoolVehicleLocation(models.Model):
    _name = 'school.vehicle.location'
    _description = 'Vehicle GPS Location'
    _order = 'recorded_at desc'

    vehicle_id = fields.Many2one('school.vehicle', string='Vehicle', required=True, ondelete='cascade', index=True)
    latitude = fields.Float(string='Latitude', digits=(10, 7), required=True)
    longitude = fields.Float(string='Longitude', digits=(10, 7), required=True)
    speed = fields.Float(string='Speed (km/h)')
    recorded_at = fields.Datetime(string='Recorded At', required=True, default=fields.Datetime.now, index=True)
    source = fields.Selection([
        ('device', 'GPS Device / Provider'),
        ('driver_app', 'Driver Phone'),
        ('manual', 'Manual'),
    ], string='Source', default='device')

    @api.model
    def _cron_purge_old_locations(self, days=30):
        limit = fields.Datetime.now() - timedelta(days=days)
        self.search([('recorded_at', '<', limit)]).unlink()

class SchoolTransportRoute(models.Model):
    _name = 'school.transport.route'
    _description = 'Transport Route'
    _inherit = ['mail.thread']

    name = fields.Char(string='Route Name', required=True)
    vehicle_id = fields.Many2one('school.vehicle', string='Assigned Vehicle')
    driver_id = fields.Many2one('res.partner', related='vehicle_id.driver_id', store=True, readonly=True)
    cost = fields.Float(string='Monthly Cost')
    billing_month = fields.Date(
        string='Billing Month', default=lambda self: fields.Date.context_today(self).replace(day=1),
        help="Month used by 'Generate Bills'. Any day of the month can be picked; the bill is dated the 1st.")
    stop_ids = fields.One2many('school.transport.stop', 'route_id', string='Route Stops')
    product_id = fields.Many2one('product.product', string='Transport Fee Product',
                                  help="Product used when invoicing students on this route.")
    student_ids = fields.One2many('school.student', 'transport_route_id', string='Assigned Students')
    transport_fee_ids = fields.One2many('school.student.transport.fee', 'route_id', string='Generated Bills')
    caretaker_id = fields.Many2one('res.partner', string='Caretaker', related='vehicle_id.caretaker_id', readonly=True)
    backup_driver_id = fields.Many2one('res.partner', string='Backup Driver', domain="[('is_school_driver', '=', True)]",
                                        help="Substitute driver to use when the assigned driver is on leave.")
    is_driver_on_leave = fields.Boolean(string='Driver on Leave', tracking=True)
    effective_driver_id = fields.Many2one('res.partner', string='Current Active Driver',
                                           compute='_compute_effective_driver', store=True, tracking=True)

    # Vehicle replacement (breakdown / maintenance)
    is_vehicle_replaced = fields.Boolean(string='Vehicle Replaced', readonly=True, tracking=True)
    replacement_vehicle_id = fields.Many2one('school.vehicle', string='Replacement Vehicle', tracking=True)
    replacement_driver_id = fields.Many2one(
        'res.partner', string='Replacement Driver', tracking=True, domain="[('is_school_driver', '=', True)]",
        help="Driver of the replacement vehicle. Leave empty if the regular driver drives the replacement vehicle.")
    replacement_reason = fields.Selection([
        ('breakdown', 'Breakdown'),
        ('maintenance', 'Maintenance / Service'),
        ('other', 'Other'),
    ], string='Replacement Reason', tracking=True)
    replacement_note = fields.Char(string='Replacement Note')
    effective_vehicle_id = fields.Many2one('school.vehicle', string='Current Vehicle',
                                            compute='_compute_effective_vehicle', store=True, tracking=True)

    @api.depends('vehicle_id', 'is_vehicle_replaced', 'replacement_vehicle_id')
    def _compute_effective_vehicle(self):
        for route in self:
            if route.is_vehicle_replaced and route.replacement_vehicle_id:
                route.effective_vehicle_id = route.replacement_vehicle_id
            else:
                route.effective_vehicle_id = route.vehicle_id

    @api.depends('driver_id', 'backup_driver_id', 'is_driver_on_leave',
                 'is_vehicle_replaced', 'replacement_driver_id')
    def _compute_effective_driver(self):
        for route in self:
            if route.is_vehicle_replaced and route.replacement_driver_id:
                route.effective_driver_id = route.replacement_driver_id
            elif route.is_driver_on_leave and route.backup_driver_id:
                route.effective_driver_id = route.backup_driver_id
            else:
                route.effective_driver_id = route.driver_id

    @api.onchange('replacement_vehicle_id')
    def _onchange_replacement_vehicle_id(self):
        if self.replacement_vehicle_id.driver_id:
            self.replacement_driver_id = self.replacement_vehicle_id.driver_id

    def write(self, vals):
        res = super().write(vals)
        if 'cost' in vals or 'billing_month' in vals:
            today = fields.Date.context_today(self)
            for route in self:
                month = (route.billing_month or today).replace(day=1)
                drafts = route.transport_fee_ids.filtered(
                    lambda f: not f.invoice_id and f.billing_month == month and f.amount != route.cost)
                if drafts and route.cost > 0:
                    drafts.write({'amount': route.cost})
                    route.message_post(body=_(
                        "%(count)s draft bill(s) for %(month)s updated to %(amount)s.",
                        count=len(drafts), month=month.strftime('%B %Y'), amount=route.cost))
        return res

    @api.constrains('cost')
    def _check_cost(self):
        for route in self:
            if route.cost < 0:
                raise ValidationError(_("Route monthly cost cannot be negative."))

    def _get_same_driver_routes(self):
        """All routes driven by the same regular driver as the given routes."""
        drivers = self.mapped('driver_id')
        if not drivers:
            return self
        return self | self.search([('driver_id', 'in', drivers.ids)])

    def action_mark_driver_on_leave(self):
        for route in self:
            if not route.driver_id:
                raise ValidationError(_("Route %s has no driver assigned.") % route.name)
            if not route.backup_driver_id:
                raise ValidationError(_("Please set a Backup Driver before marking the driver on leave."))
        # A driver on leave is absent for every route he drives, not just this one.
        routes = self._get_same_driver_routes().filtered(lambda r: not r.is_driver_on_leave)
        for route in routes:
            # Routes without their own backup driver use the backup chosen on this route.
            if not route.backup_driver_id:
                source = self.filtered(lambda r: r.driver_id == route.driver_id)[:1]
                route.backup_driver_id = source.backup_driver_id
            route.is_driver_on_leave = True
        routes._notify_parents_driver_change()

    def action_driver_back_from_leave(self):
        routes = self._get_same_driver_routes().filtered('is_driver_on_leave')
        routes.write({'is_driver_on_leave': False})
        routes._notify_parents_driver_change()

    def _get_same_vehicle_routes(self):
        """All routes that use the same regular vehicle as the given routes."""
        vehicles = self.mapped('vehicle_id')
        if not vehicles:
            return self
        return self | self.search([('vehicle_id', 'in', vehicles.ids)])

    def action_replace_vehicle(self):
        for route in self:
            if not route.vehicle_id:
                raise ValidationError(_("Route %s has no assigned vehicle.") % route.name)
            if not route.replacement_vehicle_id:
                raise ValidationError(_("Please select a Replacement Vehicle first."))
            if route.replacement_vehicle_id == route.vehicle_id:
                raise ValidationError(_("Replacement Vehicle must be different from the assigned vehicle."))
            if not route.replacement_reason:
                raise ValidationError(_("Please select a Replacement Reason."))
        # A broken-down vehicle is unavailable for every route it serves, not just this one.
        routes = self._get_same_vehicle_routes().filtered(lambda r: not r.is_vehicle_replaced)
        for route in routes:
            source = self.filtered(lambda r: r.vehicle_id == route.vehicle_id)[:1]
            if route not in self:
                route.write({
                    'replacement_vehicle_id': source.replacement_vehicle_id.id,
                    'replacement_driver_id': source.replacement_driver_id.id,
                    'replacement_reason': source.replacement_reason,
                    'replacement_note': source.replacement_note,
                })
            if len(route.student_ids) > route.replacement_vehicle_id.capacity:
                raise ValidationError(_(
                    "Replacement vehicle %(vehicle)s has capacity %(capacity)s, but route %(route)s "
                    "has %(count)s students.",
                    vehicle=route.replacement_vehicle_id.name,
                    capacity=route.replacement_vehicle_id.capacity,
                    route=route.name, count=len(route.student_ids)))
        routes.write({'is_vehicle_replaced': True})
        routes._notify_parents_transport_change('vehicle')

    def action_restore_vehicle(self):
        routes = self._get_same_vehicle_routes().filtered('is_vehicle_replaced')
        routes.write({
            'is_vehicle_replaced': False,
            'replacement_vehicle_id': False,
            'replacement_driver_id': False,
            'replacement_reason': False,
            'replacement_note': False,
        })
        routes._notify_parents_transport_change('vehicle_restored')

    def _notify_parents_driver_change(self):
        self._notify_parents_transport_change('driver')

    def _notify_parents_transport_change(self, change_type):
        intro = {
            'driver': _("the driver for transport route <b>%s</b> has been updated."),
            'vehicle': _("the vehicle for transport route <b>%s</b> has been temporarily replaced."),
            'vehicle_restored': _("the regular vehicle for transport route <b>%s</b> is back in service."),
            'caretaker': _("the caretaker for transport route <b>%s</b> has been updated."),
        }[change_type]
        subject = {
            'driver': _('Transport Driver Update - %s'),
            'vehicle': _('Transport Vehicle Change - %s'),
            'vehicle_restored': _('Regular Vehicle Restored - %s'),
            'caretaker': _('Transport Caretaker Update - %s'),
        }[change_type]
        reasons = dict(self._fields['replacement_reason'].selection)
        for route in self:
            parents = route.student_ids.mapped('parent_ids')
            emails = [e for e in parents.mapped('email') if e]
            if not parents:
                continue
            vehicle = route.effective_vehicle_id
            driver = route.effective_driver_id
            lines = [
                _("<b>Vehicle:</b> %s (%s)") % (vehicle.name or '-', vehicle.vehicle_number or '-'),
                _("<b>Driver:</b> %s") % (driver.name or _('Not assigned')),
                _("<b>Driver Contact:</b> %s") % (driver.phone or _('Not available')),
            ]
            caretaker = vehicle.caretaker_id
            if caretaker:
                lines += [
                    _("<b>Caretaker:</b> %s") % caretaker.name,
                    _("<b>Caretaker Contact:</b> %s") % (caretaker.phone or _('Not available')),
                ]
            if change_type == 'vehicle' and route.replacement_reason:
                reason = reasons.get(route.replacement_reason)
                if route.replacement_note:
                    reason = "%s - %s" % (reason, route.replacement_note)
                lines.append(_("<b>Reason:</b> %s") % reason)
            if vehicle.last_location_at:
                lines.append(_("<b>Live Location:</b> Parent Portal → My Account → Student → Bus Location"))
            if vehicle.gps_tracking_url:
                lines.append(_('<b>Live Tracking:</b> <a href="%s">%s</a>') % (
                    vehicle.gps_tracking_url, vehicle.gps_tracking_url))
            body = (
                "<p>%s</p><p>%s</p><p>%s</p><p>%s</p>" % (
                    _("Dear Parent,"),
                    _("Please be informed that ") + intro % route.name,
                    "<br/>".join(lines),
                    _("Thank you,<br/>School Administration"),
                )
            )
            if emails:
                self.env['mail.mail'].create({
                    'subject': subject % route.name,
                    'body_html': body,
                    'email_to': ','.join(emails),
                }).send()
            route.message_post(body=Markup(body), subject=subject % route.name)
            route._send_transport_whatsapp(change_type, parents)

    def _send_transport_whatsapp(self, change_type, parents):
        """WhatsApp copy of the transport notification (one approved utility template, 5 variables)."""
        self.ensure_one()
        account = self.env['school.whatsapp.account']._get_account()
        if not account:
            return
        titles = {
            'driver': _('Driver updated'),
            'vehicle': _('Vehicle temporarily replaced'),
            'vehicle_restored': _('Regular vehicle back in service'),
            'caretaker': _('Caretaker updated'),
        }
        vehicle = self.effective_vehicle_id
        driver = self.effective_driver_id
        caretaker = vehicle.caretaker_id
        params = [
            titles[change_type],
            self.name or '-',
            '%s (%s)' % (vehicle.name or '-', vehicle.vehicle_number or '-'),
            '%s (%s)' % (driver.name or '-', driver.phone or '-'),
            '%s (%s)' % (caretaker.name, caretaker.phone or '-') if caretaker else '-',
        ]
        for partner in parents.mapped('partner_id'):
            account._send_template(partner.phone, account.transport_template, params,
                                   partner=partner, record=self)

    def action_generate_monthly_fees(self):
        today = fields.Date.context_today(self)
        created = self.env['school.student.transport.fee']
        for route in self:
            month_start = (route.billing_month or today).replace(day=1)
            if route.cost <= 0:
                raise ValidationError(_(
                    "Monthly Cost is not set for route %s. Please set it before generating bills."
                ) % route.name)
            for student in route.student_ids:
                existing = self.env['school.student.transport.fee'].search([
                    ('student_id', '=', student.id),
                    ('billing_month', '=', month_start),
                ])
                if not existing:
                    created += self.env['school.student.transport.fee'].create({
                        'student_id': student.id,
                        'route_id': route.id,
                        'billing_month': month_start,
                        'amount': route.cost,
                    })
        if not created:
            raise ValidationError(_(
                "No new transport bills to generate — all students are already billed for %s. "
                "Change the Billing Month on the route to bill another month.")
                % ', '.join(sorted({(r.billing_month or today).strftime('%B %Y') for r in self})))
        return {
            'name': _('Generated Transport Bills'),
            'type': 'ir.actions.act_window',
            'res_model': 'school.student.transport.fee',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created.ids)],
        }

class SchoolTransportStop(models.Model):
    _name = 'school.transport.stop'
    _description = 'Transport Route Stop'
    _order = 'sequence'

    route_id = fields.Many2one('school.transport.route', string='Route', required=True, ondelete='cascade')
    name = fields.Char(string='Stop Name', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    time = fields.Float(string='Expected Time (Hour)', help="Use 8.5 for 08:30 AM")

class SchoolStudentTransportFee(models.Model):
    _name = 'school.student.transport.fee'
    _description = 'Student Transport Fee'
    _order = 'billing_month desc'

    student_id = fields.Many2one('school.student', string='Student', required=True, ondelete='cascade')
    route_id = fields.Many2one('school.transport.route', string='Route', required=True)
    billing_month = fields.Date(string='Billing Month', required=True)
    amount = fields.Float(string='Amount', required=True)
    invoice_id = fields.Many2one('account.move', string='Invoice', readonly=True, copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('invoiced', 'Invoiced'),
        ('paid', 'Paid'),
    ], string='Status', compute='_compute_state', store=True, default='draft')

    _student_month_uniq = models.Constraint(
        'unique(student_id, billing_month)',
        'Transport fee already generated for this student for this month!'
    )

    @api.depends('invoice_id', 'invoice_id.payment_state')
    def _compute_state(self):
        for rec in self:
            if rec.invoice_id:
                rec.state = 'paid' if rec.invoice_id.payment_state == 'paid' else 'invoiced'
            else:
                rec.state = 'draft'

    def write(self, vals):
        if {'amount', 'student_id', 'route_id', 'billing_month'} & set(vals) and self.filtered('invoice_id'):
            raise ValidationError(_(
                "This transport bill is already invoiced. Change the invoice instead "
                "(Reset to Draft or Credit Note)."))
        return super().write(vals)

    def action_create_invoice(self):
        for rec in self:
            if rec.invoice_id:
                raise ValidationError(_("Invoice is already created for this transport fee."))
            if rec.amount <= 0:
                raise ValidationError(_("Cannot invoice a transport fee with zero amount."))
            if not rec.route_id.product_id:
                raise ValidationError(_("Please set a Transport Fee Product on route %s first.") % rec.route_id.name)
            invoice = self.env['account.move'].create({
                'move_type': 'out_invoice',
                'partner_id': rec.student_id.partner_id.id,
                'invoice_date': fields.Date.context_today(rec),
                'invoice_line_ids': [(0, 0, {
                    'name': _("Transport Fee - %s (%s)") % (rec.route_id.name, rec.billing_month.strftime('%B %Y')),
                    'product_id': rec.route_id.product_id.id,
                    'quantity': 1,
                    'price_unit': rec.amount,
                })],
                'company_id': rec.student_id.company_id.id,
            })
            invoice.action_post()
            rec.invoice_id = invoice.id

    def action_view_invoice(self):
        self.ensure_one()
        if not self.invoice_id:
            return
        return {
            'name': _("Invoice"),
            'view_mode': 'form',
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'type': 'ir.actions.act_window',
        }

class SchoolTransportRouteChangeRequest(models.Model):
    _name = 'school.transport.route.change.request'
    _description = 'Transport Route Change Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'request_date desc'

    student_id = fields.Many2one('school.student', string='Student', required=True, tracking=True)
    current_route_id = fields.Many2one('school.transport.route', string='Current Route (at Request Time)',
                                        readonly=True, copy=False)
    requested_route_id = fields.Many2one('school.transport.route', string='Requested Route',
                                          required=True, tracking=True)
    reason = fields.Text(string='Reason for Change')
    request_date = fields.Date(string='Request Date', default=fields.Date.context_today, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', required=True, tracking=True)
    approved_by = fields.Many2one('res.users', string='Decided By', readonly=True, copy=False)
    decision_date = fields.Datetime(string='Decision Date', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('current_route_id') and vals.get('student_id'):
                student = self.env['school.student'].browse(vals['student_id'])
                vals['current_route_id'] = student.transport_route_id.id
        return super().create(vals_list)

    @api.constrains('current_route_id', 'requested_route_id')
    def _check_different_route(self):
        for rec in self:
            if rec.requested_route_id and rec.current_route_id and rec.requested_route_id == rec.current_route_id:
                raise ValidationError(_("Requested route must be different from the current route."))

    def action_submit(self):
        self.write({'state': 'submitted'})

    def action_approve(self):
        for rec in self:
            if rec.state != 'submitted':
                raise ValidationError(_("Only submitted requests can be approved."))
            rec.student_id.write({
                'transport_route_id': rec.requested_route_id.id,
                'van_boarding_point_id': False,
            })
            rec.write({
                'state': 'approved',
                'approved_by': self.env.user.id,
                'decision_date': fields.Datetime.now(),
            })

    def action_reject(self):
        for rec in self:
            if rec.state != 'submitted':
                raise ValidationError(_("Only submitted requests can be rejected."))
            rec.write({
                'state': 'rejected',
                'approved_by': self.env.user.id,
                'decision_date': fields.Datetime.now(),
            })

class SchoolTransportAttendance(models.Model):
    _name = 'school.transport.attendance'
    _description = 'Transport Attendance'
    _inherit = ['mail.thread']
    _order = 'date desc, trip_type'

    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, tracking=True)
    route_id = fields.Many2one('school.transport.route', string='Route', required=True, tracking=True)
    trip_type = fields.Selection([
        ('morning', 'Morning Pickup'),
        ('evening', 'Evening Drop'),
    ], string='Trip', required=True, default='morning', tracking=True)
    # Snapshot of the driver at the time of the trip. Depends only on route_id, so a later
    # driver change on the route does not rewrite past attendance records.
    driver_id = fields.Many2one('res.partner', string='Driver', compute='_compute_driver_id',
                                 store=True, readonly=False, precompute=True)
    vehicle_id = fields.Many2one('school.vehicle', string='Vehicle', compute='_compute_vehicle_id',
                                  store=True, readonly=False, precompute=True)
    line_ids = fields.One2many('school.transport.attendance.line', 'attendance_id', string='Students')
    marked_by_id = fields.Many2one('res.users', string='Marked By', readonly=True, tracking=True)
    marked_source = fields.Selection([
        ('backend', 'Office'),
        ('driver_portal', 'Driver Mobile'),
    ], string='Marked From', default='backend', readonly=True)
    present_count = fields.Integer(string='Boarded', compute='_compute_counts', store=True)
    absent_count = fields.Integer(string='Absent', compute='_compute_counts', store=True)

    _route_date_trip_uniq = models.Constraint(
        'unique(route_id, date, trip_type)',
        'Attendance for this route, date and trip is already marked!'
    )

    @api.depends('route_id', 'date', 'trip_type')
    def _compute_display_name(self):
        trips = dict(self._fields['trip_type'].selection)
        for rec in self:
            rec.display_name = "%s - %s - %s" % (
                rec.route_id.name or _('New'), rec.date or '', trips.get(rec.trip_type, ''))

    @api.depends('line_ids.status')
    def _compute_counts(self):
        for rec in self:
            rec.present_count = len(rec.line_ids.filtered(lambda l: l.status == 'boarded'))
            rec.absent_count = len(rec.line_ids.filtered(lambda l: l.status == 'absent'))

    @api.depends('route_id')
    def _compute_vehicle_id(self):
        for rec in self:
            rec.vehicle_id = rec.route_id.effective_vehicle_id

    @api.depends('route_id')
    def _compute_driver_id(self):
        for rec in self:
            rec.driver_id = rec.route_id.effective_driver_id

    @api.onchange('route_id')
    def _onchange_route_id(self):
        # Rebuild the list whenever the route changes, so students of a previously
        # selected route do not stay in the table.
        commands = [Command.clear()]
        if self.route_id:
            commands += [Command.create({
                'student_id': student.id,
                'status': 'boarded',
            }) for student in self.route_id.student_ids]
        self.line_ids = commands

    def action_fetch_students(self):
        for rec in self:
            existing_students = rec.line_ids.mapped('student_id')
            new_lines = [(0, 0, {
                'student_id': student.id,
                'status': 'boarded',
            }) for student in rec.route_id.student_ids if student not in existing_students]
            if new_lines:
                rec.write({'line_ids': new_lines})

class SchoolTransportAttendanceLine(models.Model):
    _name = 'school.transport.attendance.line'
    _description = 'Transport Attendance Line'

    attendance_id = fields.Many2one('school.transport.attendance', string='Attendance', required=True, ondelete='cascade')
    student_id = fields.Many2one('school.student', string='Student', required=True)
    boarding_point_id = fields.Many2one('school.transport.stop', string='Boarding Point',
                                         related='student_id.van_boarding_point_id', readonly=True)
    status = fields.Selection([
        ('boarded', 'Boarded'),
        ('absent', 'Absent'),
    ], string='Status', required=True, default='boarded')

    _line_uniq = models.Constraint(
        'unique(attendance_id, student_id)', 'This student is already listed for this trip!'
    )


# ---------------------------------------------------------------------------
# WhatsApp Cloud API (Meta)
# ---------------------------------------------------------------------------
class SchoolWhatsappAccount(models.Model):
    _name = 'school.whatsapp.account'
    _description = 'WhatsApp Cloud API Account'

    name = fields.Char(default='WhatsApp Cloud API', required=True)
    active = fields.Boolean(default=True)
    test_mode = fields.Boolean(
        string='Test Mode', default=True,
        help="When on, messages are only written to the WhatsApp Log and never sent to Meta.")
    api_version = fields.Char(string='Graph API Version', default='v25.0', required=True)
    phone_number_id = fields.Char(string='Phone Number ID')
    business_account_id = fields.Char(string='WhatsApp Business Account ID')
    access_token = fields.Char(string='Access Token', groups='ad_school_management.group_school_admin')
    country_code = fields.Char(string='Default Country Code', default='91', required=True,
                               help="Added to 10-digit mobile numbers, e.g. 91 for India.")
    template_language = fields.Char(string='Template Language', default='en', required=True,
                                    help="Language code of your approved templates, e.g. en or en_US.")
    transport_template = fields.Char(string='Transport Template Name', default='transport_update', required=True)
    test_phone = fields.Char(string='Test Mobile Number')

    @api.model
    def _get_account(self):
        return self.sudo().search([('active', '=', True)], limit=1)

    def _normalize_phone(self, phone):
        digits = re.sub(r'\D', '', phone or '')
        if not digits:
            return False
        if len(digits) == 11 and digits.startswith('0'):
            digits = digits[1:]
        if len(digits) == 10:
            digits = (self.country_code or '') + digits
        return digits

    def _send_template(self, phone, template, params=None, language=None, partner=False, record=False):
        """Send one approved template message. Always creates a log line."""
        self.ensure_one()
        account = self.sudo()
        number = account._normalize_phone(phone)
        params = [str(p) if p not in (None, False, '') else '-' for p in (params or [])]
        log_vals = {
            'account_id': account.id,
            'partner_id': partner.id if partner else False,
            'phone': number or phone or '',
            'template_name': template,
            'parameters': ' | '.join(params),
            'res_model': record._name if record else False,
            'res_id': record.id if record else False,
        }
        Log = self.env['school.whatsapp.message'].sudo()
        if not number:
            return Log.create(dict(log_vals, state='failed', error=_('No mobile number.')))
        if account.test_mode or not (account.access_token and account.phone_number_id):
            return Log.create(dict(log_vals, state='test',
                                   error=False if account.test_mode else _('Access Token / Phone Number ID missing.')))
        payload = {
            'messaging_product': 'whatsapp',
            'to': number,
            'type': 'template',
            'template': {'name': template, 'language': {'code': language or account.template_language}},
        }
        if params:
            payload['template']['components'] = [{
                'type': 'body',
                'parameters': [{'type': 'text', 'text': p} for p in params],
            }]
        url = 'https://graph.facebook.com/%s/%s/messages' % (account.api_version, account.phone_number_id)
        try:
            resp = requests.post(url, json=payload, timeout=15, headers={
                'Authorization': 'Bearer %s' % account.access_token,
                'Content-Type': 'application/json',
            })
            data = resp.json() if resp.content else {}
        except Exception as e:  # network error, timeout, invalid JSON
            _logger.warning("WhatsApp send failed: %s", e)
            return Log.create(dict(log_vals, state='failed', error=str(e)[:500]))
        if resp.ok and data.get('messages'):
            return Log.create(dict(log_vals, state='sent', wa_message_id=data['messages'][0].get('id')))
        error = data.get('error', {})
        message = error.get('error_user_msg') or error.get('message') or resp.text
        return Log.create(dict(log_vals, state='failed', error=('[%s] %s' % (error.get('code', resp.status_code), message))[:500]))

    def action_send_hello_world(self):
        """Connectivity test with Meta's pre-approved 'hello_world' template."""
        self.ensure_one()
        if not self.test_phone:
            raise UserError(_("Enter a Test Mobile Number first."))
        log = self._send_template(self.test_phone, 'hello_world', language='en_US')
        return self._notify_result(log)

    def action_send_transport_test(self):
        self.ensure_one()
        if not self.test_phone:
            raise UserError(_("Enter a Test Mobile Number first."))
        log = self._send_template(self.test_phone, self.transport_template, [
            _('Driver updated'), 'Test Route', 'Van 1 (TN00AB0000)', 'Driver Name (9000000000)', 'Caretaker (9000000001)'])
        return self._notify_result(log)

    def _notify_result(self, log):
        kind = {'sent': 'success', 'test': 'info', 'failed': 'danger'}[log.state]
        message = {
            'sent': _('Message accepted by WhatsApp.'),
            'test': _('Test Mode: logged only, not sent.'),
            'failed': log.error or _('Failed.'),
        }[log.state]
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('WhatsApp'), 'message': message, 'type': kind, 'sticky': log.state == 'failed'}}


class SchoolWhatsappMessage(models.Model):
    _name = 'school.whatsapp.message'
    _description = 'WhatsApp Message Log'
    _order = 'id desc'

    account_id = fields.Many2one('school.whatsapp.account', string='Account', ondelete='set null')
    partner_id = fields.Many2one('res.partner', string='Recipient')
    phone = fields.Char(string='Mobile')
    template_name = fields.Char(string='Template')
    parameters = fields.Char(string='Values')
    state = fields.Selection([
        ('test', 'Test (not sent)'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ], string='Status', required=True, default='test')
    error = fields.Char(string='Error / Note')
    wa_message_id = fields.Char(string='WhatsApp Message ID')
    res_model = fields.Char(string='Related Model')
    res_id = fields.Integer(string='Related Record')