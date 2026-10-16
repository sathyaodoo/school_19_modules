# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from . import oe_logic

MAX_FILE_BYTES = 5 * 1024 * 1024      # per file
MAX_FILES = 10                        # per submission
GRACE_SECONDS = 5


class SchoolOeAssignment(models.Model):
    _name = 'school.oe.assignment'
    _description = 'Descriptive Exam / Assignment / Project'
    _order = 'id desc'

    name = fields.Char(string='Title', required=True)
    kind = fields.Selection(
        [('descriptive', 'Descriptive Exam'), ('assignment', 'Assignment'), ('project', 'Project')],
        string='Type', default='descriptive', required=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('published', 'Published'), ('closed', 'Closed')],
        string='Status', default='draft', required=True)
    class_id = fields.Many2one('school.class', string='Class', required=True)
    section_id = fields.Many2one(
        'school.section', string='Section', domain="[('class_id', '=', class_id)]",
        help="Leave empty for the whole class.")
    subject_id = fields.Many2one('school.subject', string='Subject', required=True)
    instructions = fields.Text(string='Question / Instructions')
    question_attachment_ids = fields.Many2many(
        'ir.attachment', 'school_oe_assignment_qatt_rel', 'assignment_id', 'attachment_id',
        string='Question Paper / Files')
    max_marks = fields.Float(string='Max Marks', default=100.0, required=True)
    due_datetime = fields.Datetime(string='Due Date & Time', required=True)
    duration_minutes = fields.Integer(
        string='Time Limit (minutes)', default=0,
        help="0 = no timer, students can upload until the due date. "
             "If set, the timer starts when the student presses Start "
             "(never later than the due date).")
    allow_late = fields.Boolean(
        string='Allow Late Submission',
        help="Late submissions are accepted and marked as Late.")
    school_exam_id = fields.Many2one(
        'school.exam', string='Linked School Exam',
        help="Marks are sent from here to the principal; once approved they are written into this school exam's results.")
    mark_entry_count = fields.Integer(compute='_compute_mark_entry_count', string='Marks Entries')
    submission_ids = fields.One2many('school.oe.submission', 'assignment_id', string='Submissions')
    submission_count = fields.Integer(compute='_compute_counts', string='Submission Count')
    student_ids = fields.Many2many('school.student', compute='_compute_students', string='Students')
    student_count = fields.Integer(compute='_compute_students', string='Student Count')

    # ------------------------------------------------------------------
    @api.constrains('max_marks', 'duration_minutes')
    def _check_values(self):
        for rec in self:
            if rec.max_marks <= 0:
                raise ValidationError(_("Max marks must be greater than zero."))
            if rec.duration_minutes < 0:
                raise ValidationError(_("Time limit cannot be negative (0 = no timer)."))

    @api.constrains('class_id', 'section_id')
    def _check_section(self):
        for rec in self:
            if rec.section_id and rec.section_id.class_id != rec.class_id:
                raise ValidationError(_("The section does not belong to the selected class."))

    @api.onchange('class_id')
    def _onchange_class_id(self):
        if self.section_id and self.section_id.class_id != self.class_id:
            self.section_id = False

    def _compute_counts(self):
        for rec in self:
            rec.submission_count = len(rec.submission_ids.filtered(lambda s: s.state != 'draft'))

    def _student_domain(self):
        self.ensure_one()
        domain = [('class_id', '=', self.class_id.id)]
        if self.section_id:
            domain.append(('section_id', '=', self.section_id.id))
        return domain

    @api.depends('class_id', 'section_id')
    def _compute_students(self):
        Student = self.env['school.student']
        for rec in self:
            students = Student.search(rec._student_domain(), order='roll_number, name') if rec.class_id else Student
            rec.student_ids = students
            rec.student_count = len(students)

    # question files belong to this record so every teacher can open them
    def _link_question_files(self):
        for rec in self:
            rec.question_attachment_ids.sudo().filtered(lambda a: not a.res_model).write(
                {'res_model': rec._name, 'res_id': rec.id})

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs._link_question_files()
        return recs

    def write(self, vals):
        res = super().write(vals)
        if 'question_attachment_ids' in vals:
            self._link_question_files()
        return res

    # ------------------------------------------------------------------
    def action_publish(self):
        self.write({'state': 'published'})

    def action_close(self):
        self.write({'state': 'closed'})

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_view_submissions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Submissions'),
            'res_model': 'school.oe.submission', 'view_mode': 'list,form',
            'domain': [('assignment_id', '=', self.id)],
        }

    def _compute_mark_entry_count(self):
        Entry = self.env['school.oe.mark.entry']
        for rec in self:
            rec.mark_entry_count = Entry.search_count([('assignment_id', '=', rec.id)]) if rec.id else 0

    def action_view_mark_entries(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Marks Approval'),
                'res_model': 'school.oe.mark.entry', 'view_mode': 'list,form',
                'domain': [('assignment_id', '=', self.id)]}

    def action_send_for_approval(self):
        """Send the evaluated submissions' marks to the principal for approval."""
        self.ensure_one()
        if not self.school_exam_id:
            raise UserError(_("Select a 'Linked School Exam' first."))
        rows = [(s.student_id, s.marks, self.max_marks)
                for s in self.submission_ids if s.state == 'evaluated']
        if not rows:
            raise UserError(_("No submission is evaluated yet."))
        sent, unchanged = self.env['school.oe.mark.entry']._submit_for_approval(
            self, self.school_exam_id, self.subject_id, rows)
        return self.env['school.oe.mark.entry']._notify(
            _("Sent for approval"),
            _("%(sent)s mark(s) sent to the principal, %(same)s already up to date.", sent=sent, same=unchanged))

    def action_view_students(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Students'),
            'res_model': 'school.student', 'view_mode': 'list,form',
            'domain': self._student_domain(),
        }

    # ------------------------------------------------------------------
    def _visible_for(self, student):
        """True when this (published) assignment is meant for the student."""
        self.ensure_one()
        return (self.state == 'published' and student.class_id == self.class_id
                and (not self.section_id or student.section_id == self.section_id))

    def _submission_for(self, student, create=False, start=False):
        self.ensure_one()
        sub = self.env['school.oe.submission'].sudo().search(
            [('assignment_id', '=', self.id), ('student_id', '=', student.id)], limit=1)
        if not sub and create:
            sub = self.env['school.oe.submission'].sudo().create({
                'assignment_id': self.id, 'student_id': student.id,
                'started_datetime': fields.Datetime.now()})
        return sub


