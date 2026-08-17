# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class SchoolClass(models.Model):
    _name = 'school.class'
    _description = 'School Class'
    _order = 'name'

    name = fields.Char(string='Class Name', required=True, help='e.g. Grade 1')
    code = fields.Char(string='Code')
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year')
    teacher_id = fields.Many2one('school.teacher', string='Class Teacher')
    room_id = fields.Many2one('school.class.room', string='Classroom')
    subject_ids = fields.Many2many(
        'school.subject',
        'school_class_subject_rel',
        'class_id',
        'subject_id',
        string='Subjects',
    )
    student_ids = fields.One2many('school.student', 'class_id', string='Students')
    student_count = fields.Integer(
        string='Student Count',
        compute='_compute_student_count',
        store=True,
    )
    capacity = fields.Integer(string='Capacity')
    active = fields.Boolean(default=True)

    @api.depends('student_ids')
    def _compute_student_count(self):
        for record in self:
            record.student_count = len(record.student_ids)
