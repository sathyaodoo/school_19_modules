from odoo import models, fields, api, _

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
        for rec in self:
            for line in rec.line_ids:
                existing = self.env['school.attendance'].search([
                    ('student_id', '=', line.student_id.id),
                    ('date', '=', rec.date)
                ], limit=1)
                if existing:
                    existing.write({'status': line.status})
                else:
                    self.env['school.attendance'].create({
                        'student_id': line.student_id.id,
                        'class_id': rec.class_id.id,
                        'section_id': rec.section_id.id,
                        'date': rec.date,
                        'status': line.status,
                    })
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
