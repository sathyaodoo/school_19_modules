# -*- coding: utf-8 -*-
from odoo import _, models


class SchoolTransportRoute(models.Model):
    """Replacement seats from the LIVE trip: a student who got off frees the seat at once."""
    _inherit = 'school.transport.route'

    def _running_trip(self, domain):
        return self.env['school.transport.trip'].sudo().search(domain + [('state', '=', 'running')], limit=1)

    def _replacement_seats_used(self, vehicle):
        trip = self._running_trip([('vehicle_id', '=', vehicle.id)])
        return trip.on_board_count if trip else super()._replacement_seats_used(vehicle)

    def _students_to_move(self):
        trip = self._running_trip([('route_id', '=', self.id)])
        return trip.on_board_count if trip else super()._students_to_move()

    def _seat_basis(self, vehicle):
        if self._running_trip([('vehicle_id', '=', vehicle.id)]) or self._running_trip([('route_id', '=', self.id)]):
            return _("Students on board now (live trip)")
        return super()._seat_basis(vehicle)
