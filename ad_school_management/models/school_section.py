from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SchoolSection(models.Model):
    _name = 'school.section'
    _description = 'Section'
    _order = 'name'

    class_id = fields.Many2one('school.class', string='Class', required=True, ondelete='cascade')
    name = fields.Char(string='Section Name', required=True)
    capacity = fields.Integer(string='Capacity', default=30, required=True)

    @api.constrains('capacity')
    def _check_capacity(self):
        for section in self:
            if section.capacity <= 0:
                raise ValidationError(_("Section capacity must be greater than zero!"))

    _class_section_uniq = models.Constraint(
        'unique(class_id, name)', 'The section name must be unique within the class!'
    )
