from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SchoolStaffResignation(models.Model):
    _name = 'school.staff.resignation'
    _description = 'Staff Resignation & Handover Process'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'submitted_date desc, id desc'
    _rec_name = 'employee_id'

    # --- Step 1: Letter -----------------------------------------------
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, tracking=True,
        ondelete='cascade', default=lambda self: self._default_employee_id(),
    )
    letter_content = fields.Text(string='Resignation Letter', tracking=True)
    letter_attachment = fields.Binary(string='Scanned Letter (optional)')
    letter_attachment_filename = fields.Char(string='Attachment Filename')
    submitted_date = fields.Date(string='Date of Resignation', tracking=True)

    # --- Resignation Request Form: STANDARD fields ----------------------
    # Pulled straight from hr.employee — no new data entry, just display.
    #employee_code = fields.Char(related='employee_id.teacher_code', string='Employee ID', store=True, readonly=True,)
    department_id = fields.Many2one(
        related='employee_id.department_id', string='Department', store=True, readonly=True,
    )
    job_id = fields.Many2one(
        related='employee_id.job_id', string='Designation', store=True, readonly=True,
    )

    # --- Resignation Request Form: CUSTOM fields -------------------------
    reason_for_resignation = fields.Selection(
        [
            ('better_opportunity', 'Better Opportunity'),
            ('personal', 'Personal Reasons'),
            ('health', 'Health Reasons'),
            ('relocation', 'Relocation'),
            ('higher_studies', 'Higher Studies'),
            ('retirement', 'Retirement'),
            ('other', 'Other'),
        ],
        string='Reason for Resignation', tracking=True,
    )
    reason_details = fields.Text(string='Reason Details')

    last_working_day = fields.Date(string='Last Working Day', tracking=True)

    minimum_notice_date = fields.Date(
        string='Minimum Notice Date (90 Days)', compute='_compute_minimum_notice_date',
    )
    notice_period_met = fields.Boolean(
        string='Notice Period Met (>= 90 Days)', compute='_compute_notice_period_met',
    )

    @api.depends()
    def _compute_minimum_notice_date(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.minimum_notice_date = today + relativedelta(days=90)

    @api.depends('last_working_day')
    def _compute_notice_period_met(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.notice_period_met = bool(
                rec.last_working_day and (rec.last_working_day - today).days >= 90
            )

    # --- Overall status (step 9 in the spec) ---------------------------
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
            ('approved', 'Approved'),
            ('notice_period', 'Notice Period'),
            ('handover', 'Handover'),
            ('settled', 'Settled'),
        ],
        string='Status', default='draft', required=True, tracking=True,
    )
    exit_done = fields.Boolean(string='Exit Processed', tracking=True, copy=False)

    # --- Step 2: Principal approval (1st level) -------------------------
    principal_approved = fields.Boolean(string='Principal Approved', copy=False)
    principal_approved_by = fields.Many2one('res.users', string='Approved By (Principal)', copy=False)
    principal_approved_date = fields.Datetime(string='Principal Approval Date', copy=False)

    # --- Step 3: HR Manager approval (2nd level) -------------------------
    hr_approved = fields.Boolean(string='HR Manager Approved', copy=False)
    hr_approved_by = fields.Many2one('res.users', string='Approved By (HR Manager)', copy=False)
    hr_approved_date = fields.Datetime(string='HR Approval Date', copy=False)

    # --- Step 4: Notice period (minimum 3 months, mandatory) -----------
    notice_period_start = fields.Date(string='Notice Period Start')
    notice_period_end = fields.Date(string='Notice Period End', compute='_compute_notice_period_end', store=True)

    # --- Step 5: Handover checklist -------------------------------------
    handover_student_register = fields.Boolean(string='Student Register Handed Over')
    handover_study_materials = fields.Boolean(string='Study Materials Handed Over')
    handover_reports = fields.Boolean(string='Reports Handed Over')
    handover_id_card = fields.Boolean(string='ID Card Returned')

    # --- Step 6: Manager verification -----------------------------------
    handover_verified = fields.Boolean(string='Handover Verified', copy=False)
    handover_verified_by = fields.Many2one('res.users', string='Verified By', copy=False)
    handover_verified_date = fields.Datetime(string='Verification Date', copy=False)

    # --- Step 7: Settlement ----------------------------------------------
    currency_id = fields.Many2one(
        'res.currency', string='Currency', default=lambda self: self.env.company.currency_id,
    )
    settlement_amount = fields.Monetary(string='Final Settlement Amount', currency_field='currency_id')
    settlement_processed = fields.Boolean(string='Settlement Processed', copy=False)
    settlement_processed_date = fields.Datetime(string='Settlement Date', copy=False)

    # --- Exit Interview(s) linked to this resignation -------------------
    exit_interview_ids = fields.One2many(
        'school.exit.interview', 'resignation_id', string='Exit Interviews',
    )
    exit_interview_count = fields.Integer(
        string='Exit Interview Count', compute='_compute_exit_interview_count',
    )

    @api.depends('exit_interview_ids')
    def _compute_exit_interview_count(self):
        for rec in self:
            rec.exit_interview_count = len(rec.exit_interview_ids)

    @api.model
    def _default_employee_id(self):
        employee = self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)
        return employee.id if employee else False

    @api.depends('notice_period_start')
    def _compute_notice_period_end(self):
        for rec in self:
            # Minimum 3 months' notice is MANDATORY — always exactly
            # start + 3 months, not user-editable to something shorter.
            rec.notice_period_end = (
                rec.notice_period_start + relativedelta(months=3)
                if rec.notice_period_start else False
            )

    # ------------------------------------------------------------------
    # Step 1: Letter
    # ------------------------------------------------------------------
    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only a Draft resignation letter can be submitted."))
            if not rec.letter_content:
                raise UserError(_("Please write the resignation letter before submitting."))
            if not rec.reason_for_resignation:
                raise UserError(_("Please select a Reason for Resignation before submitting."))
            if not rec.last_working_day:
                raise UserError(_("Please enter a proposed Last Working Day before submitting."))
            if not rec.notice_period_met:
                raise UserError(_(
                    "Last Working Day must be at least 90 days (3 months) from today. "
                    "The earliest allowed date is %s."
                ) % rec.minimum_notice_date)
            rec.write({
                'state': 'submitted',
                'submitted_date': fields.Date.context_today(rec),
            })

    # ------------------------------------------------------------------
    # Step 2: Principal approval — button restricted in the view to
    # group_school_admin / group_school_principal, and re-checked here
    # server-side so it can't be bypassed by calling the method directly.
    # ------------------------------------------------------------------
    def action_principal_approve(self):
        for rec in self:
            if not (self.env.user.has_group('ad_school_management.group_school_admin')
                    or self.env.user.has_group('ad_school_management.group_school_principal')):
                raise UserError(_("Only the Principal or an Administrator can give this approval."))
            if rec.state != 'submitted':
                raise UserError(_("Only a Submitted resignation can be approved by the Principal."))
            rec.write({
                'principal_approved': True,
                'principal_approved_by': self.env.uid,
                'principal_approved_date': fields.Datetime.now(),
            })
            rec._check_fully_approved()

    # ------------------------------------------------------------------
    # Step 3: HR Manager approval — button restricted in the view to
    # group_school_admin / group_school_hr_manager, re-checked here too.
    # ------------------------------------------------------------------
    def action_hr_approve(self):
        for rec in self:
            if not (self.env.user.has_group('ad_school_management.group_school_admin')
                    or self.env.user.has_group('ad_school_management.group_school_hr_manager')):
                raise UserError(_("Only the HR Manager or an Administrator can give this approval."))
            if rec.state != 'submitted':
                raise UserError(_("Only a Submitted resignation can be approved by HR."))
            if not rec.principal_approved:
                raise UserError(_(
                    "The Principal must approve this resignation before HR Manager approval is allowed."
                ))
            rec.write({
                'hr_approved': True,
                'hr_approved_by': self.env.uid,
                'hr_approved_date': fields.Datetime.now(),
            })
            rec._check_fully_approved()

    def _check_fully_approved(self):
        for rec in self:
            if rec.principal_approved and rec.hr_approved and rec.state == 'submitted':
                rec.state = 'approved'

    # ------------------------------------------------------------------
    # Step 4: Notice period
    # ------------------------------------------------------------------
    def action_start_notice_period(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_("Notice period can only start once BOTH the Principal and HR Manager have approved."))
            rec.write({
                'notice_period_start': fields.Date.context_today(rec),
                'state': 'notice_period',
            })

    # ------------------------------------------------------------------
    # Step 5: Move into Handover once the notice period is running
    # ------------------------------------------------------------------
    def action_start_handover(self):
        for rec in self:
            if rec.state != 'notice_period':
                raise UserError(_("Handover can only start once the Notice Period stage has begun."))
            rec.state = 'handover'

    # ------------------------------------------------------------------
    # Step 6: Manager verification of the handover checklist
    # ------------------------------------------------------------------
    def action_verify_handover(self):
        for rec in self:
            if rec.state != 'handover':
                raise UserError(_("Only a resignation in the Handover stage can be verified."))
            missing = []
            if not rec.handover_student_register:
                missing.append(_("Student Register"))
            if not rec.handover_study_materials:
                missing.append(_("Study Materials"))
            if not rec.handover_reports:
                missing.append(_("Reports"))
            if not rec.handover_id_card:
                missing.append(_("ID Card"))
            if missing:
                raise UserError(_(
                    "Please complete the full handover checklist before verifying. Still pending: %s"
                ) % ", ".join(missing))
            rec.write({
                'handover_verified': True,
                'handover_verified_by': self.env.uid,
                'handover_verified_date': fields.Datetime.now(),
            })

    # ------------------------------------------------------------------
    # Step 7: Settlement
    # ------------------------------------------------------------------
    def action_process_settlement(self):
        for rec in self:
            if rec.state != 'handover' or not rec.handover_verified:
                raise UserError(_("Handover must be verified before processing the final settlement."))
            if rec.settlement_amount <= 0:
                raise UserError(_("Please enter the final settlement amount before processing it."))
            rec.write({
                'settlement_processed': True,
                'settlement_processed_date': fields.Datetime.now(),
                'state': 'settled',
            })

    # ------------------------------------------------------------------
    # Step 8: Exit — STANDARD Odoo functionality (archiving), just
    # wired up here for a smooth one-click workflow from this record.
    # ------------------------------------------------------------------
    def action_mark_exit(self):
        for rec in self:
            if rec.state != 'settled':
                raise UserError(_("The employee can only be exited after final settlement is processed."))
            rec.employee_id.action_archive()  # standard Odoo archiving (active = False)
            rec.exit_done = True

    # ------------------------------------------------------------------
    # Exit Interview — conducted as part of Step 8 (Exit). Restricted to
    # Admin/HR Manager in the view (see the button below); creates one
    # exit.interview record (auto-sequenced EXIT/YYYY/NNN) linked back to
    # this resignation, and opens it directly for HR to fill in.
    # ------------------------------------------------------------------
    def action_conduct_exit_interview(self):
        self.ensure_one()
        if not (self.env.user.has_group('ad_school_management.group_school_admin')
                or self.env.user.has_group('ad_school_management.group_school_hr_manager')):
            raise UserError(_("Only the HR Manager or an Administrator can conduct an exit interview."))
        interview = self.env['school.exit.interview'].create({
            'resignation_id': self.id,
        })
        return {
            'name': _('Exit Interview'),
            'type': 'ir.actions.act_window',
            'res_model': 'school.exit.interview',
            'res_id': interview.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_exit_interviews(self):
        self.ensure_one()
        return {
            'name': _('Exit Interviews'),
            'type': 'ir.actions.act_window',
            'res_model': 'school.exit.interview',
            'view_mode': 'list,form',
            'domain': [('resignation_id', '=', self.id)],
            'context': {'default_resignation_id': self.id},
        }