from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SchoolExam(models.Model):
    """An exam (e.g. Mid Term) for the academic year. Each class taking part
    has its OWN schedule (school.exam.class) that is prepared, scheduled and
    completed separately; the exam's status follows its classes."""
    _name = 'school.exam'
    _description = 'Examination'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Exam Name', required=True, tracking=True)
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', required=True, tracking=True)
    term_id = fields.Many2one('school.academic.term', string='Academic Term', required=True, tracking=True)
    class_schedule_ids = fields.One2many('school.exam.class', 'exam_id', string='Class Schedules')
    # All papers of all classes (read-only here: papers are added in each
    # class schedule). Used by the results and the result entry wizard.
    exam_subject_ids = fields.One2many('school.exam.subject', 'exam_id', string='Exam Schedule')
    class_ids = fields.Many2many('school.class', string='Classes', compute='_compute_class_ids', store=True,
                                 help='Classes that have a schedule in this exam.')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string='Status', compute='_compute_state', store=True, tracking=True,
        help='Follows the class schedules: Scheduled as soon as one class is scheduled, '
             'Completed when every (non-cancelled) class is completed.')
    # Activity marks the teacher adds for chosen students (only used when
    # Settings > Exam Marks > "Allow Activity Marks in Exam Total" is ticked).
    activity_mark_ids = fields.One2many('school.exam.activity.mark', 'exam_id', string='Activity Marks')
    activity_marks_enabled = fields.Boolean(compute='_compute_activity_marks_enabled')
    scheduled_class_count = fields.Integer(compute='_compute_schedule_progress')
    active_class_count = fields.Integer(compute='_compute_schedule_progress')
    schedule_progress = fields.Char(string='Classes Scheduled', compute='_compute_schedule_progress')

    @api.depends('class_schedule_ids.class_id')
    def _compute_class_ids(self):
        for exam in self:
            exam.class_ids = exam.class_schedule_ids.class_id

    @api.depends('class_schedule_ids.state')
    def _compute_state(self):
        for exam in self:
            states = exam.class_schedule_ids.mapped('state')
            active = [state for state in states if state != 'cancelled']
            if not states:
                exam.state = 'draft'
            elif not active:
                exam.state = 'cancelled'
            elif all(state == 'completed' for state in active):
                exam.state = 'completed'
            elif any(state in ('scheduled', 'completed') for state in active):
                exam.state = 'scheduled'
            else:
                exam.state = 'draft'

    @api.depends('class_schedule_ids.state')
    def _compute_schedule_progress(self):
        for exam in self:
            active = exam.class_schedule_ids.filtered(lambda c: c.state != 'cancelled')
            done = active.filtered(lambda c: c.state in ('scheduled', 'completed'))
            exam.active_class_count = len(active)
            exam.scheduled_class_count = len(done)
            exam.schedule_progress = '%s / %s' % (len(done), len(active))

    def _compute_activity_marks_enabled(self):
        enabled = self.env['school.exam.result']._activity_marks_settings()[0]
        for exam in self:
            exam.activity_marks_enabled = enabled

    def action_cancel(self):
        """Cancel the whole exam: every class schedule that is not completed."""
        self.class_schedule_ids.filtered(lambda c: c.state != 'completed').action_cancel()


