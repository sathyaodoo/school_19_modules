# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class SchoolClassRoom(models.Model):
    _name = 'school.class.room'
    _description = 'Classroom'
    _order = 'name'

    name = fields.Char(string='Room Name', required=True, help='e.g. Room 101')
    code = fields.Char(string='Code')
    floor = fields.Integer(string='Floor')
    capacity = fields.Integer(string='Capacity')
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint('UNIQUE(name)', 'Classroom name must be unique!')
