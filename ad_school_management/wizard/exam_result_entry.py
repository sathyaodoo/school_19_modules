from odoo import models, fields, api, _

class SchoolExamResultEntry(models.TransientModel):
    _name = 'school.exam.result.entry'
    _description = 'Exam Result Entry Wizard'

    exam_id = fields.Many2one('school.exam', string='Exam', required=True)
    class_id = fields.Many2one('school.class', string='Class', required=True)
    section_id = fields.Many2one('school.section', string='Section', required=True)
    subject_id = fields.Many2one('school.subject', string='Subject', required=True)
    line_ids = fields.One2many('school.exam.result.entry.line', 'wizard_id', string='Result Entries')

    @api.onchange('exam_id', 'class_id', 'section_id', 'subject_id')
    def _onchange_selections(self):
        if self.exam_id and self.class_id and self.section_id and self.subject_id:
            self.line_ids = [(5, 0, 0)]
            students = self.env['school.student'].search([
                ('class_id', '=', self.class_id.id),
                ('section_id', '=', self.section_id.id)
            ])
            lines = []
            for student in students:
                existing = self.env['school.exam.result'].search([
                    ('exam_id', '=', self.exam_id.id),
                    ('student_id', '=', student.id),
                    ('subject_id', '=', self.subject_id.id)
                ], limit=1)
                
                lines.append((0, 0, {
                    'student_id': student.id,
                    'marks_obtained': existing.marks_obtained if existing else 0.0,
                }))
            self.line_ids = lines

    def action_save_results(self):
        for rec in self:
            for line in rec.line_ids:
                existing = self.env['school.exam.result'].search([
                    ('exam_id', '=', rec.exam_id.id),
                    ('student_id', '=', line.student_id.id),
                    ('subject_id', '=', rec.subject_id.id)
                ], limit=1)
                if existing:
                    existing.write({'marks_obtained': line.marks_obtained})
                else:
                    self.env['school.exam.result'].create({
                        'exam_id': rec.exam_id.id,
                        'student_id': line.student_id.id,
                        'subject_id': rec.subject_id.id,
                        'marks_obtained': line.marks_obtained,
                    })
        return {'type': 'ir.actions.act_window_close'}

class SchoolExamResultEntryLine(models.TransientModel):
    _name = 'school.exam.result.entry.line'
    _description = 'Exam Result Entry Line'

    wizard_id = fields.Many2one('school.exam.result.entry', string='Wizard')
    student_id = fields.Many2one('school.student', string='Student', required=True, readonly=True)
    marks_obtained = fields.Float(string='Marks Obtained', default=0.0)
