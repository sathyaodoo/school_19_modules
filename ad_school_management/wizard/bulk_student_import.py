from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SchoolBulkStudentImport(models.TransientModel):
    _name = 'school.bulk.student.import'
    _description = 'Bulk Student Import'

    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', required=True)
    class_id = fields.Many2one('school.class', string='Class', required=True)
    section_id = fields.Many2one('school.section', string='Section', required=True)
    line_ids = fields.One2many('school.bulk.student.import.line', 'wizard_id', string='Students')

    def action_import(self):
        for rec in self:
            for line in rec.line_ids:
                partner = self.env['res.partner'].create({
                    'name': line.name,
                    'email': line.email,
                    'phone': line.phone,
                    'is_student': True,
                    'student_status': 'enrolled',
                })
                self.env['school.student'].create({
                    'partner_id': partner.id,
                    'class_id': rec.class_id.id,
                    'section_id': rec.section_id.id,
                    'academic_year_id': rec.academic_year_id.id,
                    'roll_number': line.roll_number,
                })
        return {'type': 'ir.actions.act_window_close'}

class SchoolBulkStudentImportLine(models.TransientModel):
    _name = 'school.bulk.student.import.line'
    _description = 'Bulk Student Import Line'

    wizard_id = fields.Many2one('school.bulk.student.import', string='Wizard')
    name = fields.Char(string='Name', required=True)
    email = fields.Char(string='Email')
    phone = fields.Char(string='Phone')
    roll_number = fields.Char(string='Roll Number')
