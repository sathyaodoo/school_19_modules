from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SchoolHostel(models.Model):
    _name = 'school.hostel'
    _description = 'Hostel'

    name = fields.Char(string='Hostel Name', required=True)
    type = fields.Selection([
        ('boys', 'Boys Hostel'),
        ('girls', 'Girls Hostel')
    ], string='Hostel Type', required=True, default='boys')
    address = fields.Char(string='Address')
    capacity = fields.Integer(string='Total Capacity')
    room_count = fields.Integer(string='Rooms Count', compute='_compute_hostel_stats')
    occupied_beds = fields.Integer(string='Occupied Beds', compute='_compute_hostel_stats')
    active_residents = fields.Integer(string='Active Residents', compute='_compute_hostel_stats')

    def _compute_hostel_stats(self):
        for hostel in self:
            rooms = self.env['school.hostel.room'].search([('hostel_id', '=', hostel.id)])
            hostel.room_count = len(rooms)
            allocations = self.env['school.hostel.allocation'].search([
                ('hostel_id', '=', hostel.id),
                ('state', '=', 'allocated')
            ])
            hostel.occupied_beds = len(allocations)
            hostel.active_residents = len(allocations.mapped('student_id'))

    def action_view_rooms(self):
        self.ensure_one()
        return {
            'name': _('Hostel Rooms'),
            'type': 'ir.actions.act_window',
            'res_model': 'school.hostel.room',
            'view_mode': 'list,form',
            'domain': [('hostel_id', '=', self.id)],
            'context': {'default_hostel_id': self.id},
        }

    def action_view_allocations(self):
        self.ensure_one()
        return {
            'name': _('Hostel Allocations'),
            'type': 'ir.actions.act_window',
            'res_model': 'school.hostel.allocation',
            'view_mode': 'list,form,pivot,graph',
            'domain': [('hostel_id', '=', self.id)],
            'context': {'default_hostel_id': self.id},
        }

class SchoolHostelRoom(models.Model):
    _name = 'school.hostel.room'
    _description = 'Hostel Room'
    _order = 'name'

    hostel_id = fields.Many2one('school.hostel', string='Hostel', required=True, ondelete='cascade')
    name = fields.Char(string='Room Name/No.', required=True)
    capacity = fields.Integer(string='Bed Capacity', default=4, required=True)
    availability = fields.Integer(string='Available Beds', compute='_compute_availability', store=True)
    occupied_beds = fields.Integer(string='Occupied Beds', compute='_compute_occupied_beds', store=True)
    rent = fields.Float(string='Monthly Rent')
    allocation_ids = fields.One2many('school.hostel.allocation', 'room_id', string='Allocations')

    _hostel_room_uniq = models.Constraint(
        'unique(hostel_id, name)', 'Room number must be unique in this hostel!'
    )

    @api.constrains('capacity', 'rent')
    def _check_values(self):
        for room in self:
            if room.capacity <= 0:
                raise ValidationError(_("Room capacity must be greater than zero."))
            if room.rent < 0:
                raise ValidationError(_("Room rent cannot be negative."))

    @api.depends('capacity', 'allocation_ids.state')
    def _compute_availability(self):
        for room in self:
            allocated = self.env['school.hostel.allocation'].search_count([
                ('room_id', '=', room.id),
                ('state', '=', 'allocated')
            ])
            room.availability = max(room.capacity - allocated, 0)

    @api.depends('capacity', 'availability')
    def _compute_occupied_beds(self):
        for room in self:
            room.occupied_beds = room.capacity - room.availability

class SchoolHostelAllocation(models.Model):
    _name = 'school.hostel.allocation'
    _description = 'Hostel Room Allocation'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    room_id = fields.Many2one('school.hostel.room', string='Room', required=True, tracking=True)
    hostel_id = fields.Many2one('school.hostel', string='Hostel', related='room_id.hostel_id', store=True)
    student_id = fields.Many2one('school.student', string='Student', required=True, tracking=True)
    partner_id = fields.Many2one('res.partner', string='Partner', related='student_id.partner_id', store=True)
    date_start = fields.Date(string='Allocation Start Date', required=True, default=fields.Date.context_today, tracking=True)
    date_end = fields.Date(string='Vacated Date', tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('allocated', 'Allocated'),
        ('vacated', 'Vacated')
    ], string='Status', default='draft', required=True, tracking=True)

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_start > rec.date_end:
                raise ValidationError(_("Vacated date must be after start date!"))

    def action_allocate(self):
        for rec in self:
            if rec.room_id.availability <= 0:
                raise ValidationError(_("This room has no available beds."))
            rec.student_id.write({'hostel_room_id': rec.room_id.id})
            rec.write({'state': 'allocated'})

    def action_vacate(self):
        for rec in self:
            today = fields.Date.context_today(rec)
            rec.student_id.write({'hostel_room_id': False})
            rec.write({
                'date_end': today,
                'state': 'vacated'
            })

class SchoolStudent(models.Model):
    _inherit = 'school.student'

    hostel_room_id = fields.Many2one('school.hostel.room', string='Hostel Room')
    hostel_allocation_ids = fields.One2many('school.hostel.allocation', 'student_id', string='Hostel Allocations')
    hostel_allocation_count = fields.Integer(string='Hostel Allocations Count', compute='_compute_hostel_allocation_count')

    def _compute_hostel_allocation_count(self):
        for student in self:
            student.hostel_allocation_count = len(student.hostel_allocation_ids)

    def action_view_hostel_allocations(self):
        self.ensure_one()
        return {
            'name': _('Hostel Allocations'),
            'type': 'ir.actions.act_window',
            'res_model': 'school.hostel.allocation',
            'view_mode': 'list,form,pivot,graph',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id},
        }
