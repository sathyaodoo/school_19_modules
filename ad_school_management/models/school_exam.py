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
    class_ids = fields.Many2many('school.class', string='Classes', compute='_compute_class_ids', store=True,
                                 help='Classes that have at least one paper in this exam.')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', required=True, tracking=True)

    @api.depends('exam_subject_ids.class_id')
    def _compute_class_ids(self):
        for exam in self:
            exam.class_ids = exam.exam_subject_ids.class_id

    def action_schedule(self):
        for exam in self:
            if not exam.exam_subject_ids:
                raise ValidationError(_("Add the Exam Schedule (class, subject, date and time) before scheduling the exam."))
        self.write({'state': 'scheduled'})

    def action_complete(self):
        self.write({'state': 'completed'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

class SchoolExamSubject(models.Model):
    """One paper of an exam for ONE class: each class has its own subjects,
    dates, times, marks and room."""
    _name = 'school.exam.subject'
    _description = 'Exam Subject Detail'
    _order = 'class_id, date, time_start, id'

    exam_id = fields.Many2one('school.exam', string='Exam Reference', required=True, ondelete='cascade')
    class_id = fields.Many2one('school.class', string='Class', required=True, index=True)
    subject_id = fields.Many2one('school.subject', string='Subject', required=True)
    academic_year_id = fields.Many2one(related='exam_id.academic_year_id', string='Academic Year', store=True)
    exam_state = fields.Selection(related='exam_id.state', string='Exam Status')
    date = fields.Date(string='Exam Date', required=True)
    time_start = fields.Float(string='Start Time', required=True, aggregator=False)
    time_end = fields.Float(string='End Time', required=True, aggregator=False)
    max_marks = fields.Float(string='Max Marks', default=100.0, required=True, aggregator=False)
    min_marks = fields.Float(string='Min Marks', default=40.0, required=True, aggregator=False)
    room = fields.Char(string='Room/Hall')

    _exam_class_subject_uniq = models.Constraint(
        'unique(exam_id, class_id, subject_id)',
        'This subject is already scheduled for this class in this exam!'
    )

    @api.depends('exam_id', 'class_id', 'subject_id')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s – %s – %s' % (
                rec.exam_id.name or '', rec.class_id.name or '', rec.subject_id.name or '')

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
    _order = 'student_id, exam_id, subject_id'

    exam_id = fields.Many2one('school.exam', string='Exam', required=True, ondelete='cascade')
    student_id = fields.Many2one('school.student', string='Student', required=True)
    subject_id = fields.Many2one('school.subject', string='Subject', required=True)

    # Stored so results can be filtered, grouped and printed by them
    # (Exam Marks Tracking & Filtering / Mark List report).
    admission_no = fields.Char(related='student_id.admission_no', string='Admission No', store=True)
    class_id = fields.Many2one(related='student_id.class_id', string='Class', store=True)
    section_id = fields.Many2one(related='student_id.section_id', string='Section', store=True)
    academic_year_id = fields.Many2one(related='exam_id.academic_year_id', string='Academic Year', store=True)
    term_id = fields.Many2one(related='exam_id.term_id', string='Term', store=True)
    
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

    @api.depends('exam_id', 'subject_id', 'class_id',
                 'exam_id.exam_subject_ids.class_id', 'exam_id.exam_subject_ids.subject_id')
    def _compute_exam_subject_id(self):
        """The schedule line of this exam + subject for the STUDENT'S class
        (its max / min marks are used for the result)."""
        for rec in self:
            if rec.exam_id and rec.subject_id and rec.class_id:
                exam_subj = self.env['school.exam.subject'].search([
                    ('exam_id', '=', rec.exam_id.id),
                    ('class_id', '=', rec.class_id.id),
                    ('subject_id', '=', rec.subject_id.id),
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

    @api.constrains('marks_obtained', 'max_marks', 'exam_subject_id')
    def _check_obtained_marks(self):
        for record in self:
            if not record.exam_subject_id:
                raise ValidationError(_(
                    "No exam schedule found for subject '%(subject)s' for class '%(cls)s' on exam "
                    "'%(exam)s'. Add this subject for this class in the exam's Exam Schedule tab, "
                    "and save the exam, before entering results.",
                    subject=record.subject_id.name, cls=record.class_id.name or '-',
                    exam=record.exam_id.name))
            if record.marks_obtained < 0:
                raise ValidationError(_("Marks obtained cannot be negative."))
            if record.marks_obtained > record.max_marks:
                raise ValidationError(_("Marks obtained (%s) cannot exceed the maximum marks (%s)!") % (record.marks_obtained, record.max_marks))

    def action_print_mark_list(self):
        """Print the Mark List for the selected result lines."""
        if not self:
            raise ValidationError(_("Please select at least one result to print."))
        return self.env.ref('ad_school_management.action_report_exam_mark_list').report_action(self)