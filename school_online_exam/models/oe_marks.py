# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

APPROVER_GROUPS = (
    'ad_school_management.group_school_principal',
    'ad_school_management.group_school_admin',
    'base.group_system',
)


class SchoolOeMarkEntry(models.Model):
    """One student's marks of one online exam / assignment, waiting for approval.

    Teacher presses "Send Marks for Approval" -> entries are *pending*.
    Principal / administrator approves -> the marks are written to the
    School Exam Results (marks register). Nothing reaches the register before."""
    _name = 'school.oe.mark.entry'
    _description = 'Online Exam Marks Approval'
    _order = 'id desc'

    source = fields.Selection(
        [('exam', 'Online Exam'), ('assignment', 'Assignment / Project')],
        string='Source', required=True)
    exam_id = fields.Many2one('school.oe.exam', string='Online Exam', ondelete='cascade', index=True)
    assignment_id = fields.Many2one('school.oe.assignment', string='Assignment', ondelete='cascade', index=True)
    source_name = fields.Char(compute='_compute_source_name', store=True, string='Exam / Assignment')
    school_exam_id = fields.Many2one('school.exam', string='School Exam (marks register)',
                                     required=True, ondelete='cascade')
    subject_id = fields.Many2one('school.subject', string='Subject', required=True)
    student_id = fields.Many2one('school.student', string='Student', required=True, ondelete='cascade', index=True)
    class_id = fields.Many2one(related='student_id.class_id', store=True, string='Class')
    score = fields.Float(string='Score')
    total = fields.Float(string='Out of')
    percentage = fields.Float(string='Percentage')
    max_marks = fields.Float(string='Register Max Marks')
    marks = fields.Float(string='Marks for Register')
    state = fields.Selection(
        [('pending', 'Waiting for Approval'), ('approved', 'Approved & Posted'), ('rejected', 'Rejected')],
        string='Status', default='pending', required=True, index=True)
    submitted_by = fields.Many2one('res.users', string='Sent By', readonly=True)
    submitted_datetime = fields.Datetime(string='Sent On', readonly=True)
    approved_by = fields.Many2one('res.users', string='Approved / Rejected By', readonly=True)
    approved_datetime = fields.Datetime(string='Decided On', readonly=True)
    reject_reason = fields.Text(string='Reason (when rejected)')
    result_id = fields.Many2one('school.exam.result', string='Register Entry', readonly=True, ondelete='set null')

    _exam_student_uniq = models.Constraint(
        'UNIQUE(exam_id, student_id)', 'This student already has an entry for this online exam!')
    _assignment_student_uniq = models.Constraint(
        'UNIQUE(assignment_id, student_id)', 'This student already has an entry for this assignment!')

    @api.depends('exam_id.name', 'assignment_id.name')
    def _compute_source_name(self):
        for rec in self:
            rec.source_name = rec.exam_id.name or rec.assignment_id.name or ''

    @api.depends('source_name', 'student_id.name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s / %s' % (rec.source_name or '', rec.student_id.name or '')

    # ------------------------------------------------------------------ who may approve
    def _check_approver(self):
        if self.env.su:
            return
        user = self.env.user
        if not any(user.has_group(g) for g in APPROVER_GROUPS):
            raise AccessError(_("Only the principal or an administrator can approve or reject marks."))

    def write(self, vals):
        if vals.get('state') in ('approved', 'rejected'):
            self._check_approver()
        return super().write(vals)

    # ------------------------------------------------------------------ teacher side
    @api.model
    def _submit_for_approval(self, source, school_exam, subject, rows):
        """source: school.oe.exam / school.oe.assignment record,
        rows: [(student, score, total)]. Returns (sent, unchanged)."""
        schedule = school_exam.exam_subject_ids.filtered(lambda s: s.subject_id == subject)[:1]
        if not schedule:
            raise UserError(_("The linked school exam has no schedule line for subject %s.", subject.name))
        field = 'exam_id' if source._name == 'school.oe.exam' else 'assignment_id'
        Entry = self.sudo()
        now = fields.Datetime.now()
        sent = unchanged = 0
        for student, score, total in rows:
            percentage = (score / total * 100.0) if total else 0.0
            marks = round(percentage * schedule.max_marks / 100.0, 2)
            vals = {
                'school_exam_id': school_exam.id, 'subject_id': subject.id, 'student_id': student.id,
                'score': score, 'total': total, 'percentage': percentage,
                'max_marks': schedule.max_marks, 'marks': marks,
            }
            entry = Entry.search([(field, '=', source.id), ('student_id', '=', student.id)], limit=1)
            if entry:
                if (entry.state in ('pending', 'approved') and entry.school_exam_id == school_exam
                        and abs(entry.marks - marks) < 0.005):
                    unchanged += 1
                    continue
                entry.write(dict(vals, state='pending', submitted_by=self.env.user.id, submitted_datetime=now,
                                 approved_by=False, approved_datetime=False, reject_reason=False))
            else:
                Entry.create(dict(vals, source='exam' if field == 'exam_id' else 'assignment',
                                  submitted_by=self.env.user.id, submitted_datetime=now, **{field: source.id}))
            sent += 1
        return sent, unchanged

    # ------------------------------------------------------------------ principal / admin side
    def _post_to_register(self):
        self.ensure_one()
        Result = self.env['school.exam.result'].sudo()
        result = Result.search([('exam_id', '=', self.school_exam_id.id),
                                ('student_id', '=', self.student_id.id),
                                ('subject_id', '=', self.subject_id.id)], limit=1)
        if result:
            result.marks_obtained = self.marks
        else:
            result = Result.create({'exam_id': self.school_exam_id.id, 'student_id': self.student_id.id,
                                    'subject_id': self.subject_id.id, 'marks_obtained': self.marks})
        return result

    def action_approve(self):
        self._check_approver()
        now = fields.Datetime.now()
        done = 0
        for entry in self.filtered(lambda e: e.state in ('pending', 'rejected')):
            result = entry._post_to_register()
            entry.sudo().write({'state': 'approved', 'approved_by': self.env.user.id, 'approved_datetime': now,
                                'result_id': result.id, 'reject_reason': False})
            done += 1
        return self._notify(_("Approved"), _("%s mark(s) approved and posted to the marks register.", done))

    def action_reject(self):
        self._check_approver()
        now = fields.Datetime.now()
        for entry in self:
            if entry.state != 'pending':
                raise UserError(_("Only marks that are waiting for approval can be rejected."))
            if not (entry.reject_reason or '').strip():
                raise UserError(_("Write the reason for rejecting in 'Reason (when rejected)' first."))
            entry.sudo().write({'state': 'rejected', 'approved_by': self.env.user.id, 'approved_datetime': now})
        return self._notify(_("Rejected"), _("The teacher can correct the marks and send them again."), 'warning')

    @api.model
    def _notify(self, title, message, kind='success'):
         return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': title, 'message': message, 'type': kind, 'sticky': False,
                           'next': {'type': 'ir.actions.act_window_close'}}}