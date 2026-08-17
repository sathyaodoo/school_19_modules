from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SchoolAcademicTerm(models.Model):
    _name = 'school.academic.term'
    _description = 'Academic Term'
    _order = 'start_date'

    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', required=True, ondelete='cascade')
    name = fields.Char(string='Term Name', required=True)
    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date', required=True)

    @api.constrains('start_date', 'end_date', 'academic_year_id')
    def _check_dates(self):
        for term in self:
            if term.start_date and term.end_date:
                if term.start_date >= term.end_date:
                    raise ValidationError(_("Term start date must be before the end date!"))
                
                year = term.academic_year_id
                if year:
                    if term.start_date < year.date_start or term.end_date > year.date_end:
                        raise ValidationError(_(
                            "Term dates must fall within the Academic Year dates: %s to %s"
                        ) % (year.date_start, year.date_end))
