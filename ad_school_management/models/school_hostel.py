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
            if not 1 <= room.capacity:
                raise ValidationError(_("Room capacity must be at least 1"))
            if room.rent < 0:
                raise ValidationError(_("Room rent cannot be negative."))

    @api.depends('capacity', 'allocation_ids.state', 'allocation_ids.room_id')
    def _compute_availability(self):
        for room in self:
            allocated = self.env['school.hostel.allocation'].search_count([
                ('room_id', '=', room.id),
                ('state', '=', 'allocated')
            ])
            room.availability = max(room.capacity - allocated, 0)

    @api.depends('capacity', 'allocation_ids.state', 'allocation_ids.room_id')
    def _compute_occupied_beds(self):
        for room in self:
            room.occupied_beds = self.env['school.hostel.allocation'].search_count([
                ('room_id', '=', room.id), ('state', '=', 'allocated')
            ])

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

    vacate_reason = fields.Text(string='Vacate Reason', tracking=True)
    student_gender = fields.Selection(related='student_id.gender', readonly=True)

    @api.onchange('student_id')
    def _onchange_student_id(self):
        self.room_id = False

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_start > rec.date_end:
                raise ValidationError(_("Vacated date must be after start date!"))

    def _check_allocation_allowed(self):
        """Serialize allocations per room and check room/student compatibility."""
        for rec in self:
            if not rec.room_id or not rec.student_id:
                continue
            # PostgreSQL row lock prevents two users taking the last bed together.
            self.env.cr.execute(
                'SELECT id FROM school_hostel_room WHERE id = %s FOR UPDATE',
                [rec.room_id.id],
            )
            desired = {'male': 'boys', 'female': 'girls'}.get(rec.student_id.gender)
            if not desired or rec.room_id.hostel_id.type != desired:
                raise ValidationError(_('Student gender does not match hostel type.'))
            if self.search_count([
                ('student_id', '=', rec.student_id.id),
                ('state', '=', 'allocated'),
                ('id', '!=', rec.id),
            ]):
                raise ValidationError(_('Student already has an active hostel allocation.'))
            occupied = self.search_count([
                ('room_id', '=', rec.room_id.id),
                ('state', '=', 'allocated'),
                ('id', '!=', rec.id),
            ])
            if occupied >= rec.room_id.capacity:
                raise ValidationError(_('Room %s is full.') % rec.room_id.name)

    @api.model_create_multi
    def create(self, vals_list):
        # Validate allocated creates before insertion, including student-facilities flow.
        for vals in vals_list:
            if vals.get('state') == 'allocated':
                room = self.env['school.hostel.room'].browse(vals['room_id'])
                student = self.env['school.student'].browse(vals['student_id'])
                self.env.cr.execute(
                    'SELECT id FROM school_hostel_room WHERE id = %s FOR UPDATE', [room.id]
                )
                if room.hostel_id.type != {'male': 'boys', 'female': 'girls'}.get(student.gender):
                    raise ValidationError(_('Student gender does not match hostel type.'))
                if self.search_count([('student_id', '=', student.id), ('state', '=', 'allocated')]):
                    raise ValidationError(_('Student already has an active hostel allocation.'))
                if self.search_count([('room_id', '=', room.id), ('state', '=', 'allocated')]) >= (room.capacity):
                    raise ValidationError(_('Room %s is full.') % room.name)
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('state') == 'allocated' or (
            ('student_id' in vals or 'room_id' in vals) and
            any(rec.state == 'allocated' for rec in self)
        ):
            # First update in-memory for validation? Validate each target explicitly using new().
            for rec in self:
                room = self.env['school.hostel.room'].browse(vals.get('room_id', rec.room_id.id))
                student = self.env['school.student'].browse(vals.get('student_id', rec.student_id.id))
                self.env.cr.execute(
                    'SELECT id FROM school_hostel_room WHERE id = %s FOR UPDATE', [room.id]
                )
                if room.hostel_id.type != {'male': 'boys', 'female': 'girls'}.get(student.gender):
                    raise ValidationError(_('Student gender does not match hostel type.'))
                if self.search_count([('student_id', '=', student.id), ('state', '=', 'allocated'), ('id', '!=', rec.id)]):
                    raise ValidationError(_('Student already has an active hostel allocation.'))
                if self.search_count([('room_id', '=', room.id), ('state', '=', 'allocated'), ('id', '!=', rec.id)]) >= (room.capacity):
                    raise ValidationError(_('Room %s is full.') % room.name)
        return super().write(vals)

    def action_allocate(self):
        for rec in self:
            if rec.state != 'draft':
                continue
            rec.write({'state': 'allocated'})
            rec.student_id.with_context(skip_hostel_sync=True).write({
                'hostel_room_id': rec.room_id.id
            })

    def action_vacate(self):
        for rec in self:
            if rec.state != 'allocated':
                continue
            if not rec.vacate_reason:
                raise ValidationError(_('Please enter Vacate Reason before vacating.'))
            rec.write({
                'date_end': fields.Date.context_today(rec),
                'state': 'vacated',
            })
            if rec.student_id.hostel_room_id == rec.room_id:
                rec.student_id.with_context(skip_hostel_sync=True).write({
                    'hostel_room_id': False
                })

class SchoolStudent(models.Model):
    _inherit = 'school.student'

    hostel_room_id = fields.Many2one('school.hostel.room', string='Hostel Room')
    hostel_allocation_ids = fields.One2many('school.hostel.allocation', 'student_id', string='Hostel Allocations')
    hostel_allocation_count = fields.Integer(string='Hostel Allocations Count', compute='_compute_hostel_allocation_count')

    student_gender = fields.Selection(related='gender', readonly=True)

    def _sync_hostel_allocation(self):
        Allocation = self.env['school.hostel.allocation']
        for student in self:
            active = Allocation.search([
                ('student_id', '=', student.id), ('state', '=', 'allocated')
            ])
            room = student.hostel_room_id
            if room and len(active) == 1 and active.room_id == room:
                continue
            if room:
                # Lock and validate availability before vacating the old room.
                self.env.cr.execute(
                    'SELECT id FROM school_hostel_room WHERE id = %s FOR UPDATE', [room.id]
                )
                expected = {'male': 'boys', 'female': 'girls'}.get(student.gender)
                if room.hostel_id.type != expected:
                    raise ValidationError(_('Student gender does not match hostel type.'))
                if Allocation.search_count([
                    ('room_id', '=', room.id), ('state', '=', 'allocated'),
                    ('student_id', '!=', student.id)
                ]) >= (room.capacity):
                    raise ValidationError(_('Room %s is full.') % room.name)
            if active:
                active.write({
                    'state': 'vacated',
                    'date_end': fields.Date.context_today(student),
                    'vacate_reason': 'Room changed from Student Facilities' if room else 'Cleared from Student Facilities',
                })
            if room:
                Allocation.create({
                    'student_id': student.id,
                    'room_id': room.id,
                    'date_start': fields.Date.context_today(student),
                    'state': 'allocated',
                })

    @api.model_create_multi
    def create(self, vals_list):
        students = super().create(vals_list)
        if not self.env.context.get('skip_hostel_sync'):
            students.filtered('hostel_room_id')._sync_hostel_allocation()
        return students

    def write(self, vals):
        result = super().write(vals)
        if 'hostel_room_id' in vals and not self.env.context.get('skip_hostel_sync'):
            self._sync_hostel_allocation()
        return result

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