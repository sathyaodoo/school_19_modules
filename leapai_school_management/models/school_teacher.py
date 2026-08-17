# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class SchoolTeacher(models.Model):
    _name = 'school.teacher'
    _description = 'School Teacher'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Teacher Name', required=True, tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee')
    code = fields.Char(string='Code', readonly=True, copy=False, default='New')
    subject_ids = fields.Many2many(
        'school.subject',
        'school_teacher_subject_rel',
        'teacher_id',
        'subject_id',
        string='Subjects',
    )
    class_ids = fields.One2many('school.class', 'teacher_id', string='Classes')
    qualification = fields.Char(string='Qualification')
    experience_years = fields.Integer(string='Experience (Years)')
    phone = fields.Char(string='Phone')
    email = fields.Char(string='Email')
    image = fields.Binary(string='Photo')
    active = fields.Boolean(default=True)
    student_count = fields.Integer(
        string='Total Students',
        compute='_compute_student_count',
        store=False,
    )

    @api.depends('class_ids', 'class_ids.student_ids')
    def _compute_student_count(self):
        for record in self:
            students = self.env['school.student']
            for cls in record.class_ids:
                students |= cls.student_ids
            record.student_count = len(students)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', 'New') == 'New':
                vals['code'] = self.env['ir.sequence'].next_by_code('school.teacher') or 'New'
        return super().create(vals_list)

    def action_view_classes(self):
        return {
            'name': _('Classes'),
            'type': 'ir.actions.act_window',
            'res_model': 'school.class',
            'view_mode': 'list,form',
            'domain': [('teacher_id', '=', self.id)],
        }

    def action_view_students(self):
        student_ids = []
        for cls in self.class_ids:
            student_ids.extend(cls.student_ids.ids)
        return {
            'name': _('Students'),
            'type': 'ir.actions.act_window',
            'res_model': 'school.student',
            'view_mode': 'list,form',
            'domain': [('id', 'in', student_ids)],
        }
