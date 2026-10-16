from odoo import models, fields, api, Command

class SchoolClass(models.Model):
    _name = 'school.class'
    _description = 'Class'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name'

    name = fields.Char(string='Class Name', required=True, tracking=True)
    code = fields.Char(string='Code', required=True, tracking=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)

    # old class-level Class Teacher: now set per section (see school.section). Kept only to move old data.
    class_teacher_id = fields.Many2one('school.teacher', string='Class Teacher (old)')
    teacher_ids = fields.Many2many('school.teacher', 'school_class_teacher_rel', 'class_id', 'teacher_id', string='Assigned Teachers')
    section_ids = fields.One2many('school.section', 'class_id', string='Sections')

    _code_uniq = models.Constraint(
        'unique(code)', 'The class code must be unique!'
    )

    @api.model
    def _migrate_class_teachers(self):
        # one-time move: old class-level Class Teacher -> every section of that class
        for cls in self.with_context(active_test=False).search([('class_teacher_id', '!=', False)]):
            if not cls.section_ids:
                continue
            for sec in cls.section_ids.filtered(lambda x: not x.class_teacher_id):
                sec.class_teacher_id = cls.class_teacher_id
            cls.class_teacher_id = False

    @api.model
    def _cleanup_class_teacher_links(self):
        # one-time: class teachers were earlier auto-added to the class "Teachers" list (class-wide access).
        # A class teacher stays there only if he/she also teaches a subject of that class.
        param = self.env['ir.config_parameter'].sudo()
        key = 'ad_school_management.class_teacher_cleanup_done'
        if param.get_param(key):
            return
        for cls in self.with_context(active_test=False).search([]):
            subject_teachers = self.env['school.subject'].search([('class_ids', 'in', cls.id)]).mapped('teacher_ids')
            for teacher in cls.section_ids.mapped('class_teacher_id'):
                if teacher in cls.teacher_ids and teacher not in subject_teachers:
                    cls.teacher_ids = [Command.unlink(teacher.id)]
        param.set_param(key, '1')