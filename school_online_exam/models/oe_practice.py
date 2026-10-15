# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SchoolOePracticeSetting(models.Model):
    _name = 'school.oe.practice.setting'
    _description = 'Self-practice setting (per class and subject)'
    _order = 'class_id, subject_id'

    class_id = fields.Many2one('school.class', string='Class', required=True, ondelete='cascade')
    subject_id = fields.Many2one('school.subject', string='Subject', required=True, ondelete='cascade')
    practice_enabled = fields.Boolean(
        string='Practice Open', default=True,
        help="Self-practice is open for every class and subject by default. "
             "Add a line and untick this to close it for a class / subject.")

    _class_subject_uniq = models.Constraint(
        'UNIQUE(class_id, subject_id)', 'There is already a setting for this class and subject!')

    @api.model
    def is_practice_open(self, klass, subject):
        setting = self.sudo().search(
            [('class_id', '=', klass.id), ('subject_id', '=', subject.id)], limit=1)
        return setting.practice_enabled if setting else True
