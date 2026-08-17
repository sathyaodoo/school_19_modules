from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SchoolVehicle(models.Model):
    _name = 'school.vehicle'
    _description = 'School Vehicle'

    name = fields.Char(string='Vehicle Name', required=True)
    vehicle_number = fields.Char(string='Vehicle Number', required=True)
    capacity = fields.Integer(string='Passenger Capacity', default=40, required=True)
    driver_id = fields.Many2one('res.partner', string='Driver')

    _number_uniq = models.Constraint(
        'unique(vehicle_number)', 'Vehicle number must be unique!'
    )

    @api.constrains('capacity')
    def _check_capacity(self):
        for rec in self:
            if rec.capacity <= 0:
                raise ValidationError(_("Vehicle capacity must be greater than zero."))

class SchoolTransportRoute(models.Model):
    _name = 'school.transport.route'
    _description = 'Transport Route'

    name = fields.Char(string='Route Name', required=True)
    vehicle_id = fields.Many2one('school.vehicle', string='Assigned Vehicle')
    driver_id = fields.Many2one('res.partner', related='vehicle_id.driver_id', store=True, readonly=True)
    cost = fields.Float(string='Monthly Cost')
    stop_ids = fields.One2many('school.transport.stop', 'route_id', string='Route Stops')

    @api.constrains('cost')
    def _check_cost(self):
        for route in self:
            if route.cost < 0:
                raise ValidationError(_("Route monthly cost cannot be negative."))

class SchoolTransportStop(models.Model):
    _name = 'school.transport.stop'
    _description = 'Transport Route Stop'
    _order = 'sequence'

    route_id = fields.Many2one('school.transport.route', string='Route', required=True, ondelete='cascade')
    name = fields.Char(string='Stop Name', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    time = fields.Float(string='Expected Time (Hour)', help="Use 8.5 for 08:30 AM")
