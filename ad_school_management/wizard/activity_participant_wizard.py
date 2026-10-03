from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SchoolActivityParticipantWizard(models.TransientModel):
    """Add many students to a school activity at once (by class, section,
    group or gender), e.g. a whole group for a group-based event."""
    _name = 'school.activity.participant.wizard'
    _description = 'Add Activity Participants'

    event_id = fields.Many2one('event.event', string='Activity', required=True,
                               domain=[('is_school_activity', '=', True)])
    class_id = fields.Many2one('school.class', string='Class')
    section_id = fields.Many2one('school.section', string='Section')
    house_id = fields.Many2one('school.house', string='Group (House)')
    gender = fields.Selection([('male', 'Male'), ('female', 'Female')], string='Gender')
    student_ids = fields.Many2many('school.student', string='Students',
                                   help='Leave empty to add every student matching the filters.')

    @api.onchange('class_id')
    def _onchange_class_id(self):
        if self.section_id and self.section_id.class_id != self.class_id:
            self.section_id = False
        if self.house_id and self.class_id.board and self.house_id.board != self.class_id.board:
            self.house_id = False

    def _get_students(self):
        self.ensure_one()
        if self.student_ids:
            return self.student_ids
        domain = []
        if self.class_id:
            domain.append(('class_id', '=', self.class_id.id))
        if self.section_id:
            domain.append(('section_id', '=', self.section_id.id))
        if self.house_id:
            domain.append(('house_id', '=', self.house_id.id))
        if self.gender:
            domain.append(('gender', '=', self.gender))
        if not domain:
            raise UserError(_("Select students, or at least one filter (class, section, group or gender)."))
        return self.env['school.student'].search(domain)

    def action_add(self):
        self.ensure_one()
        students = self._get_students()
        already = self.event_id.registration_ids.student_id
        new_students = students - already
        if not new_students:
            raise UserError(_("No new students to add: they are all already participants."))
        self.env['event.registration'].create([
            {'event_id': self.event_id.id, 'student_id': s.id} for s in new_students
        ])
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Participants added"),
                'message': _("%(added)s student(s) added to %(event)s.",
                             added=len(new_students), event=self.event_id.name),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }