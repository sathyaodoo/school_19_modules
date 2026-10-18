from odoo import models, fields, api, _
from odoo.exceptions import UserError

from ..models.school_attendance import STATUSES


class SchoolBulkAttendance(models.TransientModel):
    """Mark the day's attendance (taken once, in the morning) for a whole
    class / section: every student is Present or Absent."""
    _name = 'school.bulk.attendance'
    _description = 'Bulk Attendance Wizard'

    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    class_id = fields.Many2one('school.class', string='Class', required=True)
    section_id = fields.Many2one('school.section', string='Section', required=True)
    line_ids = fields.One2many('school.bulk.attendance.line', 'wizard_id', string='Attendance Lines')
    present_count = fields.Integer(string='Present', compute='_compute_counts')
    absent_count = fields.Integer(string='Absent', compute='_compute_counts')

    @api.depends('line_ids.status')
    def _compute_counts(self):
        for rec in self:
            rec.present_count = len(rec.line_ids.filtered(lambda l: l.status == 'present'))
            rec.absent_count = len(rec.line_ids.filtered(lambda l: l.status == 'absent'))

    @api.onchange('class_id')
    def _onchange_class_id(self):
        if self.section_id and self.section_id.class_id != self.class_id:
            self.section_id = False

    @api.onchange('class_id', 'section_id', 'date')
    def _onchange_class_section(self):
        self.line_ids = [(5, 0, 0)]
        if not (self.class_id and self.section_id and self.date):
            return
        students = self.env['school.student'].search([
            ('class_id', '=', self.class_id.id),
            ('section_id', '=', self.section_id.id),
        ], order='roll_number, name')
        # Re-opening a day that was already marked shows what was saved.
        existing = self.env['school.attendance'].search([
            ('student_id', 'in', students.ids),
            ('date', '=', self.date),
            ('session', '=', 'morning'),
        ])
        saved = {rec.student_id.id: rec.status for rec in existing}
        self.line_ids = [(0, 0, {
            'student_id': student.id,
            'status': saved.get(student.id, 'present'),
        }) for student in students]

    def action_mark_all_present(self):
        self.line_ids.write({'status': 'present'})
        return self._reopen()

    def action_mark_all_absent(self):
        self.line_ids.write({'status': 'absent'})
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'name': _('Bulk Mark Attendance'),
        }

    def action_save_attendance(self):
        errors = []
        saved = 0
        Attendance = self.env['school.attendance']
        for rec in self:
            if not rec.line_ids:
                raise UserError(_(
                    "There is no attendance to save. Select the Class, Section and Date so the "
                    "student list is loaded, then mark each student Present or Absent."
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
            for student in students:
                status = sent_status.get(student.id)
                try:
                    # A savepoint isolates this one record: if it fails,
                    # everyone else in the batch is still saved.
                    with self.env.cr.savepoint():
                        existing = Attendance.search([
                            ('student_id', '=', student.id),
                            ('date', '=', rec.date),
                            ('session', '=', 'morning'),
                        ], limit=1)
                        if status is None:
                            # Student not on the sheet (e.g. enrolled after it
                            # was opened): never overwrite an existing record;
                            # only create a default "Present" one.
                            if existing:
                                continue
                            status = 'present'
                        if existing:
                            if existing.status != status:
                                existing.write({'status': status})
                        else:
                            Attendance.create({
                                'student_id': student.id,
                                'class_id': rec.class_id.id,
                                'section_id': rec.section_id.id,
                                'date': rec.date,
                                'session': 'morning',
                                'status': status,
                            })
                    saved += 1
                except Exception as e:
                    errors.append(_("%(student)s: %(error)s", student=student.name, error=str(e)))

        if errors:
            raise UserError(_(
                "%(saved)s attendance record(s) were saved, but the following could not be:\n\n%(errors)s",
                saved=saved, errors="\n".join(errors),
            ))
        present = sum(1 for line in self.line_ids if line.status == 'present')
        absent = sum(1 for line in self.line_ids if line.status == 'absent')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Attendance saved"),
                'message': _("%(count)s student(s): %(present)s present, %(absent)s absent.",
                             count=saved, present=present, absent=absent),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }


class SchoolBulkAttendanceLine(models.TransientModel):
    _name = 'school.bulk.attendance.line'
    _description = 'Bulk Attendance Line'

    wizard_id = fields.Many2one('school.bulk.attendance', string='Wizard')
    student_id = fields.Many2one('school.student', string='Student', required=True, readonly=True)
    roll_number = fields.Char(related='student_id.roll_number', string='Roll No.')
    status = fields.Selection(STATUSES, string='Status', required=True, default='present')

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [vals for vals in vals_list if vals.get('student_id')]
        if not vals_list:
            return self.browse()
        return super().create(vals_list)