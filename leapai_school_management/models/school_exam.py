# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SchoolExam(models.Model):
    _name = 'school.exam'
    _description = 'School Examination'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'exam_date desc'

    name = fields.Char(string='Exam Name', required=True, tracking=True, help='e.g. Mid-Term Exam 2025')
    exam_type = fields.Selection([
        ('midterm', 'Mid-Term'),
        ('final', 'Final'),
        ('unit_test', 'Unit Test'),
        ('practical', 'Practical'),
    ], string='Exam Type', required=True, default='unit_test')
    class_id = fields.Many2one('school.class', string='Class')
    subject_id = fields.Many2one('school.subject', string='Subject')
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year')
    exam_date = fields.Date(string='Exam Date')
    total_marks = fields.Float(string='Total Marks', default=100.0)
    pass_marks = fields.Float(string='Pass Marks', default=40.0)
    result_ids = fields.One2many('school.exam.result', 'exam_id', string='Results')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('published', 'Published'),
    ], string='Status', default='draft', tracking=True)

    def action_schedule(self):
        for record in self:
            if record.state != 'draft':
                raise UserError(_('Only draft exams can be scheduled.'))
            record.state = 'scheduled'

    def action_complete(self):
        for record in self:
            if record.state != 'scheduled':
                raise UserError(_('Only scheduled exams can be completed.'))
            record.state = 'completed'

    def action_publish(self):
        for record in self:
            if record.state != 'completed':
                raise UserError(_('Only completed exams can be published.'))
            record.state = 'published'

    def action_reset_draft(self):
        for record in self:
            record.state = 'draft'

    def action_generate_results(self):
        self.ensure_one()
        if not self.class_id:
            raise UserError(_('Please set a class before generating results.'))
        students = self.class_id.student_ids.filtered(lambda s: s.state in ('enrolled', 'active'))
        existing_student_ids = self.result_ids.mapped('student_id').ids
        new_results = []
        for student in students:
            if student.id not in existing_student_ids:
                new_results.append({
                    'exam_id': self.id,
                    'student_id': student.id,
                    'marks_obtained': 0.0,
                })
        if new_results:
            self.env['school.exam.result'].create(new_results)
        return True
