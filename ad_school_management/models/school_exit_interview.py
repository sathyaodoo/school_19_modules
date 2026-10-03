from odoo import models, fields, api, _


class SchoolExitInterview(models.Model):
    _name = 'school.exit.interview'
    _description = 'Staff Exit Interview'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'interview_date desc, id desc'
    _rec_name = 'name'

    # --- Row 10: Exit Interview ID — auto-sequence EXIT/2026/001 -------
    name = fields.Char(
        string='Exit Interview ID', required=True, copy=False, readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('school.exit.interview') or _('New'),
    )

    # --- Row 11: Resignation ID — link to resignation record -----------
    resignation_id = fields.Many2one(
        'school.staff.resignation', string='Resignation', required=True,
        ondelete='cascade', tracking=True,
    )

    # --- Row 12: Employee Name — auto-filled from resignation ----------
    employee_id = fields.Many2one(
        related='resignation_id.employee_id', string='Employee',
        store=True, readonly=True,
    )

    # --- Row 13: Interview Date — when exit interview conducted --------
    interview_date = fields.Date(
        string='Interview Date', default=fields.Date.context_today, tracking=True,
    )

    # --- Row 14: Conducted By — HR Manager conducting -------------------
    # Restricted to HR Manager + Admin. Built using has_group() — a
    # stable PUBLIC METHOD on res.users, not an internal many2many field
    # name — since this build has renamed both res.users.groups_id and
    # res.groups.users, guessing a third internal field name isn't safe.
    # has_group() is core Odoo API used everywhere and won't be renamed.
    conducted_by = fields.Many2one(
        'res.users', string='Conducted By', tracking=True,
        default=lambda self: self._default_conducted_by(),
        domain=lambda self: [('id', 'in', self._get_allowed_conducted_by_user_ids())],
    )

    @api.model
    def _get_allowed_conducted_by_user_ids(self):
        users = self.env['res.users'].search([('active', '=', True)])
        return [
            u.id for u in users
            if u.has_group('ad_school_management.group_school_hr_manager')
            or u.has_group('ad_school_management.group_school_admin')
        ]

    def _default_conducted_by(self):
        # Only pre-fill with the current user if THEY are actually an HR
        # Manager — e.g. when Admin creates the record on HR's behalf,
        # leave it blank rather than pre-filling a name outside the
        # field's own allowed domain (Admin is not "HR Manager team").
        if self.env.user.has_group('ad_school_management.group_school_hr_manager'):
            return self.env.uid
        return False

    # --- Row 15: Reasons for Leaving ------------------------------------
    reasons_for_leaving = fields.Text(string='Reasons for Leaving')

    # --- Row 16: Overall Experience: Excellent/Good/Fair/Poor -----------
    overall_experience = fields.Selection(
        [
            ('excellent', '😄 Excellent'),
            ('good', '🙂 Good'),
            ('fair', '😐 Fair'),
            ('poor', '😞 Poor'),
        ],
        string='Overall Experience', tracking=True,
    )

    # --- Row 17: Management Feedback -------------------------------------
    management_feedback = fields.Text(string='Feedback on Management')

    # --- Row 18: Facility Feedback ----------------------------------------
    facility_feedback = fields.Text(string='Feedback on Facilities')

    # --- Row 19: Improvement Suggestions ----------------------------------
    improvement_suggestions = fields.Text(string='Suggestions for School')

    # --- Row 20: Confidential Notes — HR-only notes -----------------------
    # Restricted at the FIELD level (view groups=) as well as the model
    # level (ir.model.access.csv only grants Admin/HR Manager any access
    # to this model at all), so this is doubly protected — even if the
    # model's access were ever loosened, this one field stays HR-only.
    confidential_notes = fields.Text(string='Confidential Notes (HR Only)')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('school.exit.interview') or _('New')
        return super().create(vals_list)