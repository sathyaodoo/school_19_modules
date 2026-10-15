# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .oe_logic import OPTION_KEYS


class SchoolOeChapter(models.Model):
    _name = 'school.oe.chapter'
    _description = 'Online Exam Chapter'
    _order = 'class_id, subject_id, sequence, name'

    name = fields.Char(string='Chapter', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    class_id = fields.Many2one('school.class', string='Class', required=True, ondelete='cascade')
    subject_id = fields.Many2one('school.subject', string='Subject', required=True, ondelete='cascade')
    topic_ids = fields.One2many('school.oe.topic', 'chapter_id', string='Topics')
    question_count = fields.Integer(string='Questions', compute='_compute_question_count')

    _name_scope_uniq = models.Constraint(
        'UNIQUE(class_id, subject_id, name)',
        'This chapter already exists for the class and subject!')

    def _compute_question_count(self):
        Question = self.env['school.oe.question']
        for rec in self:
            rec.question_count = Question.search_count([('chapter_id', '=', rec.id)])


class SchoolOeTopic(models.Model):
    _name = 'school.oe.topic'
    _description = 'Online Exam Topic'
    _order = 'chapter_id, sequence, name'

    name = fields.Char(string='Topic', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    chapter_id = fields.Many2one('school.oe.chapter', string='Chapter', required=True, ondelete='cascade')
    class_id = fields.Many2one(related='chapter_id.class_id', store=True, string='Class')
    subject_id = fields.Many2one(related='chapter_id.subject_id', store=True, string='Subject')
    question_count = fields.Integer(string='Questions', compute='_compute_question_count')

    _name_chapter_uniq = models.Constraint(
        'UNIQUE(chapter_id, name)', 'This topic already exists in the chapter!')

    def _compute_question_count(self):
        Question = self.env['school.oe.question']
        for rec in self:
            rec.question_count = Question.search_count([('topic_id', '=', rec.id)])


class SchoolOeQuestion(models.Model):
    _name = 'school.oe.question'
    _description = 'Online Exam Question (Question Bank)'
    _order = 'class_id, subject_id, chapter_id, id'

    name = fields.Text(string='Question', required=True)
    active = fields.Boolean(default=True)
    class_id = fields.Many2one('school.class', string='Class', required=True, index=True)
    subject_id = fields.Many2one('school.subject', string='Subject', required=True, index=True)
    chapter_id = fields.Many2one(
        'school.oe.chapter', string='Chapter', index=True,
        domain="[('class_id', '=', class_id), ('subject_id', '=', subject_id)]")
    topic_id = fields.Many2one(
        'school.oe.topic', string='Topic', index=True,
        domain="[('chapter_id', '=', chapter_id)]")
    option_a = fields.Char(string='Option A', required=True)
    option_b = fields.Char(string='Option B', required=True)
    option_c = fields.Char(string='Option C')
    option_d = fields.Char(string='Option D')
    correct_option = fields.Selection(
        [('a', 'A'), ('b', 'B'), ('c', 'C'), ('d', 'D')],
        string='Correct Answer', required=True)
    marks = fields.Float(string='Marks', default=1.0, required=True)
    difficulty = fields.Selection(
        [('easy', 'Easy'), ('medium', 'Medium'), ('hard', 'Hard')],
        string='Difficulty', default='medium')
    explanation = fields.Text(string='Explanation (shown after the exam)')

    @api.depends('name')
    def _compute_display_name(self):
        for rec in self:
            text = (rec.name or '').strip().replace('\n', ' ')
            rec.display_name = text[:80] + ('...' if len(text) > 80 else '')

    @api.onchange('class_id', 'subject_id')
    def _onchange_scope(self):
        for rec in self:
            if rec.chapter_id and (rec.chapter_id.class_id != rec.class_id
                                   or rec.chapter_id.subject_id != rec.subject_id):
                rec.chapter_id = False
                rec.topic_id = False

    @api.onchange('chapter_id')
    def _onchange_chapter(self):
        for rec in self:
            if rec.topic_id and rec.topic_id.chapter_id != rec.chapter_id:
                rec.topic_id = False

    @api.constrains('correct_option', 'option_a', 'option_b', 'option_c', 'option_d')
    def _check_options(self):
        for rec in self:
            if not getattr(rec, 'option_%s' % rec.correct_option):
                raise ValidationError(_(
                    "The correct answer (%s) must have option text.",
                    rec.correct_option.upper()))
            if rec.option_d and not rec.option_c:
                raise ValidationError(_("Fill option C before option D."))

    @api.constrains('chapter_id', 'topic_id', 'class_id', 'subject_id')
    def _check_scope(self):
        for rec in self:
            if rec.chapter_id and (rec.chapter_id.class_id != rec.class_id
                                   or rec.chapter_id.subject_id != rec.subject_id):
                raise ValidationError(_("The chapter does not belong to the selected class and subject."))
            if rec.topic_id and rec.topic_id.chapter_id != rec.chapter_id:
                raise ValidationError(_("The topic does not belong to the selected chapter."))

    @api.constrains('marks')
    def _check_marks(self):
        for rec in self:
            if rec.marks <= 0:
                raise ValidationError(_("Marks must be greater than zero."))

    def get_option_keys(self):
        """Option keys that actually have text, in A-D order."""
        self.ensure_one()
        return [k for k in OPTION_KEYS if getattr(self, 'option_%s' % k)]
