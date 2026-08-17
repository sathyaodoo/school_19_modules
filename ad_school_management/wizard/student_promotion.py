from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SchoolStudentPromotion(models.TransientModel):
    _name = 'school.student.promotion'
    _description = 'Bulk Student Promotion Wizard'

    academic_year_from_id = fields.Many2one('school.academic.year', string='From Academic Year', required=True)
    academic_year_to_id = fields.Many2one('school.academic.year', string='To Academic Year', required=True)
    class_from_id = fields.Many2one('school.class', string='From Class', required=True)
    class_to_id = fields.Many2one('school.class', string='To Class', required=True)

    def action_bulk_promote(self):
        for rec in self:
            students = self.env['school.student'].search([
                ('class_id', '=', rec.class_from_id.id),
                ('academic_year_id', '=', rec.academic_year_from_id.id)
            ])
            if not students:
                raise ValidationError(_("No students found to promote for the selected Class and Academic Year."))
            
            promotion_run = self.env['school.promotion'].create({
                'academic_year_from_id': rec.academic_year_from_id.id,
                'academic_year_to_id': rec.academic_year_to_id.id,
                'class_from_id': rec.class_from_id.id,
                'class_to_id': rec.class_to_id.id,
                'student_ids': [(6, 0, students.ids)],
            })
            promotion_run.action_promote()
            
        return {'type': 'ir.actions.act_window_close'}
