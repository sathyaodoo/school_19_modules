# -*- coding: utf-8 -*-
from datetime import timedelta

import psycopg2

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from . import oe_logic


class SchoolOeExam(models.Model):
    _name = 'school.oe.exam'
    _description = 'Online Exam'
    _order = 'id desc'

    name = fields.Char(string='Exam Name', required=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('published', 'Published'), ('closed', 'Closed')],
        string='Status', default='draft', required=True)
    exam_type = fields.Selection(
        [('exam', 'Exam'), ('mock', 'Mock Test'), ('practice', 'Self Practice')],
        string='Type', default='exam', required=True, index=True,
        help="Mock test = practice only. Scores are saved in the attempt history "
             "but are never pushed to the marks register. Correct answers are "
             "always shown after submitting.")
    practice_student_id = fields.Many2one(
        'school.student', string='Practice Owner', ondelete='cascade', index=True,
        help="Self-practice sessions belong to one student and are hidden from everybody else.")
    class_id = fields.Many2one('school.class', string='Class', required=True)
    section_id = fields.Many2one(
        'school.section', string='Section',
        domain="[('class_id', '=', class_id)]",
        help="Leave empty to open the exam for the whole class. "
             "If a section is selected, only the students of that section get the exam.")
    subject_id = fields.Many2one('school.subject', string='Subject', required=True)
    chapter_ids = fields.Many2many(
        'school.oe.chapter', 'school_oe_exam_chapter_rel', 'exam_id', 'chapter_id',
        string='Chapters (optional filter)',
        domain="[('class_id', '=', class_id), ('subject_id', '=', subject_id)]")
    topic_ids = fields.Many2many(
        'school.oe.topic', 'school_oe_exam_topic_rel', 'exam_id', 'topic_id',
        string='Topics (optional filter)',
        domain="[('class_id', '=', class_id), ('subject_id', '=', subject_id)]")

    questions_per_attempt = fields.Integer(string='Questions per Attempt', default=10, required=True)
    duration_minutes = fields.Integer(string='Duration (minutes)', default=2, required=True)
    max_attempts = fields.Integer(string='Max Attempts', default=0,
                                  help="0 = unlimited attempts.")
    avoid_repeat = fields.Boolean(
        string='Avoid Repeating Questions', default=True,
        help="Next attempts first use questions the student has not seen yet. "
             "When the whole bank has been shown once, a new round starts. "
             "If off, every attempt is a plain random pick from the bank.")
    shuffle_options = fields.Boolean(string='Shuffle Options', default=True)
    show_answers = fields.Boolean(
        string='Show Correct Answers after Submit', default=True)
    pass_percentage = fields.Float(string='Pass %', default=40.0)
    score_policy = fields.Selection(
        [('best', 'Best attempt'), ('latest', 'Latest attempt'), ('first', 'First attempt')],
        string='Score Counted', default='best', required=True,
        help="Which attempt is used as the student's final score (reports / marks push).")
    date_start = fields.Datetime(string='Available From')
    date_end = fields.Datetime(string='Available Until')

    school_exam_id = fields.Many2one(
        'school.exam', string='Linked School Exam',
        help="Optional. Marks are sent from here to the principal; once approved they are written into this school exam's results.")

    attempt_ids = fields.One2many('school.oe.attempt', 'exam_id', string='Attempt Records')
    student_ids = fields.Many2many('school.student', string='Students', compute='_compute_students')
    student_count = fields.Integer(string='Student Count', compute='_compute_students')
    pool_count = fields.Integer(string='Questions in Bank', compute='_compute_counts')
    attempt_count = fields.Integer(string='Attempts', compute='_compute_counts')

    # ------------------------------------------------------------------
    # computes / constraints
    # ------------------------------------------------------------------
    def _compute_counts(self):
        Question = self.env['school.oe.question']
        Attempt = self.env['school.oe.attempt']
        for rec in self:
            rec.pool_count = Question.search_count(rec._pool_domain()) if rec.id else 0
            rec.attempt_count = Attempt.search_count([('exam_id', '=', rec.id)]) if rec.id else 0

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
            students = Student.search(rec._student_domain(), order='roll_number, name') \
                if rec.class_id else Student
            rec.student_ids = students
            rec.student_count = len(students)

    @api.onchange('class_id')
    def _onchange_class_id(self):
        if self.section_id and self.section_id.class_id != self.class_id:
            self.section_id = False

    @api.constrains('class_id', 'section_id')
    def _check_section(self):
        for rec in self:
            if rec.section_id and rec.section_id.class_id != rec.class_id:
                raise ValidationError(_("The section does not belong to the selected class."))

    @api.constrains('questions_per_attempt', 'duration_minutes', 'max_attempts', 'pass_percentage')
    def _check_config(self):
        for rec in self:
            if rec.questions_per_attempt < 1:
                raise ValidationError(_("Questions per attempt must be at least 1."))
            if rec.duration_minutes < 1:
                raise ValidationError(_("Duration must be at least 1 minute."))
            if rec.max_attempts < 0:
                raise ValidationError(_("Max attempts cannot be negative (0 = unlimited)."))
            if not 0 <= rec.pass_percentage <= 100:
                raise ValidationError(_("Pass % must be between 0 and 100."))

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_start >= rec.date_end:
                raise ValidationError(_("'Available From' must be before 'Available Until'."))

    # ------------------------------------------------------------------
    # question pool
    # ------------------------------------------------------------------
    def _pool_domain(self):
        self.ensure_one()
        domain = [('class_id', '=', self.class_id.id),
                  ('subject_id', '=', self.subject_id.id),
                  ('active', '=', True)]
        if self.topic_ids:
            domain.append(('topic_id', 'in', self.topic_ids.ids))
        elif self.chapter_ids:
            domain.append(('chapter_id', 'in', self.chapter_ids.ids))
        return domain

    def _get_pool(self):
        self.ensure_one()
        return self.env['school.oe.question'].sudo().search(self._pool_domain())

    # ------------------------------------------------------------------
    # state buttons
    # ------------------------------------------------------------------
    def action_publish(self):
        for rec in self:
            pool = rec.pool_count
            if pool < rec.questions_per_attempt:
                raise UserError(_(
                    "The question bank for this exam has only %(pool)s question(s) but each attempt "
                    "needs %(need)s. Add more questions before publishing.",
                    pool=pool, need=rec.questions_per_attempt))
            rec.state = 'published'

    def action_close(self):
        self.write({'state': 'closed'})

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_view_questions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Questions'),
            'res_model': 'school.oe.question',
            'view_mode': 'list,form',
            'domain': self._pool_domain(),
            'context': {'default_class_id': self.class_id.id,
                        'default_subject_id': self.subject_id.id},
        }

    def action_view_students(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Students'),
            'res_model': 'school.student',
            'view_mode': 'list,form',
            'domain': self._student_domain(),
        }

    def action_view_attempts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Attempts'),
            'res_model': 'school.oe.attempt',
            'view_mode': 'list,form',
            'domain': [('exam_id', '=', self.id)],
            'context': {'search_default_group_student': 1},
        }

    # ------------------------------------------------------------------
    # student side: start / resume
    # ------------------------------------------------------------------
    def _check_available(self, student, now=None):
        self.ensure_one()
        now = now or fields.Datetime.now()
        if self.state != 'published':
            raise UserError(_("This exam is not open."))
        if student.class_id != self.class_id:
            raise UserError(_("This exam is not for your class."))
        if self.section_id and student.section_id != self.section_id:
            raise UserError(_("This exam is not for your section."))
        if self.exam_type == 'practice' and self.practice_student_id != student:
            raise UserError(_("This practice session belongs to another student."))
        if self.date_start and now < self.date_start:
            raise UserError(_("This exam has not started yet."))
        if self.date_end and now > self.date_end:
            raise UserError(_("This exam is closed."))

    @api.model
    def _practice_exam_for(self, student, subject, chapter, topic, n):
        """The student's own practice 'exam' for this subject/chapter/topic/size.

        It is re-used on every session so the 'unseen questions first' rule keeps
        working across sessions."""
        student = student.sudo()
        Exam = self.sudo()
        candidates = Exam.search([
            ('exam_type', '=', 'practice'), ('practice_student_id', '=', student.id),
            ('subject_id', '=', subject.id), ('class_id', '=', student.class_id.id),
            ('questions_per_attempt', '=', n)])
        for exam in candidates:
            if exam.chapter_ids == chapter and exam.topic_ids == topic:
                return exam
        parts = [subject.name] + ([chapter.name] if chapter else []) + ([topic.name] if topic else [])
        return Exam.create({
            'name': _("Practice: %(what)s (%(n)s questions)", what=' / '.join(parts), n=n),
            'exam_type': 'practice', 'practice_student_id': student.id,
            'class_id': student.class_id.id, 'subject_id': subject.id,
            'chapter_ids': [(6, 0, chapter.ids)], 'topic_ids': [(6, 0, topic.ids)],
            'questions_per_attempt': n, 'duration_minutes': max(1, n),   # 1 minute per question
            'max_attempts': 0, 'avoid_repeat': True, 'shuffle_options': True,
            'show_answers': True, 'state': 'published',
        })

    def _start_or_resume_attempt(self, student):
        """Return the attempt the student should see now.

        * an unexpired in-progress attempt is RESUMED (same questions)
        * an expired in-progress attempt is auto-submitted first
        * otherwise a NEW attempt is created (if attempts are left)
        """
        self.ensure_one()
        exam = self.sudo()
        student = student.sudo()
        Attempt = self.env['school.oe.attempt'].sudo()
        now = fields.Datetime.now()

        open_attempt = Attempt.search(
            [('exam_id', '=', exam.id), ('student_id', '=', student.id),
             ('state', '=', 'in_progress')], limit=1)
        if open_attempt:
            if open_attempt.deadline > now:
                return open_attempt
            open_attempt._finalize('auto_submitted', now)

        exam._check_available(student, now)

        past = Attempt.search(
            [('exam_id', '=', exam.id), ('student_id', '=', student.id)], order='attempt_no')
        if exam.max_attempts and len(past) >= exam.max_attempts:
            raise UserError(_("You have used all %s attempts for this exam.", exam.max_attempts))

        pool = exam._get_pool()
        if not pool:
            raise UserError(_("No questions are available for this exam."))
        history = [a.line_ids.sorted('sequence').mapped('question_id').ids for a in past]
        seen = oe_logic.seen_in_current_cycle(history, pool.ids)
        chosen_ids = oe_logic.pick_questions(
            pool.ids, seen, exam.questions_per_attempt, exam.avoid_repeat)

        questions = {q.id: q for q in pool}
        line_vals = []
        for seq, qid in enumerate(chosen_ids, start=1):
            q = questions[qid]
            order = oe_logic.shuffled_keys(q.get_option_keys(), exam.shuffle_options)
            line_vals.append((0, 0, {
                'sequence': seq,
                'question_id': q.id,
                'question_text': q.name,
                'option_a': q.option_a, 'option_b': q.option_b,
                'option_c': q.option_c, 'option_d': q.option_d,
                'correct_key': q.correct_option,
                'marks': q.marks,
                'option_order': ''.join(order),
            }))
        vals = {
            'exam_id': exam.id,
            'student_id': student.id,
            'attempt_no': (past[-1].attempt_no if past else 0) + 1,
            'start_datetime': now,
            'deadline': now + timedelta(minutes=exam.duration_minutes),
            'state': 'in_progress',
            'line_ids': line_vals,
        }
        try:
            with self.env.cr.savepoint():
                return Attempt.create(vals)
        except psycopg2.IntegrityError:
            # two tabs / devices started at the same moment: use the winner
            winner = Attempt.search(
                [('exam_id', '=', exam.id), ('student_id', '=', student.id),
                 ('state', '=', 'in_progress')], limit=1)
            if winner:
                return winner
            raise

    # ------------------------------------------------------------------
    # scores
    # ------------------------------------------------------------------
    def _final_attempt(self, student):
        """The attempt that counts for this student (per score policy)."""
        self.ensure_one()
        done = self.attempt_ids.filtered(
            lambda a: a.student_id == student and a.state != 'in_progress')
        if not done:
            return self.env['school.oe.attempt']
        done = done.sorted('attempt_no')
        if self.score_policy == 'first':
            return done[0]
        if self.score_policy == 'latest':
            return done[-1]
        return sorted(done, key=lambda a: (-a.score, a.attempt_no))[0]

    @api.onchange('exam_type')
    def _onchange_exam_type(self):
        if self.exam_type == 'mock':
            self.show_answers = True
            self.school_exam_id = False

    mark_entry_count = fields.Integer(compute='_compute_mark_entry_count', string='Marks Entries')

    def _compute_mark_entry_count(self):
        Entry = self.env['school.oe.mark.entry']
        for rec in self:
            rec.mark_entry_count = Entry.search_count([('exam_id', '=', rec.id)]) if rec.id else 0

    def action_view_mark_entries(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Marks Approval'),
                'res_model': 'school.oe.mark.entry', 'view_mode': 'list,form',
                'domain': [('exam_id', '=', self.id)]}

    def action_send_for_approval(self):
        """Send each student's counted score to the principal for approval.
        Only approved marks reach the School Exam Results."""
        self.ensure_one()
        if self.exam_type != 'exam':
            raise UserError(_("Mock tests and self-practice are not counted in the marks register."))
        if not self.school_exam_id:
            raise UserError(_("Select a 'Linked School Exam' first."))
        rows = []
        for student in self.attempt_ids.mapped('student_id'):
            att = self._final_attempt(student)
            if att:
                rows.append((student, att.score, att.total_marks))
        if not rows:
            raise UserError(_("No student has finished this exam yet."))
        sent, unchanged = self.env['school.oe.mark.entry']._submit_for_approval(
            self, self.school_exam_id, self.subject_id, rows)
        return self.env['school.oe.mark.entry']._notify(
            _("Sent for approval"),
            _("%(sent)s mark(s) sent to the principal, %(same)s already up to date.", sent=sent, same=unchanged))