class SchoolExamClass(models.Model):
    """The schedule of ONE class for an exam: its own papers (subject, date,
    time, marks, room) and its own status, independent of the other classes."""
    _name = 'school.exam.class'
    _description = 'Class Exam Schedule'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'exam_id desc, class_id'

    name = fields.Char(compute='_compute_name', store=True)
    exam_id = fields.Many2one('school.exam', string='Exam', required=True, ondelete='cascade', index=True)
    class_id = fields.Many2one('school.class', string='Class', required=True, index=True, tracking=True)
    academic_year_id = fields.Many2one(related='exam_id.academic_year_id', store=True)
    term_id = fields.Many2one(related='exam_id.term_id', store=True)
    exam_subject_ids = fields.One2many('school.exam.subject', 'class_schedule_id', string='Papers')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    paper_count = fields.Integer(string='No. of Papers', compute='_compute_dates', store=True)
    date_start = fields.Date(string='First Paper', compute='_compute_dates', store=True)
    date_end = fields.Date(string='Last Paper', compute='_compute_dates', store=True)

    _exam_class_uniq = models.Constraint(
        'unique(exam_id, class_id)',
        'This class already has a schedule in this exam!'
    )

    @api.depends('exam_id.name', 'class_id.name')
    def _compute_name(self):
        for rec in self:
            rec.name = '%s – %s' % (rec.exam_id.name or '', rec.class_id.name or '')

    @api.depends('exam_subject_ids.date')
    def _compute_dates(self):
        for rec in self:
            dates = [d for d in rec.exam_subject_ids.mapped('date') if d]
            rec.paper_count = len(rec.exam_subject_ids)
            rec.date_start = min(dates) if dates else False
            rec.date_end = max(dates) if dates else False

    def action_schedule(self):
        for rec in self:
            if rec.state != 'draft':
                raise ValidationError(_("Only a Draft class schedule can be scheduled."))
            if not rec.exam_subject_ids:
                raise ValidationError(_(
                    "Add the papers (subject, date and time) for %(cls)s before scheduling it.",
                    cls=rec.class_id.name))
        self.write({'state': 'scheduled'})

    def action_complete(self):
        if any(rec.state != 'scheduled' for rec in self):
            raise ValidationError(_("Only a Scheduled class schedule can be completed."))
        self.write({'state': 'completed'})

    def action_cancel(self):
        if any(rec.state == 'completed' for rec in self):
            raise ValidationError(_("A completed class schedule cannot be cancelled."))
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        """Re-open a scheduled / cancelled class schedule to change its papers."""
        if any(rec.state == 'completed' for rec in self):
            raise ValidationError(_("A completed class schedule cannot be reset to Draft."))
        self.write({'state': 'draft'})

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft_or_cancelled(self):
        # Deleting a scheduled / completed class would also delete its papers,
        # which the students' results are linked to.
        for rec in self:
            if rec.state in ('scheduled', 'completed'):
                raise ValidationError(_(
                    "The exam schedule of %(cls)s is %(state)s and cannot be deleted. "
                    "Reset it to Draft (or cancel it) first.",
                    cls=rec.class_id.name,
                    state=dict(self._fields['state']._description_selection(self.env))[rec.state]))

    def action_open(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.display_name,
            'res_model': 'school.exam.class',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }


