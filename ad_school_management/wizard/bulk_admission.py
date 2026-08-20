from odoo import models, fields, api, _
from odoo.exceptions import UserError

class SchoolBulkAdmission(models.TransientModel):
    _name = 'school.bulk.admission'
    _description = 'Bulk Admission Wizard'

    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', required=True)
    class_id = fields.Many2one('school.class', string='Class', required=True)
    section_id = fields.Many2one('school.section', string='Section')
    line_ids = fields.One2many('school.bulk.admission.line', 'wizard_id', string='Applications')

    def action_register(self):
        errors = []
        for rec in self:
            for line in rec.line_ids:
                if not line.first_name or not line.last_name or not line.date_of_birth:
                    errors.append(_(
                        "Row for '%s %s' is missing required details (name/date of birth) and was skipped."
                    ) % (line.first_name or '', line.last_name or ''))
                    continue
                try:
                    # A savepoint isolates this one application: if it
                    # fails for any reason, only this row is rolled back -
                    # every other application in the batch still registers
                    # normally instead of the whole transaction aborting.
                    with self.env.cr.savepoint():
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
                except Exception as e:
                    errors.append(_("%s %s: %s") % (line.first_name, line.last_name, str(e)))

        if errors:
            raise UserError(_(
                "Some applications were registered, but the following could not be:\n\n%s"
            ) % "\n".join(errors))
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

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [
            vals for vals in vals_list
            if vals.get('first_name') and vals.get('last_name')
        ]
        if not vals_list:
            return self.browse()
        return super().create(vals_list)