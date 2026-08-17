from odoo import models, fields, api

class SchoolParent(models.Model):
    _name = 'school.parent'
    _description = 'Parent/Guardian'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _inherits = {'res.partner': 'partner_id'}

    partner_id = fields.Many2one('res.partner', string='Partner', required=True, ondelete='cascade')
    relation = fields.Selection([
        ('father', 'Father'),
        ('mother', 'Mother'),
        ('guardian', 'Guardian')
    ], string='Relation', required=True, default='father', tracking=True)
    occupation = fields.Char(string='Occupation', tracking=True)
    annual_income = fields.Float(string='Annual Income', tracking=True)
    student_ids = fields.Many2many('school.student', 'school_student_parent_rel', 'parent_id', 'student_id', string='Children')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['is_parent'] = True
        return super(SchoolParent, self).create(vals_list)

    def action_view_partner(self):
        self.ensure_one()
        return {
            'name': _('Contact Details'),
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': self.partner_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
