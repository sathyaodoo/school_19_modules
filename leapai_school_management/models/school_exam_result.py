# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class SchoolExamResult(models.Model):
    _name = 'school.exam.result'
    _description = 'Exam Result'
    _order = 'exam_id, student_id'

    exam_id = fields.Many2one('school.exam', string='Exam', required=True, ondelete='cascade')
    student_id = fields.Many2one('school.student', string='Student', required=True)
    marks_obtained = fields.Float(string='Marks Obtained')
    grade = fields.Char(string='Grade', compute='_compute_grade_percentage', store=True)
    percentage = fields.Float(string='Percentage', compute='_compute_grade_percentage', store=True)
    result_state = fields.Selection([
        ('pass', 'Pass'),
        ('fail', 'Fail'),
    ], string='Result', compute='_compute_grade_percentage', store=True)
    remarks = fields.Char(string='Remarks')

    _student_exam_uniq = models.Constraint('UNIQUE(exam_id, student_id)', 'A student can only have one result per exam!')

    @api.depends('marks_obtained', 'exam_id.total_marks', 'exam_id.pass_marks')
    def _compute_grade_percentage(self):
        for record in self:
            total = record.exam_id.total_marks or 100.0
            pass_marks = record.exam_id.pass_marks or 40.0
            marks = record.marks_obtained or 0.0
            percentage = (marks / total * 100) if total else 0.0
            record.percentage = percentage
            if marks < pass_marks:
                record.grade = 'F'
                record.result_state = 'fail'
            elif percentage >= 90:
                record.grade = 'A+'
                record.result_state = 'pass'
            elif percentage >= 80:
                record.grade = 'A'
                record.result_state = 'pass'
            elif percentage >= 70:
                record.grade = 'B+'
                record.result_state = 'pass'
            elif percentage >= 60:
                record.grade = 'B'
                record.result_state = 'pass'
            elif percentage >= 50:
                record.grade = 'C'
                record.result_state = 'pass'
            elif percentage >= 40:
                record.grade = 'D'
                record.result_state = 'pass'
            else:
                record.grade = 'F'
                record.result_state = 'fail'
