from odoo import models, fields, api

class SchoolClass(models.Model):
    _name = 'school.class'
    _description = 'Class'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name'

    name = fields.Char(string='Class Name', required=True, tracking=True)
    code = fields.Char(string='Code', required=True, tracking=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)
    
    class_teacher_id = fields.Many2one('school.teacher', string='Class Teacher', tracking=True)
    teacher_ids = fields.Many2many('school.teacher', 'school_class_teacher_rel', 'class_id', 'teacher_id', string='Assigned Teachers')
    section_ids = fields.One2many('school.section', 'class_id', string='Sections')

    _code_uniq = models.Constraint(
        'unique(code)', 'The class code must be unique!'
    )
