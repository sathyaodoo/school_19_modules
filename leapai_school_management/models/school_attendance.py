# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class SchoolAttendance(models.Model):
    _name = 'school.attendance'
    _description = 'Student Attendance'
    _order = 'date desc'

    student_id = fields.Many2one('school.student', string='Student', required=True)
    class_id = fields.Many2one(
        'school.class',
        string='Class',
        related='student_id.class_id',
        store=True,
    )
    date = fields.Date(string='Date', default=fields.Date.today, required=True)
    state = fields.Selection([
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
        ('excused', 'Excused'),
    ], string='Status', default='present', required=True)
    note = fields.Char(string='Note')

    _student_date_uniq = models.Constraint('UNIQUE(student_id, date)', 'Attendance record for this student on this date already exists!')
