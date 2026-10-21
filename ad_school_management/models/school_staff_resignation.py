from dateutil.relativedelta import relativedelta

from markupsafe import Markup

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_date


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
        # Pipeline (kanban) shows every stage as a column, even when empty.
        group_expand='_group_expand_states',
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
    # Both dates are editable during Notice Period / Handover. Changing the
    # start proposes start + 3 months as the end; the end can then be moved
    # later, but never earlier than 3 months after the start (mandatory).
    notice_period_start = fields.Date(string='Notice Period Start', tracking=True)
    # The end of the notice period is the employee's last working day.
    notice_period_end = fields.Date(
        string='Notice Period End (Last Working Day)', compute='_compute_notice_period_end',
        store=True, readonly=False, tracking=True)

    # --- Skip Notice Period: move on without serving the 3-month notice --
    notice_waived = fields.Boolean(
        string='Notice Period Skipped', readonly=True, copy=False, tracking=True,
        help='The employee did not serve the full 3-month notice period (for example an '
             'emergency). Set with the "Skip Notice Period" button, with a reason.')
    notice_waiver_reason = fields.Text(string='Reason for Skipping Notice Period', readonly=True, copy=False)
    notice_waived_by = fields.Many2one('res.users', string='Skip Approved By', readonly=True, copy=False)
    notice_waived_date = fields.Datetime(string='Skip Approved On', readonly=True, copy=False)

    # --- Step 5: Handover checklist -------------------------------------
    handover_student_register = fields.Boolean(string='Student Register Handed Over')
    handover_study_materials = fields.Boolean(string='Study Materials Handed Over')
    handover_reports = fields.Boolean(string='Reports Handed Over')
    handover_id_card = fields.Boolean(string='ID Card Returned')

    # --- Step 6: Manager verification -----------------------------------
    handover_verified = fields.Boolean(string='Handover Verified', copy=False)
    handover_verified_by = fields.Many2one('res.users', string='Verified By', copy=False)
    handover_verified_date = fields.Datetime(string='Verification Date', copy=False)
    # Items that were NOT handed over but accepted by the verifier, with the
    # reason (e.g. non-teaching staff have no study materials / register).
    handover_not_applicable = fields.Char(string='Not Handed Over (Accepted)', readonly=True, copy=False)
    # Summary of all reasons ("Item: reason" per line), kept for the chatter
    # and for records verified before per-item reasons existed.
    handover_exception_reason = fields.Text(string='Reason (Items Not Handed Over)', readonly=True, copy=False)
    # One reason per checklist item that was NOT handed over (shown next to it).
    handover_student_register_reason = fields.Char(
        string='Reason: Student Register Not Handed Over', readonly=True, copy=False)
    handover_study_materials_reason = fields.Char(
        string='Reason: Study Materials Not Handed Over', readonly=True, copy=False)
    handover_reports_reason = fields.Char(
        string='Reason: Reports Not Handed Over', readonly=True, copy=False)
    handover_id_card_reason = fields.Char(
        string='Reason: ID Card Not Returned', readonly=True, copy=False)
    is_teaching_staff = fields.Boolean(
        string='Teaching Staff', compute='_compute_is_teaching_staff',
        help='The employee has a teacher profile. Non-teaching staff usually have no study '
             'materials or student register to hand over.')

    @api.depends('employee_id.teacher_id')
    def _compute_is_teaching_staff(self):
        for rec in self:
            rec.is_teaching_staff = bool(rec.employee_id.teacher_id)

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

    # --- Pipeline (kanban) helpers --------------------------------------
    @api.model
    def _group_expand_states(self, states, domain):
        """Every stage is a pipeline column, in workflow order, even when empty."""
        return [key for key, _label in self._fields['state'].selection]

    color = fields.Integer(string='Color Index')
    employee_image = fields.Image(related='employee_id.avatar_128', string='Employee Photo')
    pipeline_next_step = fields.Char(
        string='Next Step', compute='_compute_pipeline_next_step',
        help='What has to happen for this resignation to move to the next stage.')

    @api.depends('state', 'principal_approved', 'hr_approved', 'handover_verified',
                 'settlement_processed', 'exit_done', 'exit_interview_ids')
    def _compute_pipeline_next_step(self):
        for rec in self:
            if rec.state == 'draft':
                step = _("Employee to submit the letter")
            elif rec.state == 'submitted':
                step = (_("Waiting for HR Manager approval") if rec.principal_approved
                        else _("Waiting for Principal approval"))
            elif rec.state == 'approved':
                step = _("Start the notice period")
            elif rec.state == 'notice_period':
                step = _("Start the handover")
            elif rec.state == 'handover':
                step = (_("Process the final settlement") if rec.handover_verified
                        else _("Complete & verify the handover checklist"))
            elif not rec.exit_done:
                step = _("Mark the employee as left")
            elif not rec.exit_interview_ids:
                step = _("Conduct the exit interview")
            else:
                step = _("Completed")
            rec.pipeline_next_step = step

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
        # Proposed end = start + 3 months (recomputed when the start changes);
        # the user may then move it later (see _check_notice_period_dates).
        for rec in self:
            rec.notice_period_end = (
                rec.notice_period_start + relativedelta(months=3)
                if rec.notice_period_start else False
            )

    @api.constrains('notice_period_start', 'notice_period_end', 'notice_waived')
    def _check_notice_period_dates(self):
        for rec in self:
            if not rec.notice_period_start or not rec.notice_period_end:
                continue
            if rec.notice_period_end < rec.notice_period_start:
                raise ValidationError(_("The last working day cannot be before the notice period start."))
            if rec.notice_waived:
                continue  # notice period skipped: shorter notice approved, with a reason
            minimum_end = rec.notice_period_start + relativedelta(months=3)
            if rec.notice_period_end < minimum_end:
                raise ValidationError(_(
                    "The notice period is at least 3 months (mandatory). For a start on %(start)s, "
                    "the last working day cannot be before %(minimum)s.\n\n"
                    "If the employee cannot serve the notice period, use the "
                    "\"Skip Notice Period\" button and give the reason.",
                    start=format_date(self.env, rec.notice_period_start),
                    minimum=format_date(self.env, minimum_end)))

    # ------------------------------------------------------------------
    # Pipeline: click a stage in the status bar, or drag a card in the
    # kanban, to move FORWARD or BACKWARD to any stage.
    # ------------------------------------------------------------------
    _PIPELINE_BACK_GROUPS = (
        'ad_school_management.group_school_admin',
        'ad_school_management.group_school_hr_manager',
        'ad_school_management.group_school_principal',
    )

    def write(self, vals):
        """A stage change that does not come from a workflow button (status bar
        click, kanban drag, import) is routed through the workflow:
        forward runs every step's button with its checks, backward resets the
        data of the stages that are undone."""
        if 'state' not in vals or self.env.context.get('resignation_workflow'):
            return super().write(vals)
        target = vals['state']
        other_vals = {key: value for key, value in vals.items() if key != 'state'}
        if other_vals:
            super().write(other_vals)
        for rec in self.filtered(lambda r: r.state != target):
            rec._pipeline_move_to(target)
        return True

    def _pipeline_stages(self):
        return [key for key, _label in self._fields['state'].selection]

    def _pipeline_move_to(self, target):
        self.ensure_one()
        stages = self._pipeline_stages()
        if stages.index(target) > stages.index(self.state):
            self._pipeline_forward(target)
        else:
            self._pipeline_back(target)

    def _pipeline_forward(self, target):
        """Run each step between the current stage and the target, exactly as
        if the buttons had been clicked one after the other. If one step's
        rules are not met, its error is shown and nothing is changed."""
        labels = dict(self._fields['state']._description_selection(self.env))
        while self.state != target:
            current = self.state
            if current == 'draft':
                self.action_submit()
            elif current == 'submitted':
                if not self.principal_approved:
                    self.action_principal_approve()
                if not self.hr_approved:
                    self.action_hr_approve()
            elif current == 'approved':
                self.action_start_notice_period()
            elif current == 'notice_period':
                self.action_start_handover()
            elif current == 'handover':
                if not self.handover_verified:
                    pending = self._handover_pending_items()
                    if pending:
                        raise UserError(_(
                            "The handover is not verified yet and some items are not ticked (%s). "
                            "Open the resignation and click \"Verify Handover\" to give the reason.",
                            ", ".join(pending)))
                    self.action_verify_handover()
                self.action_process_settlement()
            if self.state == current:  # safety net: a step did not advance
                raise UserError(_("Could not move %(employee)s's resignation past %(stage)s.",
                                  employee=self.employee_id.name, stage=labels[current]))

    def _pipeline_back(self, target):
        """Go back to an earlier stage and undo what the later stages recorded,
        so the workflow buttons of the target stage are available again."""
        if not (self.env.is_superuser()
                or any(self.env.user.has_group(group) for group in self._PIPELINE_BACK_GROUPS)):
            raise UserError(_("Only an Administrator, the HR Manager or the Principal can move a "
                              "resignation back to an earlier stage."))
        stages = self._pipeline_stages()
        labels = dict(self._fields['state']._description_selection(self.env))
        position = stages.index(target)
        vals = {'state': target}
        reset = []
        if position < stages.index('settled') and (self.settlement_processed or self.exit_done):
            vals.update(settlement_processed=False, settlement_processed_date=False)
            reset.append(_("final settlement"))
            if self.exit_done:
                # The employee was archived by "Exit / Mark as Left": restore them.
                self.employee_id.sudo().action_unarchive()
                vals['exit_done'] = False
                reset.append(_("exit (employee restored)"))
        if position < stages.index('handover') and self.handover_verified:
            vals.update(handover_verified=False, handover_verified_by=False, handover_verified_date=False,
                        handover_not_applicable=False, handover_exception_reason=False,
                        handover_student_register_reason=False, handover_study_materials_reason=False,
                        handover_reports_reason=False, handover_id_card_reason=False)
            reset.append(_("handover verification"))
        if position < stages.index('notice_period') and self.notice_period_start:
            vals['notice_period_start'] = False
        if position < stages.index('handover') and self.notice_waived:
            vals.update(notice_waived=False, notice_waiver_reason=False,
                        notice_waived_by=False, notice_waived_date=False)
            if vals.get('notice_period_start', self.notice_period_start):
                # back to the normal mandatory 3-month notice
                vals['notice_period_end'] = self.notice_period_start + relativedelta(months=3)
            reset.append(_("skipped notice period"))
            reset.append(_("notice period"))
        if position < stages.index('approved') and (self.principal_approved or self.hr_approved):
            vals.update(principal_approved=False, principal_approved_by=False, principal_approved_date=False,
                        hr_approved=False, hr_approved_by=False, hr_approved_date=False)
            reset.append(_("Principal and HR Manager approvals"))
        if position < stages.index('submitted') and self.submitted_date:
            vals['submitted_date'] = False
            reset.append(_("submission date"))
        previous = labels[self.state]
        self.with_context(resignation_workflow=True).write(vals)
        self.message_post(body=_(
            "Moved back from %(from)s to %(to)s by %(user)s.%(reset)s",
            user=self.env.user.name, to=labels[target], reset=(
                " " + _("Reset: %s.", ", ".join(reset)) if reset else ""),
            **{'from': previous}))

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
            rec.with_context(resignation_workflow=True).write({
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
                rec.with_context(resignation_workflow=True).write({'state': 'approved'})

    # ------------------------------------------------------------------
    # Step 4: Notice period
    # ------------------------------------------------------------------
    def action_start_notice_period(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_("Notice period can only start once BOTH the Principal and HR Manager have approved."))
            rec.with_context(resignation_workflow=True).write({
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
            rec.with_context(resignation_workflow=True).write({'state': 'handover'})

    # ------------------------------------------------------------------
    # Skip Notice Period: move to Handover without serving the notice, with a reason
    # ------------------------------------------------------------------
    _NOTICE_WAIVER_GROUPS = (
        'ad_school_management.group_school_admin',
        'ad_school_management.group_school_hr_manager',
        'ad_school_management.group_school_principal',
    )

    def _check_can_waive_notice(self):
        if not (self.env.is_superuser()
                or any(self.env.user.has_group(g) for g in self._NOTICE_WAIVER_GROUPS)):
            raise UserError(_("Only an Administrator, the HR Manager or the Principal can approve "
                              "skipping the notice period."))

    def action_open_emergency_exit(self):
        """'Skip Notice Period' button: ask for the reason and the last working day."""
        self.ensure_one()
        self._check_can_waive_notice()
        if self.state != 'notice_period':
            raise UserError(_("The notice period can only be skipped during the Notice Period stage."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Skip Notice Period: %s', self.employee_id.name),
            'res_model': 'school.resignation.emergency.exit',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_resignation_id': self.id},
        }

    def _do_emergency_exit(self, reason, last_working_day, start=False):
        """Record the waiver and move straight to Handover. `start` (from the
        dialog) replaces the notice period start when given."""
        self.ensure_one()
        self._check_can_waive_notice()
        if self.state != 'notice_period':
            raise UserError(_("The notice period can only be skipped during the Notice Period stage."))
        if not (reason or '').strip():
            raise UserError(_("Please give the reason for skipping the notice period."))
        start = start or self.notice_period_start or fields.Date.context_today(self)
        if last_working_day < start:
            raise UserError(_("The last working day cannot be before the notice period start (%s).",
                              format_date(self.env, start)))
        self.with_context(resignation_workflow=True).write({
            'notice_period_start': start,
            'notice_period_end': last_working_day,
            'notice_waived': True,
            'notice_waiver_reason': reason.strip(),
            'notice_waived_by': self.env.user.id,
            'notice_waived_date': fields.Datetime.now(),
            'state': 'handover',
        })
        self.message_post(body=_(
            "Notice period skipped (approved by %(user)s), last working day %(day)s. "
            "Reason: %(reason)s",
            user=self.env.user.name, day=format_date(self.env, last_working_day), reason=reason.strip()))
        return True

    # ------------------------------------------------------------------
    # Step 6: Manager verification of the handover checklist
    # ------------------------------------------------------------------
    def _handover_items(self):
        """(checkbox field, reason field, label) for every checklist item."""
        return [
            ('handover_student_register', 'handover_student_register_reason', _("Student Register")),
            ('handover_study_materials', 'handover_study_materials_reason', _("Study Materials")),
            ('handover_reports', 'handover_reports_reason', _("Reports")),
            ('handover_id_card', 'handover_id_card_reason', _("ID Card")),
        ]

    def _handover_pending(self):
        """Checklist items not ticked yet: [(checkbox field, reason field, label)]."""
        self.ensure_one()
        return [item for item in self._handover_items() if not self[item[0]]]

    def _handover_pending_items(self):
        """Labels of the checklist items not ticked yet."""
        return [label for _fname, _rname, label in self._handover_pending()]

    def action_verify_handover(self):
        """'Verify Handover' button.

        Everything ticked -> verified. Some items not ticked (e.g. a
        non-teaching staff member has no study materials) -> a dialog asks
        the verifier for the reason, then verifies with those items recorded
        as not handed over."""
        self.ensure_one()
        if self.state != 'handover':
            raise UserError(_("Only a resignation in the Handover stage can be verified."))
        pending = self._handover_pending_items()
        if pending:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Verify Handover: %s', self.employee_id.name),
                'res_model': 'school.resignation.handover.exception',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_resignation_id': self.id},
            }
        self._mark_handover_verified()
        return True

    def _mark_handover_verified(self, reasons=None):
        """Verify the handover. `reasons` = {checkbox field: reason} for the
        items that were NOT handed over; every unticked item needs its own
        reason. Those items are then accepted and their reasons recorded."""
        self.ensure_one()
        if self.state != 'handover':
            raise UserError(_("Only a resignation in the Handover stage can be verified."))
        reasons = {key: (value or '').strip() for key, value in (reasons or {}).items()}
        pending = self._handover_pending()
        missing = [label for fname, _rname, label in pending if not reasons.get(fname)]
        if missing:
            raise UserError(_("Give a reason for each item that was not handed over: %s",
                              ", ".join(missing)))
        vals = {
            'handover_verified': True,
            'handover_verified_by': self.env.uid,
            'handover_verified_date': fields.Datetime.now(),
            'handover_not_applicable': ", ".join(label for _f, _r, label in pending) or False,
            'handover_exception_reason': "\n".join(
                "%s: %s" % (label, reasons[fname]) for fname, _r, label in pending) or False,
        }
        for fname, rname, _label in self._handover_items():
            vals[rname] = reasons.get(fname) if fname in dict((p[0], p) for p in pending) else False
        self.write(vals)
        if pending:
            # Markup % escapes the typed reasons (no HTML injection).
            lines = Markup("").join(Markup("<li>%s: %s</li>") % (label, reasons[fname])
                                    for fname, _r, label in pending)
            self.message_post(body=Markup(_("Handover verified by %(user)s. Not handed over:<ul>%(lines)s</ul>")) % {
                'user': self.env.user.name, 'lines': lines})

    # ------------------------------------------------------------------
    # Step 7: Settlement
    # ------------------------------------------------------------------
    def action_process_settlement(self):
        for rec in self:
            # Same rule as the button (groups=) in the form, enforced server-side
            # too, because the pipeline lets users drag cards to 'Settled'.
            if not (self.env.user.has_group('ad_school_management.group_school_admin')
                    or self.env.user.has_group('ad_school_management.group_school_accountant')):
                raise UserError(_("Only an Administrator or the Accountant can process the final settlement."))
            if rec.state != 'handover' or not rec.handover_verified:
                raise UserError(_("Handover must be verified before processing the final settlement."))
            if rec.settlement_amount <= 0:
                raise UserError(_("Please enter the final settlement amount before processing it."))
            rec.with_context(resignation_workflow=True).write({
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
        # Open a NEW (unsaved) interview form instead of creating the record
        # straight away: 'Conducted By' is mandatory, so the user must be able
        # to choose it before the interview is saved.
        return {
            'name': _('Exit Interview'),
            'type': 'ir.actions.act_window',
            'res_model': 'school.exit.interview',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {'default_resignation_id': self.id},
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
