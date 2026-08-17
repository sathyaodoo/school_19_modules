from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SchoolSubject(models.Model):
    _name = 'school.subject'
    _description = 'Subject'
    _order = 'name'

    name = fields.Char(string='Subject Name', required=True)
    code = fields.Char(string='Code', required=True)
    class_ids = fields.Many2many('school.class', 'school_subject_class_rel', 'subject_id', 'class_id', string='Classes')
    teacher_ids = fields.Many2many('school.teacher', 'school_subject_teacher_rel', 'subject_id', 'teacher_id', string='Teachers')
    credits = fields.Float(string='Credits', default=1.0)

    _code_uniq = models.Constraint(
        'unique(code)', 'The subject code must be unique!'
    )

    @api.constrains('credits')
    def _check_credits(self):
        for subject in self:
            if subject.credits <= 0:
                raise ValidationError(_("Subject credits must be greater than zero!"))
