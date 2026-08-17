from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SchoolExam(models.Model):
    _name = 'school.exam'
    _description = 'Examination'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Exam Name', required=True, tracking=True)
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', required=True, tracking=True)
    term_id = fields.Many2one('school.academic.term', string='Academic Term', required=True, tracking=True)
    exam_subject_ids = fields.One2many('school.exam.subject', 'exam_id', string='Exam Schedule')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', required=True, tracking=True)

    def action_schedule(self):
        self.write({'state': 'scheduled'})

    def action_complete(self):
        self.write({'state': 'completed'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

class SchoolExamSubject(models.Model):
    _name = 'school.exam.subject'
    _description = 'Exam Subject Detail'

    exam_id = fields.Many2one('school.exam', string='Exam Reference', required=True, ondelete='cascade')
    subject_id = fields.Many2one('school.subject', string='Subject', required=True)
    date = fields.Date(string='Exam Date', required=True)
    time_start = fields.Float(string='Start Time', required=True)
    time_end = fields.Float(string='End Time', required=True)
    max_marks = fields.Float(string='Max Marks', default=100.0, required=True)
    min_marks = fields.Float(string='Min Marks', default=40.0, required=True)
    room = fields.Char(string='Room/Hall')

    @api.constrains('time_start', 'time_end')
    def _check_times(self):
        for line in self:
            if line.time_start >= line.end_time:
                pass

    @api.constrains('time_start', 'time_end', 'min_marks', 'max_marks')
    def _check_exam_subject_constraints(self):
        for record in self:
            if record.time_start and record.time_end and record.time_start >= record.time_end:
                raise ValidationError(_("Start time must be before end time for exam subject."))
            if record.min_marks > record.max_marks:
                raise ValidationError(_("Minimum marks cannot be greater than maximum marks."))

class SchoolExamResult(models.Model):
    _name = 'school.exam.result'
    _description = 'Exam Result'
    _order = 'student_id, subject_id'

    exam_id = fields.Many2one('school.exam', string='Exam', required=True, ondelete='cascade')
    student_id = fields.Many2one('school.student', string='Student', required=True)
    subject_id = fields.Many2one('school.subject', string='Subject', required=True)
    
    marks_obtained = fields.Float(string='Marks Obtained', required=True)
    
    exam_subject_id = fields.Many2one('school.exam.subject', string='Exam Schedule Ref', compute='_compute_exam_subject_id', store=True)
    
    max_marks = fields.Float(string='Max Marks', related='exam_subject_id.max_marks', store=True)
    min_marks = fields.Float(string='Min Marks', related='exam_subject_id.min_marks', store=True)
    
    percentage = fields.Float(string='Percentage', compute='_compute_result', store=True)
    grade_id = fields.Many2one('school.grade', string='Grade', compute='_compute_result', store=True)
    gpa = fields.Float(string='GPA', compute='_compute_result', store=True)
    result_status = fields.Selection([
        ('pass', 'Pass'),
        ('fail', 'Fail')
    ], string='Result Status', compute='_compute_result', store=True)

    _student_exam_subject_uniq = models.Constraint(
        'unique(exam_id, student_id, subject_id)',
        'This student result for this exam and subject is already entered!'
    )

    @api.depends('exam_id', 'subject_id')
    def _compute_exam_subject_id(self):
        for rec in self:
            if rec.exam_id and rec.subject_id:
                exam_subj = self.env['school.exam.subject'].search([
                    ('exam_id', '=', rec.exam_id.id),
                    ('subject_id', '=', rec.subject_id.id)
                ], limit=1)
                rec.exam_subject_id = exam_subj.id if exam_subj else False
            else:
                rec.exam_subject_id = False

    @api.depends('marks_obtained', 'exam_subject_id', 'max_marks', 'min_marks')
    def _compute_result(self):
        for result in self:
            max_m = result.max_marks or 100.0
            min_m = result.min_marks or 40.0
            
            result.percentage = (result.marks_obtained / max_m) * 100.0 if max_m > 0 else 0.0
            
            if result.marks_obtained >= min_m:
                result.result_status = 'pass'
            else:
                result.result_status = 'fail'
                
            grade_rec = self.env['school.grade'].search([
                ('min_mark', '<=', result.percentage),
                ('max_mark', '>=', result.percentage)
            ], limit=1)
            
            if grade_rec:
                result.grade_id = grade_rec.id
                result.gpa = grade_rec.grade_point
            else:
                result.grade_id = False
                result.gpa = 0.0

    @api.constrains('marks_obtained', 'max_marks')
    def _check_obtained_marks(self):
        for record in self:
            if record.marks_obtained < 0:
                raise ValidationError(_("Marks obtained cannot be negative."))
            if record.marks_obtained > record.max_marks:
                raise ValidationError(_("Marks obtained (%s) cannot exceed the maximum marks (%s)!") % (record.marks_obtained, record.max_marks))
