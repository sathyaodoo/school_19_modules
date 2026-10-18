# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError

from ..models.geo import offset_point


class SchoolTransportPingWizard(models.TransientModel):
    """Send a test GPS ping to see the alerts work without a real device (demo / training)."""
    _name = 'school.transport.ping.wizard'
    _description = 'Send a test GPS ping'

    vehicle_id = fields.Many2one('school.vehicle', string='Vehicle', required=True)
    mode = fields.Selection([('stop', 'Near a stop'), ('campus', 'At the school'), ('coordinates', 'Exact coordinates')],
                            string='Where', required=True, default='stop')
    stop_id = fields.Many2one('school.transport.stop', string='Stop')
    meters_before = fields.Float(string='Distance from the stop (m)', default=400.0,
                                 help="The test position is this many metres north of the stop.")
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    speed = fields.Float(string='Speed (km/h)', default=20.0)
    ping_at = fields.Datetime(string='Time of the ping', default=fields.Datetime.now,
                              help="Change it to a later time to test 'stopped for a long time'.")

    def action_send(self):
        self.ensure_one()
        cfg = self.env['school.transport.config']._get()
        if self.mode == 'stop':
            if not self.stop_id or not self.stop_id.has_location:
                raise UserError(_("Choose a stop that has coordinates."))
            lat, lon = offset_point(self.stop_id.latitude, self.stop_id.longitude, north_m=self.meters_before)
        elif self.mode == 'campus':
            if not cfg.has_campus:
                raise UserError(_("Set the school coordinates in Transport Settings first."))
            lat, lon = cfg.campus_latitude, cfg.campus_longitude
        else:
            lat, lon = self.latitude, self.longitude
        Event = self.env['school.transport.event'].sudo()
        last = Event.search([], order='id desc', limit=1).id or 0
        self.vehicle_id.sudo()._register_location(lat, lon, speed=self.speed, recorded_at=self.ping_at, source='manual')
        new = Event.search([('id', '>', last), ('vehicle_id', '=', self.vehicle_id.id)])
        types = dict(Event._fields['event_type'].selection)
        message = _("Ping sent (%(lat).5f, %(lon).5f at %(speed)d km/h).", lat=lat, lon=lon, speed=round(self.speed))
        if new:
            message += ' ' + _("New: %s.", ', '.join(types[t] for t in new.mapped('event_type')))
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _("GPS test"), 'message': message, 'type': 'success', 'sticky': False}}