class SchoolExamSubject(models.Model):
    """One paper of a class schedule: subject, date, time, marks and room."""
    _name = 'school.exam.subject'
    _description = 'Exam Subject Detail'
    _order = 'class_id, date, time_start, id'

    class_schedule_id = fields.Many2one('school.exam.class', string='Class Schedule', required=True,
                                        ondelete='cascade', index=True)
    # Taken from the class schedule; stored so results, the result entry
    # wizard and the mark list keep finding papers by exam + class.
    exam_id = fields.Many2one(related='class_schedule_id.exam_id', string='Exam Reference',
                              store=True, index=True)
    class_id = fields.Many2one(related='class_schedule_id.class_id', string='Class',
                               store=True, index=True)
    subject_id = fields.Many2one('school.subject', string='Subject', required=True)
    academic_year_id = fields.Many2one(related='exam_id.academic_year_id', string='Academic Year', store=True)
    exam_state = fields.Selection(related='class_schedule_id.state', string='Schedule Status')
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

    # Papers can only be changed while their class schedule is in Draft
    # (use "Reset to Draft" on a scheduled class to change its timetable).
    def _check_schedule_editable(self, schedules):
        locked = schedules.filtered(lambda c: c.state != 'draft')
        if locked:
            raise ValidationError(_(
                "The exam schedule of %(cls)s is %(state)s. Reset it to Draft to change its papers.",
                cls=locked[0].class_id.name,
                state=dict(locked._fields['state']._description_selection(self.env))[locked[0].state]))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_schedule_editable(self.env['school.exam.class'].browse(
            [vals['class_schedule_id'] for vals in vals_list if vals.get('class_schedule_id')]))
        return super().create(vals_list)

    def write(self, vals):
        self._check_schedule_editable(self.class_schedule_id)
        if vals.get('class_schedule_id'):
            self._check_schedule_editable(self.env['school.exam.class'].browse(vals['class_schedule_id']))
        return super().write(vals)

    def unlink(self):
        self._check_schedule_editable(self.class_schedule_id)
        return super().unlink()

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

    @api.constrains('marks_obtained')
    def _check_total_with_activity_marks(self):
        """A changed subject mark must not push subject marks + the activity
        marks already added to THIS subject above the paper's max marks."""
        Mark = self.env['school.exam.activity.mark']
        for record in self:
            line = Mark.search([('exam_id', '=', record.exam_id.id),
                                ('student_id', '=', record.student_id.id),
                                ('subject_id', '=', record.subject_id.id)], limit=1)
            if line and line.marks and record.max_marks and \
                    record.marks_obtained + line.marks > record.max_marks:
                raise ValidationError(_(
                    "%(student)s - %(subject)s: %(obtained)s marks + %(marks)s activity marks already "
                    "added in exam '%(exam)s' = %(total)s, which is more than the max marks %(max)s. "
                    "Lower the activity marks in the exam's Activity Marks tab first.",
                    student=record.student_id.name, subject=record.subject_id.name,
                    obtained=record.marks_obtained, marks=line.marks, exam=record.exam_id.name,
                    total=record.marks_obtained + line.marks, max=record.max_marks))

    # ------------------------------------------------------------------
    # Activity marks in the exam total
    # (Settings > School Management > Exam Marks)
    #
    # Nothing is added automatically: the teacher picks the student and the
    # subject and types the marks in the exam's "Activity Marks" tab
    # (school.exam.activity.mark). The Mark List reads those lines.
    # ------------------------------------------------------------------
    @api.model
    def _activity_marks_settings(self, company=None):
        """(enabled, cap) of the given company (default: current company).
        cap = 0 means no limit."""
        company = company or self.env.company
        return bool(company.exam_include_activity_score), max(company.exam_activity_score_max or 0, 0)

    def get_activity_mark_details(self):
        """{(student id, exam id, subject id): activity marks the teacher added
        to that subject} for these results. Only subjects with a line in the
        exam's Activity Marks tab appear. Empty when the setting is off."""
        enabled, _cap = self._activity_marks_settings()
        if not enabled or not self:
            return {}
        keys = {(r.student_id.id, r.exam_id.id, r.subject_id.id) for r in self}
        lines = self.env['school.exam.activity.mark'].search([
            ('student_id', 'in', self.student_id.ids),
            ('exam_id', 'in', self.exam_id.ids),
            ('subject_id', 'in', self.subject_id.ids),
        ])
        details = {}
        for line in lines:
            key = (line.student_id.id, line.exam_id.id, line.subject_id.id)
            if key in keys and line.marks:
                details[key] = details.get(key, 0.0) + line.marks
        return details

    def get_mark_list_rows(self, activity_details):
        """Rows of the Mark List for these results (one student), in order:
        (result, activity added, final marks, percentage, grade, passed).
        A subject with activity marks uses its final marks (never above its
        max marks) for the grade, percentage and pass / fail."""
        grades = self.env['school.grade'].search([])
        rows = []
        for line in self:
            act = activity_details.get((line.student_id.id, line.exam_id.id, line.subject_id.id), 0.0)
            if not act:
                rows.append((line, 0.0, line.marks_obtained, line.percentage, line.grade_id,
                             line.result_status == 'pass'))
                continue
            final = max(min(line.marks_obtained + act, line.max_marks), line.marks_obtained)
            pct = (final / line.max_marks * 100.0) if line.max_marks else 0.0
            grade = grades.filtered(lambda g: g.min_mark <= pct <= g.max_mark)[:1]
            rows.append((line, final - line.marks_obtained, final, pct, grade,
                         final >= (line.min_marks or 0.0)))
        return rows

    def action_print_mark_list(self):
        """Print the Mark List for the selected result lines."""
        if not self:
            raise ValidationError(_("Please select at least one result to print."))
        return self.env.ref('ad_school_management.action_report_exam_mark_list').report_action(self)
