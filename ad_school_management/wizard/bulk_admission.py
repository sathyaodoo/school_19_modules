from odoo import models, fields, api, _

class SchoolBulkAdmission(models.TransientModel):
    _name = 'school.bulk.admission'
    _description = 'Bulk Admission Wizard'

    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', required=True)
    class_id = fields.Many2one('school.class', string='Class', required=True)
    section_id = fields.Many2one('school.section', string='Section')
    line_ids = fields.One2many('school.bulk.admission.line', 'wizard_id', string='Applications')

    def action_register(self):
        for rec in self:
            for line in rec.line_ids:
                self.env['school.admission'].create({
                    'first_name': line.first_name,
                    'last_name': line.last_name,
                    'date_of_birth': line.date_of_birth,
                    'gender': line.gender,
                    'academic_year_id': rec.academic_year_id.id,
                    'class_id': rec.class_id.id,
                    'section_id': rec.section_id.id if rec.section_id else False,
                    'parent_name': line.parent_name,
                    'state': 'submitted',
                })
        return {'type': 'ir.actions.act_window_close'}

class SchoolBulkAdmissionLine(models.TransientModel):
    _name = 'school.bulk.admission.line'
    _description = 'Bulk Admission Line'

    wizard_id = fields.Many2one('school.bulk.admission', string='Wizard')
    first_name = fields.Char(string='First Name', required=True)
    last_name = fields.Char(string='Last Name', required=True)
    date_of_birth = fields.Date(string='Date of Birth', required=True)
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other')
    ], string='Gender', required=True, default='male')
    parent_name = fields.Char(string='Parent Name')
