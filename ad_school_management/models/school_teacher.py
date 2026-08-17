from odoo import models, fields, api

class SchoolTeacher(models.Model):
    _name = 'school.teacher'
    _description = 'Teacher'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _inherits = {'hr.employee': 'employee_id'}

    employee_id = fields.Many2one('hr.employee', string='Employee Profile', required=True, ondelete='cascade')
    
    class_ids = fields.Many2many('school.class', 'school_class_teacher_rel', 'teacher_id', 'class_id', string='Assigned Classes')
    subject_ids = fields.Many2many('school.subject', 'school_subject_teacher_rel', 'teacher_id', 'subject_id', string='Assigned Subjects')

    @api.model_create_multi
    def create(self, vals_list):
        records = super(SchoolTeacher, self).create(vals_list)
        for record in records:
            record.employee_id.write({'teacher_id': record.id})
        return records
