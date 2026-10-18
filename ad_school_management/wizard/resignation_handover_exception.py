from odoo import models, fields, api, _
from odoo.exceptions import UserError

# Items a non-teaching employee normally does not have: a suggested reason is
# filled in for them (the verifier can change it).
TEACHING_ONLY_ITEMS = ('handover_student_register', 'handover_study_materials')


class SchoolResignationHandoverException(models.TransientModel):
    """Verify a handover where some checklist items were not handed over:
    one line per missing item, each with its OWN reason."""
    _name = 'school.resignation.handover.exception'
    _description = 'Verify Handover with Items Not Handed Over'

    resignation_id = fields.Many2one('school.staff.resignation', string='Resignation',
                                     required=True, readonly=True)
    employee_id = fields.Many2one(related='resignation_id.employee_id', string='Employee')
    is_teaching_staff = fields.Boolean(related='resignation_id.is_teaching_staff')
    line_ids = fields.One2many('school.resignation.handover.exception.line', 'wizard_id',
                               string='Items Not Handed Over')

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        resignation = self.env['school.staff.resignation'].browse(values.get('resignation_id'))
        if resignation and 'line_ids' in fields_list:
            non_teaching = not resignation.is_teaching_staff
            values['line_ids'] = [(0, 0, {
                'item_field': fname,
                'item_label': label,
                'reason': _("Non-teaching staff: not applicable")
                if non_teaching and fname in TEACHING_ONLY_ITEMS else False,
            }) for fname, _rname, label in resignation._handover_pending()]
        return values

    def action_confirm(self):
        self.ensure_one()
        missing = self.line_ids.filtered(lambda l: not (l.reason or '').strip())
        if missing:
            raise UserError(_("Give a reason for: %s", ", ".join(missing.mapped('item_label'))))
        self.resignation_id._mark_handover_verified(
            {line.item_field: line.reason for line in self.line_ids})
        return {'type': 'ir.actions.act_window_close'}


class SchoolResignationHandoverExceptionLine(models.TransientModel):
    _name = 'school.resignation.handover.exception.line'
    _description = 'Item Not Handed Over'

    wizard_id = fields.Many2one('school.resignation.handover.exception', required=True, ondelete='cascade')
    item_field = fields.Char(required=True)
    item_label = fields.Char(string='Item', readonly=True)
    # Required in the dialog (view) and checked in action_confirm; not a
    # database constraint, so the rows can be shown empty for the user to fill.
    reason = fields.Char(string='Reason')