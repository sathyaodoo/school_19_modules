from odoo import models, fields, api

class SchoolTeacher(models.Model):
    _name = 'school.teacher'
    _description = 'Teacher'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _inherits = {'hr.employee': 'employee_id'}

    employee_id = fields.Many2one('hr.employee', string='Employee Profile', required=True, ondelete='cascade')
    
    class_ids = fields.Many2many('school.class', 'school_class_teacher_rel', 'teacher_id', 'class_id', string='Assigned Classes')
    subject_ids = fields.Many2many('school.subject', 'school_subject_teacher_rel', 'teacher_id', 'subject_id', string='Assigned Subjects')
    class_teacher_class_ids = fields.One2many('school.class', 'class_teacher_id', string='Class Teacher For')
    class_teacher_section_ids = fields.One2many('school.section', 'class_teacher_id', string='Class Teacher Sections')
    class_teacher_for_text = fields.Char(string='Class Teacher For', compute='_compute_class_teacher_for_text')

    @api.depends('class_teacher_section_ids.name', 'class_teacher_section_ids.class_id.name')
    def _compute_class_teacher_for_text(self):
        for teacher in self:
            teacher.class_teacher_for_text = ', '.join(
                '%s - %s' % (sec.class_id.name, sec.name) for sec in teacher.class_teacher_section_ids)

    @api.model_create_multi
    def create(self, vals_list):
        records = super(SchoolTeacher, self).create(vals_list)
        for record in records:
            record.employee_id.write({'teacher_id': record.id})
        return records
    
    def write(self, vals):
        res = super().write(vals)
        if 'subject_ids' in vals:
            self.subject_ids._sync_teacher_classes()
        return res
