from odoo import models, fields

class SchoolBloodGroup(models.Model):
    _name = 'school.blood.group'
    _description = 'School Blood Group'
    _order = 'name'

    name = fields.Char(string='Blood Group', required=True)

    _name_unique = models.Constraint(
        'unique(name)',
        'Blood Group already exists!'
    )