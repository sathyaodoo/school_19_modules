# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SchoolHostel(models.Model):
    _name = 'school.hostel'
    _description = 'Hostel'
    _order = 'name'

    name = fields.Char(string='Hostel Name', required=True, help='e.g. Boys Hostel')
    hostel_type = fields.Selection([
        ('boys', 'Boys'),
        ('girls', 'Girls'),
        ('mixed', 'Mixed'),
    ], string='Hostel Type', default='mixed')
    warden_name = fields.Char(string='Warden Name')
    warden_phone = fields.Char(string='Warden Phone')
    room_ids = fields.One2many('school.hostel.room', 'hostel_id', string='Rooms')
    room_count = fields.Integer(string='Room Count', compute='_compute_stats', store=True)
    capacity = fields.Integer(string='Total Capacity', compute='_compute_stats', store=True)
    occupied = fields.Integer(string='Occupied', compute='_compute_stats', store=True)
    active = fields.Boolean(default=True)

    @api.depends('room_ids', 'room_ids.capacity', 'room_ids.occupied')
    def _compute_stats(self):
        for record in self:
            record.room_count = len(record.room_ids)
            record.capacity = sum(record.room_ids.mapped('capacity'))
            record.occupied = sum(record.room_ids.mapped('occupied'))

    def action_view_rooms(self):
        return {
            'name': _('Rooms'),
            'type': 'ir.actions.act_window',
            'res_model': 'school.hostel.room',
            'view_mode': 'list,form',
            'domain': [('hostel_id', '=', self.id)],
        }


class SchoolHostelRoom(models.Model):
    _name = 'school.hostel.room'
    _description = 'Hostel Room'
    _order = 'name'

    name = fields.Char(string='Room Name', required=True, help='e.g. Room 101')
    hostel_id = fields.Many2one('school.hostel', string='Hostel', required=True, ondelete='cascade')
    room_type = fields.Selection([
        ('single', 'Single'),
        ('double', 'Double'),
        ('triple', 'Triple'),
        ('dormitory', 'Dormitory'),
    ], string='Room Type', default='single')
    capacity = fields.Integer(string='Capacity', default=1)
    floor = fields.Integer(string='Floor')
    monthly_fee = fields.Monetary(string='Monthly Fee', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    allocation_ids = fields.One2many('school.hostel.allocation', 'room_id', string='Allocations')
    occupied = fields.Integer(string='Occupied', compute='_compute_occupancy', store=True)
    available = fields.Integer(string='Available', compute='_compute_occupancy', store=True)
    state = fields.Selection([
        ('available', 'Available'),
        ('partial', 'Partial'),
        ('full', 'Full'),
    ], string='Status', compute='_compute_occupancy', store=True)

    @api.depends('allocation_ids', 'allocation_ids.state', 'capacity')
    def _compute_occupancy(self):
        for record in self:
            active_allocations = record.allocation_ids.filtered(lambda a: a.state == 'active')
            record.occupied = len(active_allocations)
            record.available = max(0, (record.capacity or 0) - record.occupied)
            if record.occupied == 0:
                record.state = 'available'
            elif record.occupied >= (record.capacity or 1):
                record.state = 'full'
            else:
                record.state = 'partial'


class SchoolHostelAllocation(models.Model):
    _name = 'school.hostel.allocation'
    _description = 'Hostel Allocation'
    _order = 'check_in desc'

    student_id = fields.Many2one('school.student', string='Student', required=True)
    room_id = fields.Many2one('school.hostel.room', string='Room', required=True)
    check_in = fields.Date(string='Check-In Date')
    check_out = fields.Date(string='Check-Out Date')
    state = fields.Selection([
        ('active', 'Active'),
        ('checked_out', 'Checked Out'),
    ], string='Status', default='active')

    def action_check_out(self):
        for record in self:
            record.state = 'checked_out'
            record.check_out = fields.Date.today()
