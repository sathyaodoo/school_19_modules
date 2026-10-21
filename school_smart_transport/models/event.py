# -*- coding: utf-8 -*-
import logging

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

EVENT_TYPES = [
    ('trip_start', 'Trip started'), ('trip_end', 'Trip finished'),
    ('geofence_enter', 'Entered a geofence'), ('geofence_exit', 'Left a geofence'),
    ('approaching', 'Van approaching a stop'),
    ('speeding', 'Excessive speed'), ('harsh_brake', 'Harsh braking'), ('harsh_accel', 'Harsh acceleration'),
    ('deviation', 'Route deviation'), ('back_on_route', 'Back on route'),
    ('stationary', 'Stopped for a long time'),
    ('breakdown', 'Vehicle breakdown'), ('sos', 'Emergency SOS'),
    ('left_on_board', 'Student left on board'),
]
SEVERITY = {
    'trip_start': 'info', 'trip_end': 'info', 'geofence_enter': 'info', 'geofence_exit': 'info',
    'approaching': 'info', 'harsh_brake': 'info', 'harsh_accel': 'info', 'back_on_route': 'info',
    'speeding': 'warning', 'deviation': 'warning', 'stationary': 'warning',
    'breakdown': 'critical', 'sos': 'critical', 'left_on_board': 'critical',
}


def staff_users(env, cfg):
    """School admin and principal, plus the users chosen in the transport settings."""
    groups = env.ref('ad_school_management.group_school_admin') | env.ref('ad_school_management.group_school_principal')
    users = env['res.users'].sudo().search([('all_group_ids', 'in', groups.ids), ('share', '=', False)])
    return users | cfg.alert_user_ids