class SchoolOeSubmission(models.Model):
    _name = 'school.oe.submission'
    _description = 'Student Submission (answer sheet / assignment)'
    _order = 'assignment_id, student_id'

    assignment_id = fields.Many2one('school.oe.assignment', required=True, ondelete='cascade', index=True)
    student_id = fields.Many2one('school.student', string='Student', required=True, ondelete='cascade', index=True)
    class_id = fields.Many2one(related='assignment_id.class_id', store=True, string='Class')
    subject_id = fields.Many2one(related='assignment_id.subject_id', store=True, string='Subject')
    max_marks = fields.Float(related='assignment_id.max_marks', string='Max Marks')
    state = fields.Selection(
        [('draft', 'Not Submitted'), ('submitted', 'Submitted'), ('evaluated', 'Evaluated')],
        string='Status', default='draft', required=True, index=True)
    started_datetime = fields.Datetime(string='Started')
    submitted_datetime = fields.Datetime(string='Submitted On')
    is_late = fields.Boolean(string='Late')
    note = fields.Text(string='Student Note')
    attachment_ids = fields.Many2many(
        'ir.attachment', 'school_oe_submission_att_rel', 'submission_id', 'attachment_id',
        string='Uploaded Files')
    file_count = fields.Integer(compute='_compute_file_count', string='Files')
    marks = fields.Float(string='Marks')
    feedback = fields.Text(string='Teacher Feedback')
    evaluated_by = fields.Many2one('res.users', string='Evaluated By', readonly=True)
    evaluated_datetime = fields.Datetime(string='Evaluated On', readonly=True)

    _student_uniq = models.Constraint(
        'UNIQUE(assignment_id, student_id)', 'A student can have only one submission per assignment!')

    @api.depends('attachment_ids')
    def _compute_file_count(self):
        for rec in self:
            rec.file_count = len(rec.attachment_ids)

    @api.depends('assignment_id.name', 'student_id.name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s / %s' % (rec.assignment_id.name or '', rec.student_id.name or '')

    @api.constrains('marks')
    def _check_marks(self):
        for rec in self:
            if rec.marks < 0 or rec.marks > rec.assignment_id.max_marks:
                raise ValidationError(_(
                    "Marks must be between 0 and %s.", rec.assignment_id.max_marks))

    # ------------------------------------------------------------------ timer
    def get_deadline(self):
        self.ensure_one()
        a = self.assignment_id
        if a.duration_minutes and self.started_datetime:
            return min(a.due_datetime, self.started_datetime + timedelta(minutes=a.duration_minutes))
        return a.due_datetime

    def remaining_seconds(self):
        self.ensure_one()
        return oe_logic.remaining_seconds(self.get_deadline(), fields.Datetime.now())

    def is_open(self):
        """Student may still add / remove files and submit."""
        self.ensure_one()
        if self.state != 'draft' or self.assignment_id.state != 'published':
            return False
        if self.assignment_id.allow_late:
            return True
        return not oe_logic.is_expired(self.get_deadline(), fields.Datetime.now(), GRACE_SECONDS)

    # ------------------------------------------------------------------ student actions
    def _ensure_open(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("This work is already submitted."))
        if not self.is_open():
            raise UserError(_("The time is over. You can no longer upload or submit."))

    def add_files(self, files):
        """files: list of (filename, bytes). All-or-nothing validation."""
        self.ensure_one()
        self._ensure_open()
        if len(self.attachment_ids) + len(files) > MAX_FILES:
            raise UserError(_("You can upload at most %s files.", MAX_FILES))
        checked = []
        for filename, data in files:
            try:
                checked.append((*oe_logic.validate_upload(filename, data, MAX_FILE_BYTES), data))
            except ValueError as e:
                raise UserError(str(e))
        Attachment = self.env['ir.attachment'].sudo()
        for name, mime, data in checked:
            att = Attachment.create({'name': name, 'raw': data, 'mimetype': mime,
                                     'res_model': self._name, 'res_id': self.id})
            self.sudo().attachment_ids = [(4, att.id)]
        return len(checked)

    def remove_file(self, attachment_id):
        self.ensure_one()
        self._ensure_open()
        att = self.attachment_ids.filtered(lambda a: a.id == attachment_id)
        if att:
            self.sudo().attachment_ids = [(3, att.id)]
            att.sudo().unlink()

    def submit_work(self, note=None):
        self.ensure_one()
        self._ensure_open()
        if not self.attachment_ids:
            raise UserError(_("Upload at least one file before submitting."))
        now = fields.Datetime.now()
        self.sudo().write({
            'state': 'submitted', 'submitted_datetime': now, 'note': note or self.note,
            'is_late': oe_logic.is_expired(self.get_deadline(), now, GRACE_SECONDS),
        })

    # ------------------------------------------------------------------ teacher actions
    def action_evaluate(self):
        for rec in self:
            if rec.state == 'draft':
                raise UserError(_("The student has not submitted this work yet."))
            rec.write({'state': 'evaluated', 'evaluated_by': self.env.user.id,
                       'evaluated_datetime': fields.Datetime.now()})

    def action_reopen_evaluation(self):
        self.write({'state': 'submitted'})

    def action_return_to_student(self):
        """Teacher lets the student fix / re-upload (state back to Not Submitted)."""
        self.write({'state': 'draft', 'submitted_datetime': False, 'is_late': False})
