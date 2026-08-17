from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SchoolPromotion(models.Model):
    _name = 'school.promotion'
    _description = 'Student Promotion'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Description', compute='_compute_name', store=True)
    academic_year_from_id = fields.Many2one('school.academic.year', string='From Academic Year', required=True, tracking=True)
    academic_year_to_id = fields.Many2one('school.academic.year', string='To Academic Year', required=True, tracking=True)
    class_from_id = fields.Many2one('school.class', string='From Class', required=True, tracking=True)
    class_to_id = fields.Many2one('school.class', string='To Class', required=True, tracking=True)
    
    student_ids = fields.Many2many('school.student', 'school_promotion_student_rel', 'promotion_id', 'student_id', string='Students to Promote')
    ignore_unpaid_fees = fields.Boolean(string='Ignore Unpaid Fees', default=False, tracking=True, help="Allow promoting students who have unpaid or uninvoiced fees for the current academic year.")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done')
    ], string='Status', default='draft', required=True, tracking=True)

    @api.depends('class_from_id', 'class_to_id', 'academic_year_from_id', 'academic_year_to_id')
    def _compute_name(self):
        for rec in self:
            if rec.class_from_id and rec.class_to_id:
                rec.name = f"Promote: {rec.class_from_id.name} -> {rec.class_to_id.name}"
            else:
                rec.name = "New Promotion"

    @api.constrains('academic_year_from_id', 'academic_year_to_id', 'class_from_id', 'class_to_id')
    def _check_promotion_rules(self):
        for rec in self:
            if rec.academic_year_from_id == rec.academic_year_to_id:
                raise ValidationError(_("From and To Academic Years must be different!"))
            if rec.class_from_id == rec.class_to_id:
                raise ValidationError(_("From and To Classes must be different!"))

    def action_promote(self):
        for rec in self:
            if not rec.student_ids:
                raise ValidationError(_("Please select at least one student to promote."))
            
            if not rec.ignore_unpaid_fees:
                for student in rec.student_ids:
                    unpaid_fees = self.env['school.student.fee'].search([
                        ('student_id', '=', student.id),
                        ('academic_year_id', '=', rec.academic_year_from_id.id),
                        ('state', 'in', ('draft', 'invoiced'))
                    ])
                    if unpaid_fees:
                        raise ValidationError(_(
                            "Student %s has unpaid or pending fees for academic year %s. "
                            "Please clear their outstanding balance or select 'Ignore Unpaid Fees' to bypass."
                        ) % (student.name, rec.academic_year_from_id.name))

            for student in rec.student_ids:
                student.message_post(body=_(
                    "Promoted from %s (%s) to %s (%s) via promotion plan %s."
                ) % (
                    student.class_id.name, student.academic_year_id.name,
                    rec.class_to_id.name, rec.academic_year_to_id.name, rec.name
                ))
                student.write({
                    'class_id': rec.class_to_id.id,
                    'academic_year_id': rec.academic_year_to_id.id,
                    'roll_number': False,
                })
            rec.write({'state': 'done'})
