# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class SchoolFeeStructure(models.Model):
    _name = 'school.fee.structure'
    _description = 'Fee Structure'
    _order = 'name'

    name = fields.Char(string='Fee Name', required=True)
    class_id = fields.Many2one('school.class', string='Class')
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year')
    fee_type = fields.Selection([
        ('tuition', 'Tuition Fee'),
        ('transport', 'Transport Fee'),
        ('hostel', 'Hostel Fee'),
        ('exam', 'Exam Fee'),
        ('library', 'Library Fee'),
        ('other', 'Other'),
    ], string='Fee Type', default='tuition')
    amount = fields.Monetary(string='Amount', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    due_date = fields.Date(string='Due Date')
    active = fields.Boolean(default=True)
