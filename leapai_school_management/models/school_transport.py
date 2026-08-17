# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class SchoolTransportVehicle(models.Model):
    _name = 'school.transport.vehicle'
    _description = 'Transport Vehicle'
    _order = 'name'

    name = fields.Char(string='Vehicle Name', required=True, help='e.g. Bus 1')
    plate_number = fields.Char(string='Plate Number')
    capacity = fields.Integer(string='Capacity')
    driver_name = fields.Char(string='Driver Name')
    driver_phone = fields.Char(string='Driver Phone')
    active = fields.Boolean(default=True)

    _plate_uniq = models.Constraint('UNIQUE(plate_number)', 'Plate number must be unique!')


class SchoolTransportRoute(models.Model):
    _name = 'school.transport.route'
    _description = 'Transport Route'
    _order = 'name'

    name = fields.Char(string='Route Name', required=True, help='e.g. Route A - North')
    vehicle_id = fields.Many2one('school.transport.vehicle', string='Vehicle')
    pickup_time = fields.Char(string='Pickup Time', help='e.g. 7:00 AM')
    dropoff_time = fields.Char(string='Drop-off Time', help='e.g. 2:30 PM')
    stops = fields.Text(string='Stops', help='Comma-separated list of stops')
    student_ids = fields.One2many('school.student', 'transport_route_id', string='Students')
    student_count = fields.Integer(
        string='Student Count',
        compute='_compute_student_count',
        store=True,
    )
    active = fields.Boolean(default=True)

    @api.depends('student_ids')
    def _compute_student_count(self):
        for record in self:
            record.student_count = len(record.student_ids)

    def action_view_students(self):
        from odoo import _
        return {
            'name': _('Students'),
            'type': 'ir.actions.act_window',
            'res_model': 'school.student',
            'view_mode': 'list,form',
            'domain': [('transport_route_id', '=', self.id)],
        }
