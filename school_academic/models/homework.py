# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SchoolOeAssignment(models.Model):
    """Homework is an Online Exam assignment of the type 'Homework', tied to a class diary entry.
    Upload, submit, teacher marks and feedback are the ones that already exist for assignments."""
    _inherit = 'school.oe.assignment'

    kind = fields.Selection(selection_add=[('homework', 'Homework')], ondelete={'homework': 'set default'})
    diary_id = fields.Many2one('school.class.diary', string='Class Diary Entry', ondelete='set null', index=True)
    outcome_ids = fields.Many2many('school.learning.outcome', 'school_oe_assignment_outcome_rel',
                                   'assignment_id', 'outcome_id', string='Learning Outcomes')

    @api.model
    def _diary_for(self, class_id, subject_id, section_id, day):
        """The class diary entry of that class + subject + day (of the same section, or of every section)."""
        diaries = self.env['school.class.diary'].sudo().search(
            [('class_id', '=', class_id), ('subject_id', '=', subject_id), ('date', '=', day)],
            order='period_no desc, id desc')
        return diaries.filtered(lambda d: not section_id or not d.section_id or d.section_id.id == section_id)[:1]

    @api.model_create_multi
    def create(self, vals_list):
        today = fields.Date.context_today(self)
        for vals in vals_list:                       # homework given today joins today's diary entry by itself
            if vals.get('kind') == 'homework' and not vals.get('diary_id') and vals.get('class_id') and vals.get('subject_id'):
                diary = self._diary_for(vals['class_id'], vals['subject_id'], vals.get('section_id'), today)
                if diary:
                    vals['diary_id'] = diary.id
        return super().create(vals_list)

    @api.onchange('kind', 'class_id', 'section_id', 'subject_id')
    def _onchange_homework_diary(self):
        if self.kind == 'homework' and not self.diary_id and self.class_id and self.subject_id:
            diary = self._diary_for(self.class_id.id, self.subject_id.id, self.section_id.id,
                                    fields.Date.context_today(self))
            if diary:
                self.diary_id = diary

    @api.constrains('diary_id', 'class_id', 'subject_id')
    def _check_diary(self):
        for work in self:
            diary = work.diary_id
            if diary and (diary.class_id != work.class_id or diary.subject_id != work.subject_id):
                raise ValidationError(_("The class diary entry is for another class or subject."))
