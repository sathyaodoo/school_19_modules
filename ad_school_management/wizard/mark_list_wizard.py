from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SchoolMarkListWizard(models.TransientModel):
    """Report Card Generation: pick the students (directly, or by class /
    section / exam) and print their marks as a Mark List PDF."""
    _name = 'school.mark.list.wizard'
    _description = 'Print Mark List'

    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year')
    exam_id = fields.Many2one('school.exam', string='Exam',
                              help='Leave empty to include all exams.')
    class_id = fields.Many2one('school.class', string='Class')
    section_id = fields.Many2one('school.section', string='Section')
    subject_ids = fields.Many2many('school.subject', string='Subjects',
                                   help='Leave empty to include all subjects.')
    student_ids = fields.Many2many('school.student', string='Students',
                                   help='Leave empty to include every student matching the filters above.')
    result_status = fields.Selection(
        [('all', 'All'), ('pass', 'Passed only'), ('fail', 'Failed only')],
        string='Result', default='all', required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # Opened from the Students list with records selected
        if self.env.context.get('active_model') == 'school.student' and self.env.context.get('active_ids'):
            res['student_ids'] = [(6, 0, self.env.context['active_ids'])]
        return res

    @api.onchange('class_id')
    def _onchange_class_id(self):
        if self.section_id and self.section_id.class_id != self.class_id:
            self.section_id = False

    @api.onchange('academic_year_id')
    def _onchange_academic_year_id(self):
        if self.exam_id and self.academic_year_id and self.exam_id.academic_year_id != self.academic_year_id:
            self.exam_id = False

    def _get_result_domain(self):
        self.ensure_one()
        domain = []
        if self.student_ids:
            domain.append(('student_id', 'in', self.student_ids.ids))
        if self.academic_year_id:
            domain.append(('academic_year_id', '=', self.academic_year_id.id))
        if self.exam_id:
            domain.append(('exam_id', '=', self.exam_id.id))
        if self.class_id:
            domain.append(('class_id', '=', self.class_id.id))
        if self.section_id:
            domain.append(('section_id', '=', self.section_id.id))
        if self.subject_ids:
            domain.append(('subject_id', 'in', self.subject_ids.ids))
        if self.result_status != 'all':
            domain.append(('result_status', '=', self.result_status))
        return domain

    def action_print(self):
        self.ensure_one()
        results = self.env['school.exam.result'].search(self._get_result_domain())
        if not results:
            raise UserError(_("No exam results found for the selected students and filters."))
        return self.env.ref('ad_school_management.action_report_exam_mark_list').report_action(results)

    def action_view_results(self):
        """Show the matching results on screen (list / pivot / graph)."""
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('ad_school_management.action_school_exam_result')
        action['domain'] = self._get_result_domain()
        action['context'] = {'search_default_group_by_student': 1}
        return action