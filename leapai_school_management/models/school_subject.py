# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class SchoolSubject(models.Model):
    _name = 'school.subject'
    _description = 'School Subject'
    _order = 'name'

    name = fields.Char(string='Subject Name', required=True)
    code = fields.Char(string='Code')
    teacher_id = fields.Many2one('school.teacher', string='Primary Teacher')
    class_ids = fields.Many2many(
        'school.class',
        'school_class_subject_rel',
        'subject_id',
        'class_id',
        string='Classes',
    )
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint('UNIQUE(name)', 'Subject name must be unique!')
