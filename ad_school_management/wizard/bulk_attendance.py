from odoo import models, fields, api, _
from odoo.exceptions import UserError

from ..models.school_attendance import STATUSES


class SchoolBulkAttendance(models.TransientModel):
    _name = 'school.bulk.attendance'
    _description = 'Bulk Attendance Wizard'

    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    session = fields.Selection(
        [('morning', 'Morning'), ('afternoon', 'Afternoon'), ('both', 'Both Sessions (Full Day)')],
        string='Session', required=True,
        default=lambda self: self.env['school.attendance']._default_session_now(),
        help='Morning or Afternoon marks that session only. '
             'Both Sessions saves the same status for the whole day.')
    class_id = fields.Many2one('school.class', string='Class', required=True)
    section_id = fields.Many2one('school.section', string='Section', required=True)
    line_ids = fields.One2many('school.bulk.attendance.line', 'wizard_id', string='Attendance Lines')

    def _target_sessions(self):
        self.ensure_one()
        return ['morning', 'afternoon'] if self.session == 'both' else [self.session]

    @api.onchange('class_id', 'section_id', 'date', 'session')
    def _onchange_class_section(self):
        if self.class_id and self.section_id and self.session:
            self.line_ids = [(5, 0, 0)]
            students = self.env['school.student'].search([
                ('class_id', '=', self.class_id.id),
                ('section_id', '=', self.section_id.id)
            ])
            # Status already saved for this date: the chosen session, or for
            # "Both Sessions" the morning status (afternoon if no morning).
            existing = self.env['school.attendance'].search([
                ('student_id', 'in', students.ids),
                ('date', '=', self.date),
                ('session', 'in', self._target_sessions()),
            ], order='session')  # 'afternoon' first, then 'morning' overwrites -> morning wins
            saved = {rec.student_id.id: rec.status for rec in existing}
            self.line_ids = [(0, 0, {
                'student_id': student.id,
                'status': saved.get(student.id, 'present'),
            }) for student in students]

    def action_save_attendance(self):
        errors = []
        saved = 0
        Attendance = self.env['school.attendance']
        for rec in self:
            if not rec.line_ids:
                raise UserError(_(
                    "There is no attendance to save. Select the Class, Section, Date and "
                    "Session so the student list is loaded, then set each student's status."
                ))
            # The status chosen for each student on the sheet.
            sent_status = {
                line.student_id.id: line.status
                for line in rec.line_ids if line.student_id
            }
            students = self.env['school.student'].search([
                ('class_id', '=', rec.class_id.id),
                ('section_id', '=', rec.section_id.id),
            ])
            for session in rec._target_sessions():
                for student in students:
                    status = sent_status.get(student.id)
                    try:
                        # A savepoint isolates this one record: if it fails,
                        # everyone else in the batch is still saved.
                        with self.env.cr.savepoint():
                            existing = Attendance.search([
                                ('student_id', '=', student.id),
                                ('date', '=', rec.date),
                                ('session', '=', session),
                            ], limit=1)
                            if status is None:
                                # Student not on the sheet (e.g. enrolled after it
                                # was opened): never overwrite an existing record;
                                # only create a default "Present" one.
                                if existing:
                                    continue
                                status_to_save = 'present'
                            else:
                                status_to_save = status
                            if existing:
                                if existing.status != status_to_save:
                                    existing.write({'status': status_to_save})
                            else:
                                Attendance.create({
                                    'student_id': student.id,
                                    'class_id': rec.class_id.id,
                                    'section_id': rec.section_id.id,
                                    'date': rec.date,
                                    'session': session,
                                    'status': status_to_save,
                                })
                        saved += 1
                    except Exception as e:
                        errors.append(_("%(student)s (%(session)s): %(error)s",
                                        student=student.name, session=session, error=str(e)))

        if errors:
            raise UserError(_(
                "%(saved)s attendance record(s) were saved, but the following could not be:\n\n%(errors)s",
                saved=saved, errors="\n".join(errors),
            ))
        session_label = dict(self._fields['session'].selection).get(self[:1].session, '')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Attendance saved"),
                'message': _("%(count)s attendance record(s) saved (%(session)s).",
                             count=saved, session=session_label),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class SchoolBulkAttendanceLine(models.TransientModel):
    _name = 'school.bulk.attendance.line'
    _description = 'Bulk Attendance Line'

    wizard_id = fields.Many2one('school.bulk.attendance', string='Wizard')
    student_id = fields.Many2one('school.student', string='Student', required=True, readonly=True)
    status = fields.Selection(STATUSES, string='Status', required=True, default='present')

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [vals for vals in vals_list if vals.get('student_id')]
        if not vals_list:
            return self.browse()
        return super().create(vals_list)