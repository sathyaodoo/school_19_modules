from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SchoolGrade(models.Model):
    _name = 'school.grade'
    _description = 'Grading System'
    _order = 'grade_point desc'

    grade = fields.Char(string='Grade', required=True)
    min_mark = fields.Float(string='Min Percentage', required=True)
    max_mark = fields.Float(string='Max Percentage', required=True)
    grade_point = fields.Float(string='Grade Point (GPA)', required=True)

    _grade_uniq = models.Constraint(
        'unique(grade)', 'Grade name must be unique!'
    )

    @api.constrains('min_mark', 'max_mark', 'grade_point')
    def _check_marks(self):
        for record in self:
            if record.min_mark >= record.max_mark:
                raise ValidationError(_("Minimum percentage must be less than maximum percentage!"))
            if record.min_mark < 0 or record.max_mark > 100:
                raise ValidationError(_("Percentages must be between 0 and 100."))
            if record.grade_point < 0:
                raise ValidationError(_("Grade Point cannot be negative."))
