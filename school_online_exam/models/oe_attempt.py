# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from . import oe_logic

# answers arriving up to this many seconds after the deadline are still accepted
# (network delay of the last click / the auto-submit from the browser timer)
GRACE_SECONDS = 5
WEAK_BELOW = 60.0          # chapter accuracy (%) under this is a weak area
WEAK_MIN_QUESTIONS = 3     # ...but only when at least this many questions were answered


class SchoolOeAttempt(models.Model):
    _name = 'school.oe.attempt'
    _description = 'Online Exam Attempt'
    _order = 'exam_id, student_id, attempt_no'

    exam_id = fields.Many2one('school.oe.exam', string='Exam', required=True, ondelete='cascade', index=True)
    student_id = fields.Many2one('school.student', string='Student', required=True, ondelete='cascade', index=True)
    class_id = fields.Many2one(related='exam_id.class_id', store=True, string='Class')
    subject_id = fields.Many2one(related='exam_id.subject_id', store=True, string='Subject')
    exam_type = fields.Selection(related='exam_id.exam_type', store=True, string='Type')
    attempt_no = fields.Integer(string='Attempt No.', required=True)
    state = fields.Selection(
        [('in_progress', 'In Progress'),
         ('submitted', 'Submitted'),
         ('auto_submitted', 'Auto-submitted (time over)')],
        string='Status', default='in_progress', required=True, index=True)
    start_datetime = fields.Datetime(string='Started', required=True)
    deadline = fields.Datetime(string='Deadline', required=True)
    submit_datetime = fields.Datetime(string='Submitted')
    line_ids = fields.One2many('school.oe.attempt.line', 'attempt_id', string='Questions')

    total_marks = fields.Float(string='Total Marks')
    score = fields.Float(string='Score')
    percentage = fields.Float(string='Percentage', aggregator='avg')
    correct_count = fields.Integer(string='Correct')
    answered_count = fields.Integer(string='Answered')
    result = fields.Selection([('pass', 'Pass'), ('fail', 'Fail')], string='Result')
    time_taken = fields.Integer(string='Time Taken (sec)', compute='_compute_time_taken')

    _attempt_no_uniq = models.Constraint(
        'UNIQUE(exam_id, student_id, attempt_no)',
        'Attempt number must be unique for a student in an exam!')

    def init(self):
        # one running attempt per student per exam, enforced by the database
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS school_oe_attempt_one_running_idx
            ON school_oe_attempt (exam_id, student_id)
            WHERE state = 'in_progress'
        """)

    @api.depends('start_datetime', 'submit_datetime')
    def _compute_time_taken(self):
        for rec in self:
            if rec.start_datetime and rec.submit_datetime:
                rec.time_taken = int((rec.submit_datetime - rec.start_datetime).total_seconds())
            else:
                rec.time_taken = 0

    @api.depends('exam_id.name', 'attempt_no', 'student_id.name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s / %s / #%s' % (
                rec.exam_id.name or '', rec.student_id.name or '', rec.attempt_no)

    # ------------------------------------------------------------------
    # timer
    # ------------------------------------------------------------------
    def remaining_seconds(self):
        self.ensure_one()
        if self.state != 'in_progress':
            return 0
        return oe_logic.remaining_seconds(self.deadline, fields.Datetime.now())

    def _auto_close_if_expired(self):
        """Score the attempt if its time is over. Returns True when closed."""
        self.ensure_one()
        now = fields.Datetime.now()
        if self.state == 'in_progress' and self.deadline <= now:
            self._finalize('auto_submitted', now)
            return True
        return False

    # ------------------------------------------------------------------
    # answers
    # ------------------------------------------------------------------
    def _apply_answers(self, answers):
        """answers: {line_id(int): 'a'|'b'|'c'|'d'|''}"""
        self.ensure_one()
        for line in self.line_ids:
            if line.id not in answers:
                continue
            key = answers[line.id] or False
            if key and key not in line.get_option_keys():
                continue
            if line.selected_option != key:
                line.selected_option = key

    def save_answer(self, line_id, key):
        """Called on every click. Returns state info for the browser."""
        self.ensure_one()
        now = fields.Datetime.now()
        if self.state != 'in_progress':
            return {'ok': False, 'state': self.state}
        if oe_logic.is_expired(self.deadline, now, GRACE_SECONDS):
            self._finalize('auto_submitted', now)
            return {'ok': False, 'state': self.state}
        self._apply_answers({int(line_id): key})
        return {'ok': True, 'state': 'in_progress',
                'remaining': oe_logic.remaining_seconds(self.deadline, now)}

    def submit(self, answers=None, timeout=False):
        """Final submit (button or browser timer). Late answers are ignored."""
        self.ensure_one()
        if self.state != 'in_progress':
            return self
        now = fields.Datetime.now()
        in_time = not oe_logic.is_expired(self.deadline, now, GRACE_SECONDS)
        if in_time and answers:
            self._apply_answers(answers)
        status = 'submitted' if (in_time and not timeout) else 'auto_submitted'
        self._finalize(status, now)
        return self

    # ------------------------------------------------------------------
    # scoring
    # ------------------------------------------------------------------
    def _finalize(self, status, now=None):
        self.ensure_one()
        now = now or fields.Datetime.now()
        if self.state != 'in_progress':
            return
        total = score = 0.0
        correct = answered = 0
        for line in self.line_ids:
            ok = bool(line.selected_option) and line.selected_option == line.correct_key
            line.is_correct = ok
            line.marks_obtained = line.marks if ok else 0.0
            total += line.marks
            score += line.marks_obtained
            correct += 1 if ok else 0
            answered += 1 if line.selected_option else 0
        pct = (score / total * 100.0) if total else 0.0
        submit_dt = now if status == 'submitted' else min(now, self.deadline)
        self.write({
            'state': status,
            'submit_datetime': submit_dt,
            'total_marks': total,
            'score': score,
            'percentage': pct,
            'correct_count': correct,
            'answered_count': answered,
            'result': 'pass' if pct >= self.exam_id.pass_percentage else 'fail',
        })

    # ------------------------------------------------------------------ performance analysis
    @api.model
    def _performance_data(self, student):
        """Everything the 'My Performance' page shows for one student."""
        student = student.sudo()
        Attempt = self.sudo()
        Line = self.env['school.oe.attempt.line'].sudo()
        finished = [('state', '!=', 'in_progress')]
        done = Attempt.search([('student_id', '=', student.id)] + finished, order='submit_datetime, id')

        def avg(recs):
            return sum(recs.mapped('percentage')) / len(recs) if recs else 0.0

        data = {
            'attempts': len(done), 'avg': avg(done),
            'best': max(done.mapped('percentage')) if done else 0.0,
            'by_type': [], 'subjects': [], 'chapters': [], 'weak': [], 'trend': [],
        }
        for key, label in (('exam', 'Exams'), ('mock', 'Mock Tests'), ('practice', 'Self Practice')):
            recs = done.filtered(lambda a: a.exam_type == key)
            data['by_type'].append({'key': key, 'label': label, 'count': len(recs), 'avg': avg(recs)})
        for subject in done.mapped('subject_id'):
            mine = done.filtered(lambda a: a.subject_id == subject)
            klass = Attempt.search([('class_id', '=', student.class_id.id),
                                    ('subject_id', '=', subject.id)] + finished)
            data['subjects'].append({'subject': subject, 'count': len(mine), 'avg': avg(mine),
                                     'class_avg': avg(klass)})
        data['subjects'].sort(key=lambda r: r['subject'].name)
        rows = Line._read_group(
            [('student_id', '=', student.id), ('attempt_state', '!=', 'in_progress'),
             ('chapter_id', '!=', False)],
            ['subject_id', 'chapter_id'], ['accuracy:avg', '__count'])
        for subject, chapter, accuracy, count in rows:
            item = {'subject': subject, 'chapter': chapter, 'accuracy': accuracy or 0.0, 'count': count,
                    'weak': count >= WEAK_MIN_QUESTIONS and (accuracy or 0.0) < WEAK_BELOW}
            data['chapters'].append(item)
        data['chapters'].sort(key=lambda r: (r['accuracy'], r['chapter'].name))
        data['weak'] = [c for c in data['chapters'] if c['weak']]
        for att in done[-10:]:
            data['trend'].append({'attempt': att, 'percentage': att.percentage})
        return data

    @api.model
    def _cron_auto_submit_expired(self):
        """Score attempts whose time ran out and the student never came back."""
        limit = fields.Datetime.now() - timedelta(seconds=GRACE_SECONDS)
        for att in self.search([('state', '=', 'in_progress'), ('deadline', '<', limit)]):
            att._finalize('auto_submitted')


class SchoolOeAttemptLine(models.Model):
    _name = 'school.oe.attempt.line'
    _description = 'Online Exam Attempt Question'
    _order = 'attempt_id, sequence'

    attempt_id = fields.Many2one('school.oe.attempt', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(string='No.')
    question_id = fields.Many2one('school.oe.question', string='Question (bank)', ondelete='restrict')
    # snapshot: history stays correct even if staff edit the bank later
    question_text = fields.Text(string='Question')
    option_a = fields.Char()
    option_b = fields.Char()
    option_c = fields.Char()
    option_d = fields.Char()
    correct_key = fields.Selection([('a', 'A'), ('b', 'B'), ('c', 'C'), ('d', 'D')], string='Correct')
    marks = fields.Float(string='Marks')
    option_order = fields.Char(string='Option Order', help="Display order of the option keys, e.g. 'cabd'.")
    selected_option = fields.Selection(
        [('a', 'A'), ('b', 'B'), ('c', 'C'), ('d', 'D')], string='Student Answer')
    is_correct = fields.Boolean(string='Correct?')
    marks_obtained = fields.Float(string='Marks Obtained')

    # ---- stored helper fields for the Performance Analysis reports (pivot / graph) ----
    student_id = fields.Many2one(related='attempt_id.student_id', store=True, string='Student', index=True)
    class_id = fields.Many2one(related='attempt_id.class_id', store=True, string='Class')
    subject_id = fields.Many2one(related='attempt_id.subject_id', store=True, string='Subject')
    exam_id = fields.Many2one(related='attempt_id.exam_id', store=True, string='Exam')
    exam_type = fields.Selection(related='attempt_id.exam_type', store=True, string='Type')
    attempt_state = fields.Selection(related='attempt_id.state', store=True, string='Attempt Status')
    chapter_id = fields.Many2one(related='question_id.chapter_id', store=True, string='Chapter')
    topic_id = fields.Many2one(related='question_id.topic_id', store=True, string='Topic')
    accuracy = fields.Float(
        string='Correct %', compute='_compute_accuracy', store=True, aggregator='avg',
        help="100 when the student answered correctly, 0 otherwise. The average of this "
             "field over many questions is the accuracy.")

    @api.depends('is_correct')
    def _compute_accuracy(self):
        for line in self:
            line.accuracy = 100.0 if line.is_correct else 0.0

    def get_option_keys(self):
        self.ensure_one()
        return [k for k in oe_logic.OPTION_KEYS if getattr(self, 'option_%s' % k)]

    def get_display_options(self):
        """[(key, text), ...] in the order this attempt shows them."""
        self.ensure_one()
        order = [k for k in (self.option_order or '') if k in self.get_option_keys()]
        order = order or self.get_option_keys()
        return [(k, getattr(self, 'option_%s' % k)) for k in order]
