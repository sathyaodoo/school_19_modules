from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SchoolAlumniGraduateWizard(models.TransientModel):
    """Student -> Graduate.

    Creates an alumni profile (stage Graduate) for each selected student and
    sets the student's status to Alumni. The student keeps the same contact,
    so name, photo, e-mail, phone and address carry over.
    """
    _name = 'school.alumni.graduate.wizard'
    _description = 'Graduate Students'

    class_id = fields.Many2one('school.class', string='Class')
    section_id = fields.Many2one('school.section', string='Section',
                                 domain="[('class_id', '=', class_id)]")
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year')
    graduation_year = fields.Integer(string='Graduation Year', required=True,
                                     default=lambda self: fields.Date.context_today(self).year)
    graduation_date = fields.Date(string='Graduation Date', default=fields.Date.context_today)
    student_ids = fields.Many2many('school.student', string='Students',
                                   domain="[('student_status', '!=', 'alumni')]")

    @api.onchange('class_id', 'section_id')
    def _onchange_class(self):
        if self.class_id:
            domain = [('class_id', '=', self.class_id.id), ('student_status', '!=', 'alumni')]
            if self.section_id:
                domain.append(('section_id', '=', self.section_id.id))
            self.student_ids = self.env['school.student'].search(domain)

    def action_graduate(self):
        self.ensure_one()
        students = self.student_ids
        if not students:
            raise UserError(_("Select at least one student to graduate."))
        Alumni = self.env['school.alumni']
        existing = Alumni.with_context(active_test=False).search([('student_id', 'in', students.ids)])
        done = {a.student_id.id for a in existing}
        vals_list = []
        for student in students.filtered(lambda s: s.id not in done):
            vals_list.append({
                'partner_id': student.partner_id.id,
                'student_id': student.id,
                'admission_no': student.admission_no,
                'last_class_id': student.class_id.id,
                'last_section_id': student.section_id.id,
                'graduation_academic_year_id': (self.academic_year_id or student.academic_year_id).id,
                'graduation_year': self.graduation_year,
                'graduation_date': self.graduation_date,
                'stage': 'graduate',
            })
        alumni = Alumni.create(vals_list) if vals_list else Alumni
        students.write({'student_status': 'alumni'})
        for student in students:
            student.message_post(body=_("Graduated in %s and added to the alumni network.",
                                        self.graduation_year))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Graduated Alumni'),
            'res_model': 'school.alumni',
            'view_mode': 'list,kanban,form',
            'domain': [('id', 'in', (alumni | existing).ids)],
        }