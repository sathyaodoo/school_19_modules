from odoo import fields, models


class SchoolAlumniExpertise(models.Model):
    """Areas an alumni mentor can guide students in (e.g. Engineering, Medicine)."""
    _name = 'school.alumni.expertise'
    _description = 'Alumni Expertise Area'
    _order = 'name'

    name = fields.Char(string='Expertise', required=True, translate=True)
    color = fields.Integer(string='Color')
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint('unique(name)', 'This expertise area already exists!')


class SchoolAlumniIndustry(models.Model):
    """Industry / field of work of an alumni (e.g. IT, Healthcare, Education)."""
    _name = 'school.alumni.industry'
    _description = 'Alumni Industry'
    _order = 'name'

    name = fields.Char(string='Industry', required=True, translate=True)
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint('unique(name)', 'This industry already exists!')