from odoo import models, fields, api, _, Command
from odoo.exceptions import ValidationError

class SchoolSubject(models.Model):
    _name = 'school.subject'
    _description = 'Subject'
    _order = 'name'

    name = fields.Char(string='Subject Name', required=True)
    code = fields.Char(string='Code', required=True)
    class_ids = fields.Many2many('school.class', 'school_subject_class_rel', 'subject_id', 'class_id', string='Classes')
    teacher_ids = fields.Many2many('school.teacher', 'school_subject_teacher_rel', 'subject_id', 'teacher_id', string='Teachers')
    credits = fields.Float(string='Credits', default=1.0)

    _code_uniq = models.Constraint(
        'unique(code)', 'The subject code must be unique!'
    )
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_teacher_classes()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'class_ids' in vals or 'teacher_ids' in vals:
            self._sync_teacher_classes()
        return res

    def _sync_teacher_classes(self):
        # teachers of a subject are also assigned to the classes of that subject,
        # so the classes show in the teacher's Assigned Classes
        for subject in self:
            for cls in subject.class_ids:
                missing = subject.teacher_ids - cls.teacher_ids
                if missing:
                    cls.sudo().teacher_ids = [Command.link(t.id) for t in missing]

    @api.model
    def _sync_all_teacher_classes(self):
        # run on upgrade: fix subjects that already have classes and teachers
        self.with_context(active_test=False).search([])._sync_teacher_classes()
    @api.constrains('credits')
    def _check_credits(self):
        for subject in self:
            if subject.credits <= 0:
                raise ValidationError(_("Subject credits must be greater than zero!"))
