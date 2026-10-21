from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SchoolExamActivityMark(models.Model):
    """Activity marks a teacher gives to ONE subject of ONE student in ONE exam.

    Nothing is created automatically: in the exam's "Activity Marks" tab the
    teacher picks the student, picks the subject and types the marks.
    A teacher (who is not Principal / School Admin) can only pick the
    subjects they teach (Subject > Teachers).

    Limits (checked while typing and on Save):
      * marks cannot be negative
      * per student : all activity marks of the student in this exam (all
                      subjects together) <= Settings > Exam Marks > Maximum
                      Activity Marks (0 = no limit)
      * per subject : subject marks + activity marks <= that paper's max marks
    """
    _name = 'school.exam.activity.mark'
    _description = 'Exam Activity Marks (per subject)'
    _order = 'exam_id desc, class_id, student_id, subject_id'
    _rec_name = 'student_id'

    exam_id = fields.Many2one('school.exam', string='Exam', required=True, ondelete='cascade', index=True)
    academic_year_id = fields.Many2one(related='exam_id.academic_year_id', store=True)
    student_id = fields.Many2one('school.student', string='Student', required=True, index=True)
    admission_no = fields.Char(related='student_id.admission_no', string='Admission No')
    class_id = fields.Many2one(related='student_id.class_id', string='Class', store=True)
    section_id = fields.Many2one(related='student_id.section_id', string='Section', store=True)
    subject_id = fields.Many2one('school.subject', string='Subject', required=True, index=True)
    available_subject_ids = fields.Many2many('school.subject', compute='_compute_available_subject_ids')
    added_by = fields.Many2one('res.users', string='Added By', default=lambda self: self.env.user,
                               readonly=True)

    marks = fields.Float(string='Activity Marks', required=True, default=0.0,
                         help="Marks the teacher adds to this subject in this exam.")

    # Student level: Maximum Activity Marks (Settings) shared by all subjects
    used_elsewhere = fields.Float(
        string='Given in Other Subjects', compute='_compute_limit_left',
        help='Activity marks already given to this student in the other subjects of this exam.')
    has_limit = fields.Boolean(compute='_compute_limit_left')
    limit_left = fields.Float(
        string='Limit Left', compute='_compute_limit_left',
        help='Maximum Activity Marks (Settings) minus the marks given in the other subjects. '
             'Empty when there is no limit.')

    # Subject level
    subject_marks = fields.Float(string='Subject Marks', compute='_compute_subject_marks',
                                 help='Marks the student obtained in this subject in this exam.')
    max_marks = fields.Float(string='Max Marks', compute='_compute_subject_marks',
                             help="Maximum marks of this subject's paper for the student's class.")
    available_marks = fields.Float(string='Room Left', compute='_compute_subject_marks',
                                   help='Max Marks - Subject Marks: the most activity marks that fit.')
    total_marks = fields.Float(string='Subject Total', compute='_compute_total_marks',
                               help='Subject Marks + Activity Marks.')

    _exam_student_uniq = models.Constraint(
        'unique(exam_id, student_id, subject_id)',
        'This student already has activity marks for this subject in this exam!'
    )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @api.model
    def _is_teacher_only(self):
        """True for a teacher who is not Principal / School Admin / Odoo admin:
        such a user may only give marks in the subjects they teach."""
        user = self.env.user
        if self.env.is_superuser() or user.has_group('base.group_system'):
            return False
        if user.has_group('ad_school_management.group_school_admin') or \
                user.has_group('ad_school_management.group_school_principal'):
            return False
        return user.has_group('ad_school_management.group_school_teacher')

    @api.model
    def _max_activity_marks(self):
        """Settings > Exam Marks > Maximum Activity Marks (0 = no limit)."""
        return max(self.env.company.exam_activity_score_max or 0, 0)

    def _exam_papers(self, exam, student):
        return exam.exam_subject_ids.filtered(lambda p: p.class_id == student.class_id)

    # ------------------------------------------------------------------
    # computes
    # ------------------------------------------------------------------
    @api.depends('exam_id', 'student_id')
    def _compute_available_subject_ids(self):
        teacher_only = self._is_teacher_only()
        for line in self:
            exam = line.exam_id._origin or line.exam_id
            student = line.student_id._origin or line.student_id
            subjects = self._exam_papers(exam, student).subject_id if exam and student \
                else self.env['school.subject']
            if teacher_only:
                subjects = subjects.filtered(lambda s: self.env.user in s.teacher_ids.user_id)
            line.available_subject_ids = subjects

    @api.depends('student_id', 'subject_id', 'exam_id.activity_mark_ids.marks',
                 'exam_id.activity_mark_ids.student_id', 'exam_id.activity_mark_ids.subject_id')
    def _compute_limit_left(self):
        cap = self._max_activity_marks()
        for line in self:
            # the student's lines for the OTHER subjects (one line per subject)
            others = line.exam_id.activity_mark_ids.filtered(
                lambda l: l.student_id == line.student_id and l.subject_id != line.subject_id)
            used = sum(others.mapped('marks'))
            line.used_elsewhere = used
            line.has_limit = bool(cap)
            line.limit_left = max(cap - used, 0.0) if cap else 0.0

    @api.depends('student_id', 'exam_id', 'subject_id')
    def _compute_subject_marks(self):
        Result = self.env['school.exam.result']
        for line in self:
            exam = line.exam_id._origin        # saved exam (a new exam has no results yet)
            student = line.student_id._origin or line.student_id
            subject = line.subject_id._origin or line.subject_id
            if not exam or not student or not subject:
                line.subject_marks = line.max_marks = line.available_marks = 0.0
                continue
            paper = self._exam_papers(exam, student).filtered(lambda p: p.subject_id == subject)[:1]
            result = Result.search([('exam_id', '=', exam.id), ('student_id', '=', student.id),
                                    ('subject_id', '=', subject.id)], limit=1)
            line.subject_marks = result.marks_obtained
            line.max_marks = paper.max_marks or result.max_marks
            line.available_marks = max(line.max_marks - line.subject_marks, 0.0)

    @api.depends('subject_marks', 'marks')
    def _compute_total_marks(self):
        for line in self:
            line.total_marks = line.subject_marks + line.marks

    # ------------------------------------------------------------------
    # onchange
    # ------------------------------------------------------------------
    @api.onchange('student_id')
    def _onchange_student_id(self):
        if self.subject_id and self.subject_id not in self.available_subject_ids:
            self.subject_id = False

    @api.onchange('marks')
    def _onchange_marks(self):
        """Warn while typing (the same rules block the Save)."""
        cap = self._max_activity_marks()
        if self.student_id and cap and self.used_elsewhere + self.marks > cap:
            return {'warning': {
                'title': _("Maximum Activity Marks exceeded"),
                'message': _(
                    "%(student)s can get at most %(cap)s activity marks in this exam (all subjects "
                    "together). %(used)s are already given in other subjects, so at most %(left)s "
                    "can be given here.",
                    student=self.student_id.name, cap=cap, used=self.used_elsewhere,
                    left=self.limit_left),
            }}
        if self.student_id and self.subject_id and self.max_marks and self.marks > self.available_marks:
            return {'warning': {
                'title': _("Subject total exceeds max marks"),
                'message': _(
                    "%(student)s has %(sm)s / %(max)s in %(subject)s. Adding %(marks)s would make "
                    "%(total)s, which is more than %(max)s. At most %(room)s can be added.",
                    student=self.student_id.name, subject=self.subject_id.name, sm=self.subject_marks,
                    max=self.max_marks, marks=self.marks, total=self.subject_marks + self.marks,
                    room=self.available_marks),
            }}

    # ------------------------------------------------------------------
    # checks
    # ------------------------------------------------------------------
    @api.constrains('marks', 'student_id', 'exam_id', 'subject_id')
    def _check_marks(self):
        cap = self._max_activity_marks()
        teacher_only = self._is_teacher_only()
        for line in self:
            name = line.student_id.name
            if line.marks < 0:
                raise ValidationError(_("Activity marks cannot be negative."))
            papers = self._exam_papers(line.exam_id, line.student_id)
            if line.subject_id not in papers.subject_id:
                raise ValidationError(_(
                    "%(student)s: %(subject)s is not a paper of class %(cls)s in exam %(exam)s.",
                    student=name, subject=line.subject_id.name, cls=line.class_id.name or '-',
                    exam=line.exam_id.name))
            if teacher_only and self.env.user not in line.subject_id.teacher_ids.user_id:
                raise ValidationError(_(
                    "You can only give activity marks in the subjects you teach. "
                    "%(subject)s is not one of your subjects.", subject=line.subject_id.name))
            # per student: Maximum Activity Marks, all subjects together
            if cap:
                used = sum(line.exam_id.activity_mark_ids.filtered(
                    lambda l: l.student_id == line.student_id).mapped('marks'))
                if used > cap:
                    raise ValidationError(_(
                        "%(student)s: activity marks in all subjects of this exam (%(used)s) cannot "
                        "be more than the Maximum Activity Marks set in Settings (%(cap)s).",
                        student=name, used=used, cap=cap))
            # per subject: never above the paper's max marks
            if line.max_marks and line.subject_marks + line.marks > line.max_marks:
                raise ValidationError(_(
                    "%(student)s - %(subject)s: subject marks %(sm)s + activity marks %(marks)s = "
                    "%(total)s, which is more than the max marks %(max)s. At most %(room)s can be added.",
                    student=name, subject=line.subject_id.name, sm=line.subject_marks,
                    marks=line.marks, total=line.subject_marks + line.marks, max=line.max_marks,
                    room=line.available_marks))