class SchoolTransportEvent(models.Model):
    """Everything that happens on a trip: geofence, alerts, SOS... Warnings and critical events need a reaction."""
    _name = 'school.transport.event'
    _description = 'Transport event / alert'
    _order = 'event_at desc, id desc'

    vehicle_id = fields.Many2one('school.vehicle', string='Vehicle', required=True, ondelete='cascade', index=True)
    trip_id = fields.Many2one('school.transport.trip', string='Trip', ondelete='set null', index=True)
    route_id = fields.Many2one('school.transport.route', related='trip_id.route_id', store=True, string='Route')
    driver_id = fields.Many2one('res.partner', related='trip_id.driver_id', store=True, string='Driver')
    event_type = fields.Selection(EVENT_TYPES, string='Event', required=True, index=True)
    severity = fields.Selection([('info', 'Information'), ('warning', 'Warning'), ('critical', 'Critical')],
                                string='Severity', required=True, default='info', index=True)
    event_at = fields.Datetime(string='When', required=True, default=fields.Datetime.now, index=True)
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    speed = fields.Float(string='Speed (km/h)')
    stop_id = fields.Many2one('school.transport.stop', string='Stop')
    message = fields.Char(string='Details', required=True)
    state = fields.Selection([('open', 'Needs attention'), ('acknowledged', 'Acknowledged'), ('resolved', 'Resolved')],
                             string='Status', default='open', required=True, index=True)
    handled_by = fields.Many2one('res.users', string='Handled By', readonly=True)
    handled_at = fields.Datetime(string='Handled On', readonly=True)
    note = fields.Text(string='What was done')
    staff_notified = fields.Boolean(readonly=True)
    parents_notified = fields.Boolean(readonly=True)
    map_url = fields.Char(compute='_compute_map_url')

    @api.depends('latitude', 'longitude')
    def _compute_map_url(self):
        for event in self:
            event.map_url = ('https://www.openstreetmap.org/?mlat=%s&mlon=%s#map=16/%s/%s' % (
                event.latitude, event.longitude, event.latitude, event.longitude)) if event.latitude and event.longitude else False

    @api.depends('event_type', 'message')
    def _compute_display_name(self):
        types = dict(self._fields['event_type'].selection)
        for event in self:
            event.display_name = '%s: %s' % (types.get(event.event_type, ''), event.message or '')

    # ------------------------------------------------------------------ creating events
    @api.model
    def _raise(self, vehicle, event_type, message, trip=None, severity=None, lat=None, lon=None, speed=0.0,
               stop=None, at=None, notify_staff=None):
        severity = severity or SEVERITY.get(event_type, 'info')
        if notify_staff is None:
            notify_staff = severity != 'info'
        event = self.sudo().create({
            'vehicle_id': vehicle.id, 'trip_id': trip.id if trip else False, 'event_type': event_type,
            'severity': severity, 'event_at': at or fields.Datetime.now(),
            'latitude': lat if lat is not None else vehicle.last_latitude,
            'longitude': lon if lon is not None else vehicle.last_longitude,
            'speed': speed or 0.0, 'stop_id': stop.id if stop else False, 'message': message,
            'state': 'resolved' if severity == 'info' else 'open'})
        if notify_staff:
            event._notify_staff()
        return event

    def _notify_staff(self):
        cfg = self.env['school.transport.config']._get()
        users = staff_users(self.env, cfg)
        partners = users.mapped('partner_id').ids
        severities = dict(self._fields['severity'].selection)
        types = dict(self._fields['event_type'].selection)
        for event in self:
            if partners:
                try:
                    self.env['mail.thread'].sudo().message_notify(
                        partner_ids=partners,
                        subject=_("Transport %(severity)s: %(type)s - %(vehicle)s", severity=severities[event.severity],
                                  type=types[event.event_type], vehicle=event.vehicle_id.name),
                        body=Markup(_("<p><b>%(type)s</b> (%(severity)s)</p><p>%(message)s</p>"
                                      "<p>Vehicle: %(vehicle)s &middot; Route: %(route)s &middot; %(when)s</p>"
                                      "<p>Open Transport &gt; Alerts to handle it.</p>")) % {
                            'type': types[event.event_type], 'severity': severities[event.severity],
                            'message': event.message, 'vehicle': event.vehicle_id.name,
                            'route': event.route_id.name or '-', 'when': event.event_at})
                except Exception:
                    _logger.exception("Smart transport: staff alert could not be sent")
            event.staff_notified = bool(partners)

    # ------------------------------------------------------------------ handling
    def action_acknowledge(self):
        for event in self.filtered(lambda e: e.state == 'open'):
            event.write({'state': 'acknowledged', 'handled_by': self.env.uid, 'handled_at': fields.Datetime.now()})

    def action_resolve(self):
        for event in self:
            if event.severity == 'critical' and not (event.note or '').strip():
                raise UserError(_("Write what was done in 'What was done' before resolving a critical event."))
            event.write({'state': 'resolved', 'handled_by': self.env.uid, 'handled_at': fields.Datetime.now()})

    def _affected_students(self):
        self.ensure_one()
        if self.trip_id:
            return self.trip_id.route_id.student_ids
        routes = self.env['school.transport.route'].sudo().search(
            ['|', ('vehicle_id', '=', self.vehicle_id.id), ('effective_vehicle_id', '=', self.vehicle_id.id)])
        return routes.student_ids

    def action_inform_parents(self):
        """Tell the parents of the route what happened (breakdown / emergency), once."""
        for event in self:
            if event.event_type not in ('breakdown', 'sos'):
                raise UserError(_("Only a breakdown or an emergency can be sent to the parents from here."))
            if event.parents_notified:
                raise UserError(_("The parents have already been informed."))
            event._inform_parents()

    def _inform_parents(self):
        self.ensure_one()
        route = self.route_id.name or '-'
        vehicle = self.vehicle_id.name or '-'
        if self.event_type == 'breakdown':
            kind, subject = 'breakdown', _("Van breakdown - %s", route)
            text = _("The van %(vehicle)s of route %(route)s has had a breakdown. The school is arranging a replacement "
                     "and will keep you informed.", vehicle=vehicle, route=route)
        else:
            kind, subject = 'sos', _("Emergency on the van - %s", route)
            text = _("An emergency has been reported on the van %(vehicle)s of route %(route)s. The school is responding "
                     "and will update you shortly.", vehicle=vehicle, route=route)
        self.env['school.transport.notification']._notify_parents(self._affected_students(), kind, subject, text, trip=self.trip_id)
        self.parents_notified = True

    def action_open_route(self):
        self.ensure_one()
        if not self.route_id:
            raise UserError(_("This event is not linked to a route."))
        return {'type': 'ir.actions.act_window', 'res_model': 'school.transport.route', 'res_id': self.route_id.id,
                'view_mode': 'form', 'target': 'current'}


