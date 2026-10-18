# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .geo import parse_coordinates

_logger = logging.getLogger(__name__)


class SchoolTransportStop(models.Model):
    _inherit = 'school.transport.stop'

    latitude = fields.Float(string='Latitude', digits=(10, 7))
    longitude = fields.Float(string='Longitude', digits=(10, 7))
    radius_m = fields.Integer(string='Geofence Radius (m)',
                              help="Inside this circle the van has reached the stop. 0 = the school default.")
    coordinates_text = fields.Char(string='Paste Coordinates', store=False,
                                   help="Paste 'latitude, longitude' copied from a map, e.g. 11.0168, 76.9558.")
    has_location = fields.Boolean(compute='_compute_has_location')
    map_url = fields.Char(compute='_compute_has_location')

    @api.depends('latitude', 'longitude')
    def _compute_has_location(self):
        for stop in self:
            stop.has_location = bool(stop.latitude and stop.longitude)
            stop.map_url = ('https://www.openstreetmap.org/?mlat=%s&mlon=%s#map=17/%s/%s' % (
                stop.latitude, stop.longitude, stop.latitude, stop.longitude)) if stop.has_location else False

    @api.onchange('coordinates_text')
    def _onchange_coordinates_text(self):
        parsed = parse_coordinates(self.coordinates_text)
        if parsed:
            self.latitude, self.longitude = parsed

    @api.constrains('latitude', 'longitude', 'radius_m')
    def _check_geofence(self):
        for stop in self:
            if not (-90 <= stop.latitude <= 90 and -180 <= stop.longitude <= 180):
                raise ValidationError(_("The coordinates of stop '%s' are not valid.", stop.name))
            if stop.radius_m < 0:
                raise ValidationError(_("The geofence radius cannot be negative."))

    def _geofence_radius(self, cfg):
        self.ensure_one()
        return self.radius_m or cfg.arrival_radius_m


class SchoolVehicle(models.Model):
    _inherit = 'school.vehicle'

    speed_limit_kmh = fields.Float(string='Speed Limit (km/h)', help="0 = the school default (Transport Settings).")
    over_speed_count = fields.Integer(readonly=True, copy=False)
    over_speed_alert_at = fields.Datetime(readonly=True, copy=False)
    trip_ids = fields.One2many('school.transport.trip', 'vehicle_id', string='Trips')

    # every GPS ping (provider, device or the driver's phone) comes through this method
    def _register_location(self, latitude, longitude, speed=0.0, recorded_at=None, source='device'):
        self.ensure_one()
        recorded_at = recorded_at or fields.Datetime.now()
        prev = {'speed': self.last_speed, 'at': self.last_location_at,
                'lat': self.last_latitude, 'lon': self.last_longitude}
        res = super()._register_location(latitude, longitude, speed=speed, recorded_at=recorded_at, source=source)
        if prev['at'] and recorded_at < prev['at']:
            return res                                   # a late (out of order) ping is stored but raises no alert
        try:
            with self.env.cr.savepoint():
                self.env['school.transport.trip'].sudo()._process_ping(self, latitude, longitude, speed, recorded_at, prev)
        except Exception:                                # the GPS data itself must never be lost because of an alert
            _logger.exception("Smart transport: the GPS ping of %s could not be processed", self.display_name)
        return res

    def _check_speeding(self, cfg, speed, at, lat, lon, trip):
        """Alert after a few pings in a row over the limit; then a pause so the staff is not flooded."""
        self.ensure_one()
        limit = self.speed_limit_kmh or cfg.speed_limit_kmh
        if limit and speed > limit:
            count = self.over_speed_count + 1
            vals = {'over_speed_count': count}
            pause = timedelta(minutes=cfg.speed_alert_cooldown_min)
            if count >= cfg.speed_alert_pings and (not self.over_speed_alert_at or at - self.over_speed_alert_at >= pause):
                vals['over_speed_alert_at'] = at
                self.env['school.transport.event']._raise(
                    self, 'speeding', _("%(vehicle)s is driving at %(speed)d km/h (limit %(limit)d km/h).",
                                        vehicle=self.name, speed=round(speed), limit=round(limit)),
                    trip=trip, lat=lat, lon=lon, speed=speed, at=at)
            self.sudo().write(vals)
        elif self.over_speed_count:
            self.sudo().write({'over_speed_count': 0})

    def _raise_sos(self, source='device', lat=None, lon=None, note=None):
        """Emergency SOS from the GPS device's panic button (or anywhere else)."""
        self.ensure_one()
        trip = self.env['school.transport.trip'].sudo().search([('vehicle_id', '=', self.id), ('state', '=', 'running')], limit=1)
        return trip._raise_sos(source=source, lat=lat, lon=lon, note=note) if trip else \
            self.env['school.transport.trip']._sos_without_trip(self, source=source, lat=lat, lon=lon, note=note)
