from odoo import api, fields, models, _


class SchoolStudent(models.Model):
    """Student -> Graduate: a student can be graduated into the alumni network."""
    _inherit = 'school.student'

    alumni_ids = fields.One2many('school.alumni', 'student_id', string='Alumni Profile')
    alumni_id = fields.Many2one('school.alumni', string='Alumni', compute='_compute_alumni_id')
    mentorship_ids = fields.One2many('school.alumni.mentorship', 'student_id', string='Mentorships')
    mentorship_count = fields.Integer(compute='_compute_alumni_id')

    @api.depends('alumni_ids', 'mentorship_ids')
    def _compute_alumni_id(self):
        for student in self:
            student.alumni_id = student.alumni_ids[:1]
            student.mentorship_count = len(student.mentorship_ids)

    def action_graduate(self):
        """Open the Graduate Students wizard for the selected students."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Graduate Students'),
            'res_model': 'school.alumni.graduate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_student_ids': [(6, 0, self.ids)]},
        }

    def action_view_alumni(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'school.alumni',
            'res_id': self.alumni_id.id,
            'view_mode': 'form',
        }

    def action_view_mentorships(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Mentorships'),
            'res_model': 'school.alumni.mentorship',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id},
        }