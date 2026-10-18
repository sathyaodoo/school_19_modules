# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SchoolTransportConfig(models.Model):
    """Thresholds and switches of the smart transport alerts (one record per school / company)."""
    _name = 'school.transport.config'
    _description = 'Smart transport settings'
    _rec_name = 'company_id'

    company_id = fields.Many2one('res.company', string='School / Board', required=True, default=lambda self: self.env.company)
    # speed
    speed_limit_kmh = fields.Float(string='Speed Limit (km/h)', default=60.0,
                                   help="Alert when a vehicle is faster than this. A vehicle can have its own limit.")
    speed_alert_pings = fields.Integer(string='Pings over the limit', default=2,
                                       help="Number of GPS pings in a row over the limit before the alert (avoids GPS noise).")
    speed_alert_cooldown_min = fields.Integer(string='Minutes between speed alerts', default=5)
    # stops / geofence
    approach_distance_m = fields.Integer(string='"Van approaching" distance (m)', default=500,
                                         help="Parents of a stop are told when the van is this close to the stop.")
    arrival_radius_m = fields.Integer(string='Default stop radius (m)', default=80,
                                      help="A stop counts as reached inside this radius (a stop can have its own).")
    # route
    deviation_distance_m = fields.Integer(string='Route deviation distance (m)', default=400,
                                           help="Alert when the van is farther than this from the line through the stops.")
    deviation_pings = fields.Integer(string='Pings off the route', default=2)
    stationary_minutes = fields.Integer(string='Stopped for (minutes)', default=10,
                                        help="Alert when the van does not move for this long away from a stop / school.")
    # behaviour
    harsh_brake_kmh_s = fields.Float(string='Harsh braking (km/h per second)', default=10.0)
    harsh_accel_kmh_s = fields.Float(string='Harsh acceleration (km/h per second)', default=9.0)
    # ETA
    eta_default_speed_kmh = fields.Float(string='Default speed for ETA (km/h)', default=25.0)
    road_factor = fields.Float(string='Road factor', default=1.3,
                               help="Roads are longer than the straight line: distance is multiplied by this.")
    # campus
    campus_latitude = fields.Float(string='School Latitude', digits=(10, 7))
    campus_longitude = fields.Float(string='School Longitude', digits=(10, 7))
    campus_radius_m = fields.Integer(string='School Radius (m)', default=200)
    has_campus = fields.Boolean(compute='_compute_has_campus')
    # who is told
    notify_parent_approach = fields.Boolean(string='Parents: van approaching', default=True)
    notify_parent_board = fields.Boolean(string='Parents: child boarded', default=True)
    notify_parent_reached = fields.Boolean(string='Parents: child reached stop / school', default=True)
    notify_parent_breakdown = fields.Boolean(string='Parents: vehicle breakdown', default=True)
    notify_parent_sos = fields.Boolean(string='Parents: emergency SOS (automatically)', default=False,
                                       help="Off: the school is told first and decides when to inform the parents.")
    alert_user_ids = fields.Many2many('res.users', 'school_transport_config_user_rel', 'config_id', 'user_id',
                                      string='Also alert these users',
                                      help="School admin and principal are always alerted.")

    _company_uniq = models.Constraint('unique(company_id)', 'There is already a transport setting for this school.')

    @api.depends('campus_latitude', 'campus_longitude')
    def _compute_has_campus(self):
        for cfg in self:
            cfg.has_campus = bool(cfg.campus_latitude and cfg.campus_longitude)

    @api.model
    def _get(self, company=None):
        company = company or self.env.company
        cfg = self.sudo().search([('company_id', '=', company.id)], limit=1)
        return cfg or self.sudo().create({'company_id': company.id})

    @api.model
    def action_open_settings(self):
        """Menu entry: open the settings record of the current school."""
        cfg = self._get()
        return {'type': 'ir.actions.act_window', 'name': 'Transport Alert Settings', 'res_model': self._name,
                'res_id': cfg.id, 'view_mode': 'form', 'target': 'current'}
