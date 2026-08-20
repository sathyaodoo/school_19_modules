from odoo import models, fields, api, _
from odoo.exceptions import UserError

class SchoolBulkAttendance(models.TransientModel):
    _name = 'school.bulk.attendance'
    _description = 'Bulk Attendance Wizard'

    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    class_id = fields.Many2one('school.class', string='Class', required=True)
    section_id = fields.Many2one('school.section', string='Section', required=True)
    line_ids = fields.One2many('school.bulk.attendance.line', 'wizard_id', string='Attendance Lines')

    @api.onchange('class_id', 'section_id', 'date')
    def _onchange_class_section(self):
        if self.class_id and self.section_id:
            self.line_ids = [(5, 0, 0)]
            students = self.env['school.student'].search([
                ('class_id', '=', self.class_id.id),
                ('section_id', '=', self.section_id.id)
            ])
            lines = []
            for student in students:
                existing = self.env['school.attendance'].search([
                    ('student_id', '=', student.id),
                    ('date', '=', self.date)
                ], limit=1)
                
                lines.append((0, 0, {
                    'student_id': student.id,
                    'status': existing.status if existing else 'present',
                }))
            self.line_ids = lines

    def action_save_attendance(self):
        errors = []
        for rec in self:
            # Whatever status the client actually captured, keyed by student.
            # A row that got dropped client-side simply won't appear here.
            sent_status = {
                line.student_id.id: line.status
                for line in rec.line_ids if line.student_id
            }

            # Re-derive the real class roster directly from the database.
            # This guarantees every enrolled student gets an attendance
            # record today, even if the browser failed to send their row.
            students = self.env['school.student'].search([
                ('class_id', '=', rec.class_id.id),
                ('section_id', '=', rec.section_id.id),
            ])

            for student in students:
                status = sent_status.get(student.id, 'present')
                try:
                    # A savepoint isolates this one student's save: if it
                    # fails for any reason, only this student's attempt is
                    # rolled back - everyone else in the batch still saves
                    # normally instead of the whole transaction aborting.
                    with self.env.cr.savepoint():
                        existing = self.env['school.attendance'].search([
                            ('student_id', '=', student.id),
                            ('date', '=', rec.date)
                        ], limit=1)
                        if existing:
                            existing.write({'status': status})
                        else:
                            self.env['school.attendance'].create({
                                'student_id': student.id,
                                'class_id': rec.class_id.id,
                                'section_id': rec.section_id.id,
                                'date': rec.date,
                                'status': status,
                            })
                except Exception as e:
                    errors.append(_("%s: %s") % (student.name, str(e)))

        if errors:
            raise UserError(_(
                "Some attendance records were saved, but the following could not be:\n\n%s"
            ) % "\n".join(errors))
        return {'type': 'ir.actions.act_window_close'}

class SchoolBulkAttendanceLine(models.TransientModel):
    _name = 'school.bulk.attendance.line'
    _description = 'Bulk Attendance Line'

    wizard_id = fields.Many2one('school.bulk.attendance', string='Wizard')
    student_id = fields.Many2one('school.student', string='Student', required=True, readonly=True)
    status = fields.Selection([
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('leave', 'Leave'),
        ('late', 'Late')
    ], string='Status', required=True, default='present')

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [vals for vals in vals_list if vals.get('student_id')]
        if not vals_list:
            return self.browse()
        return super().create(vals_list)