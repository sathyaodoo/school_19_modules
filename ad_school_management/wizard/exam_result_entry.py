from odoo import models, fields, api, _
from odoo.exceptions import UserError

class SchoolExamResultEntry(models.TransientModel):
    _name = 'school.exam.result.entry'
    _description = 'Exam Result Entry Wizard'

    exam_id = fields.Many2one('school.exam', string='Exam', required=True)
    class_id = fields.Many2one('school.class', string='Class', required=True)
    section_id = fields.Many2one('school.section', string='Section', required=True)
    subject_id = fields.Many2one('school.subject', string='Subject', required=True)
    line_ids = fields.One2many('school.exam.result.entry.line', 'wizard_id', string='Result Entries')

    exam_class_ids = fields.Many2many(related='exam_id.class_ids', string='Exam Classes')
    # Only subjects scheduled for this class in this exam can be chosen.
    available_subject_ids = fields.Many2many('school.subject', compute='_compute_schedule')
    exam_subject_id = fields.Many2one('school.exam.subject', string='Paper', compute='_compute_schedule')
    paper_date = fields.Date(related='exam_subject_id.date', string='Exam Date')
    paper_max_marks = fields.Float(related='exam_subject_id.max_marks', string='Max Marks')
    paper_min_marks = fields.Float(related='exam_subject_id.min_marks', string='Pass Marks')

    @api.depends('exam_id', 'class_id', 'subject_id')
    def _compute_schedule(self):
        for rec in self:
            lines = rec.exam_id.exam_subject_ids.filtered(lambda l: l.class_id == rec.class_id) \
                if rec.exam_id and rec.class_id else self.env['school.exam.subject']
            rec.available_subject_ids = lines.subject_id
            rec.exam_subject_id = lines.filtered(lambda l: l.subject_id == rec.subject_id)[:1]

    @api.onchange('exam_id', 'class_id')
    def _onchange_exam_class(self):
        # Clear a subject that is not scheduled for the new exam / class.
        if self.subject_id and self.subject_id not in self.available_subject_ids:
            self.subject_id = False
        if self.section_id and self.class_id and self.section_id.class_id != self.class_id:
            self.section_id = False

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
        errors = []
        saved = 0
        for rec in self:
            if not rec.line_ids:
                raise UserError(_(
                    "There are no marks to save. Select the Exam, Class, Section and "
                    "Subject so the student list is loaded, then enter the marks."
                ))
            # Whatever marks the client actually captured, keyed by student.
            sent_marks = {
                line.student_id.id: line.marks_obtained
                for line in rec.line_ids if line.student_id
            }

            # Re-derive the real class roster directly from the database.
            students = self.env['school.student'].search([
                ('class_id', '=', rec.class_id.id),
                ('section_id', '=', rec.section_id.id),
            ])

            for student in students:
                if student.id not in sent_marks:
                    continue
                marks = sent_marks[student.id]
                try:
                    # A savepoint isolates this one student's save: if it
                    # fails (e.g. a bad Max Marks config), only this
                    # student's attempt is rolled back - everyone else in
                    # the batch still saves normally instead of the whole
                    # transaction being aborted.
                    with self.env.cr.savepoint():
                        existing = self.env['school.exam.result'].search([
                            ('exam_id', '=', rec.exam_id.id),
                            ('student_id', '=', student.id),
                            ('subject_id', '=', rec.subject_id.id)
                        ], limit=1)
                        if existing:
                            existing.write({'marks_obtained': marks})
                        else:
                            self.env['school.exam.result'].create({
                                'exam_id': rec.exam_id.id,
                                'student_id': student.id,
                                'subject_id': rec.subject_id.id,
                                'marks_obtained': marks,
                            })
                    saved += 1
                except Exception as e:
                    errors.append(_("%s: %s") % (student.name, str(e)))

        if errors:
            raise UserError(_(
                "%(saved)s result(s) were saved, but the following could not be:\n\n%(errors)s",
                saved=saved, errors="\n".join(errors),
            ))
        # Confirm what was saved instead of closing silently.
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Results saved"),
                'message': _(
                    "%s result(s) saved. See them in Operations & Exams > Exam Results.", saved
                ),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

class SchoolExamResultEntryLine(models.TransientModel):
    _name = 'school.exam.result.entry.line'
    _description = 'Exam Result Entry Line'

    wizard_id = fields.Many2one('school.exam.result.entry', string='Wizard')
    student_id = fields.Many2one('school.student', string='Student', required=True, readonly=True)
    marks_obtained = fields.Float(string='Marks Obtained', default=0.0)

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [vals for vals in vals_list if vals.get('student_id')]
        if not vals_list:
            return self.browse()
        return super().create(vals_list)