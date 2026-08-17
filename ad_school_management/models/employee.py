from odoo import models, fields

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    teacher_code = fields.Char(string='Teacher Code')
    qualification = fields.Char(string='Qualification')
    specialization = fields.Char(string='Specialization')
    joining_date = fields.Date(string='Joining Date')
    class_teacher_for = fields.Many2one('school.class', string='Class Teacher For')
    teacher_id = fields.Many2one('school.teacher', string='Teacher Profile')
