# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

BLOOM_LEVELS = [
    ('remember', 'Remember'), ('understand', 'Understand'), ('apply', 'Apply'),
    ('analyse', 'Analyse'), ('evaluate', 'Evaluate'), ('create', 'Create'),
]


class SchoolLearningOutcome(models.Model):
    """What a student must be able to do after a unit / topic ("I can count up to 100")."""
    _name = 'school.learning.outcome'
    _description = 'Learning outcome'
    _order = 'syllabus_id, sequence, id'

    syllabus_id = fields.Many2one('school.syllabus', string='Syllabus', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    code = fields.Char(string='Code', help="Short code, for example LO1 or MA.1.2")
    name = fields.Char(string='Outcome', required=True, help="Write it as a student can do: 'Counts objects up to 100'")
    description = fields.Text(string='Details')
    bloom_level = fields.Selection(BLOOM_LEVELS, string='Thinking Level', default='understand', required=True)
    unit_id = fields.Many2one('school.syllabus.unit', string='Unit', domain="[('syllabus_id', '=', syllabus_id)]")
    topic_id = fields.Many2one('school.syllabus.topic', string='Topic', domain="[('syllabus_id', '=', syllabus_id)]")

    class_id = fields.Many2one(related='syllabus_id.class_id', store=True, string='Class')
    subject_id = fields.Many2one(related='syllabus_id.subject_id', store=True, string='Subject')
    academic_year_id = fields.Many2one(related='syllabus_id.academic_year_id', store=True, string='Academic Year')
    syllabus_state = fields.Selection(related='syllabus_id.state', store=True, string='Syllabus Status')
    teacher_user_id = fields.Many2one(related='syllabus_id.teacher_user_id', store=True, string='Teacher Login')

    diary_ids = fields.Many2many('school.class.diary', 'school_diary_outcome_rel', 'outcome_id', 'diary_id',
                                 string='Taught in Diary')
    taught_count = fields.Integer(compute='_compute_taught', store=True, string='Times Taught')
    covered = fields.Boolean(compute='_compute_taught', store=True, string='Covered')

    @api.depends('diary_ids.state')
    def _compute_taught(self):
        for outcome in self:
            count = len(outcome.diary_ids.filtered(lambda d: d.state == 'published'))
            outcome.taught_count = count
            outcome.covered = count > 0

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for outcome in self:
            outcome.display_name = ('%s - %s' % (outcome.code, outcome.name)) if outcome.code else (outcome.name or '')

    @api.constrains('syllabus_id', 'unit_id', 'topic_id')
    def _check_links(self):
        for outcome in self:
            if outcome.unit_id and outcome.unit_id.syllabus_id != outcome.syllabus_id:
                raise ValidationError(_("The unit does not belong to this syllabus."))
            if outcome.topic_id:
                if outcome.topic_id.syllabus_id != outcome.syllabus_id:
                    raise ValidationError(_("The topic does not belong to this syllabus."))
                if outcome.unit_id and outcome.topic_id.unit_id != outcome.unit_id:
                    raise ValidationError(_("The topic is not in the selected unit."))

    @api.onchange('topic_id')
    def _onchange_topic(self):
        if self.topic_id and not self.unit_id:
            self.unit_id = self.topic_id.unit_id

    # the outcomes are part of the syllabus structure: same lock as units and topics
    @api.model_create_multi
    def create(self, vals_list):
        self.env['school.syllabus'].browse([v['syllabus_id'] for v in vals_list if v.get('syllabus_id')])._check_editable()
        return super().create(vals_list)

    def write(self, vals):
        self.mapped('syllabus_id')._check_editable()
        return super().write(vals)

    def unlink(self):
        self.mapped('syllabus_id')._check_editable()
        return super().unlink()