class SchoolTransportNotification(models.Model):
    """What the parents were told (and by which channel). Parents see their own child's rows in the portal."""
    _name = 'school.transport.notification'
    _description = 'Transport notification to a parent'
    _order = 'sent_at desc, id desc'

    student_id = fields.Many2one('school.student', string='Student', required=True, ondelete='cascade', index=True)
    parent_id = fields.Many2one('school.parent', string='Parent', ondelete='set null')
    partner_id = fields.Many2one('res.partner', string='Sent To')
    trip_id = fields.Many2one('school.transport.trip', string='Trip', ondelete='set null')
    kind = fields.Selection([
        ('approaching', 'Van approaching'), ('boarded', 'Child boarded'), ('reached_stop', 'Child reached the stop'),
        ('reached_school', 'Child reached school'), ('breakdown', 'Vehicle breakdown'), ('sos', 'Emergency'),
    ], string='Kind', required=True, index=True)
    subject = fields.Char(string='Subject')
    message = fields.Text(string='Message')
    sent_at = fields.Datetime(string='Sent On', default=fields.Datetime.now)
    inbox_sent = fields.Boolean(string='Inbox / email', readonly=True)
    whatsapp_state = fields.Selection([('none', 'Not used'), ('test', 'Test (not sent)'), ('sent', 'Sent'), ('failed', 'Failed')],
                                      string='WhatsApp', default='none', readonly=True)

    @api.model
    def _notify_parents(self, students, kind, subject, text, trip=None):
        """Inbox / email through Odoo, a WhatsApp copy with the school's transport template, and a log row."""
        created = self.browse()
        account = self.env['school.whatsapp.account']._get_account()
        vehicle = trip.vehicle_id if trip else self.env['school.vehicle']
        driver = trip.driver_id if trip else self.env['res.partner']
        caretaker = vehicle.caretaker_id
        for student in students:
            for parent in student.parent_ids:
                partner = parent.partner_id
                if not partner:
                    continue
                row = self.sudo().create({'student_id': student.id, 'parent_id': parent.id, 'partner_id': partner.id,
                                          'trip_id': trip.id if trip else False, 'kind': kind, 'subject': subject,
                                          'message': text})
                try:
                    self.env['mail.thread'].sudo().message_notify(
                        partner_ids=partner.ids, subject=subject, body=Markup('<p>%s</p>') % text)
                    row.inbox_sent = True
                except Exception:
                    _logger.exception("Smart transport: parent message could not be sent")
                if account and partner.phone:
                    try:
                        log = account._send_template(
                            partner.phone, account.transport_template,
                            [text, trip.route_id.name if trip else '-',
                             '%s (%s)' % (vehicle.name, vehicle.vehicle_number) if vehicle else '-',
                             '%s (%s)' % (driver.name, driver.phone or '-') if driver else '-',
                             '%s (%s)' % (caretaker.name, caretaker.phone or '-') if caretaker else '-'],
                            partner=partner, record=trip or False)
                        row.whatsapp_state = log.state
                    except Exception:
                        _logger.exception("Smart transport: WhatsApp copy could not be sent")
                created |= row
        return created
