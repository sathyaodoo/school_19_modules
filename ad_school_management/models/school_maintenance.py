from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SchoolMaintenanceLocation(models.Model):
    _name = 'school.maintenance.location'
    _description = 'School Location (Block / Floor / Room)'
    _rec_name = 'complete_name'
    _order = 'complete_name'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code')
    location_type = fields.Selection([
        ('block', 'Block / Building'),
        ('floor', 'Floor'),
        ('room', 'Room / Classroom'),
        ('outdoor', 'Outdoor / Ground'),
        ('other', 'Other'),
    ], string='Type', default='room')
    parent_id = fields.Many2one('school.maintenance.location', string='Parent Location',
                                index=True, ondelete='restrict')
    child_ids = fields.One2many('school.maintenance.location', 'parent_id', string='Sub Locations')
    complete_name = fields.Char(string='Full Location', compute='_compute_complete_name',
                                recursive=True, store=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for rec in self:
            if rec.parent_id:
                rec.complete_name = '%s / %s' % (rec.parent_id.complete_name, rec.name)
            else:
                rec.complete_name = rec.name

    @api.constrains('parent_id')
    def _check_parent_recursion(self):
        if self._has_cycle():
            raise ValidationError(_("A location cannot be its own parent (loop detected)."))


class MaintenanceEquipment(models.Model):
    _inherit = 'maintenance.equipment'

    school_location_id = fields.Many2one('school.maintenance.location', string='School Location',
                                         help="Block / floor / room where this equipment is installed.")


class MaintenanceRequest(models.Model):
    _inherit = 'maintenance.request'

    # BRS 24: Complaint / Ticket
    school_location_id = fields.Many2one('school.maintenance.location', string='Location', tracking=True)
    repair_vendor_id = fields.Many2one('res.partner', string='Repair Vendor', tracking=True,
                                       help="Outside vendor / contractor assigned to carry out the repair.")

    # BRS 24: Inspection
    inspection_date = fields.Date(string='Inspection Date')
    inspected_by_id = fields.Many2one('res.users', string='Inspected By')
    inspection_findings = fields.Text(string='Inspection Findings')
    fault_description = fields.Text(string='Fault Description')
    action_required = fields.Text(string='Action Required')
    material_estimate = fields.Text(string='Material Required (Estimate)')
    school_currency_id = fields.Many2one('res.currency', string='Company Currency', related='company_id.currency_id')
    estimated_cost = fields.Monetary(string='Estimated Cost', currency_field='school_currency_id', tracking=True)

    # BRS 24: Repair / Action
    work_done = fields.Text(string='Work Carried Out')
    spare_line_ids = fields.One2many('school.maintenance.spare', 'request_id', string='Spares / Materials Used')
    spares_total = fields.Monetary(string='Spares Total', currency_field='school_currency_id',
                                   compute='_compute_spares_total', store=True)

    @api.depends('spare_line_ids.subtotal')
    def _compute_spares_total(self):
        for rec in self:
            rec.spares_total = sum(rec.spare_line_ids.mapped('subtotal'))

    @api.onchange('equipment_id')
    def _onchange_equipment_school_location(self):
        if self.equipment_id.school_location_id:
            self.school_location_id = self.equipment_id.school_location_id

    @api.constrains('estimated_cost')
    def _check_estimated_cost(self):
        for rec in self:
            if rec.estimated_cost < 0:
                raise ValidationError(_("Estimated cost cannot be negative."))


class SchoolMaintenanceSpare(models.Model):
    _name = 'school.maintenance.spare'
    _description = 'Spare / Material Used in Repair'

    request_id = fields.Many2one('maintenance.request', string='Request', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product')
    name = fields.Char(string='Description', required=True)
    quantity = fields.Float(string='Quantity', default=1.0, required=True)
    unit_cost = fields.Float(string='Unit Cost')
    subtotal = fields.Float(string='Subtotal', compute='_compute_subtotal', store=True)

    @api.depends('quantity', 'unit_cost')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.unit_cost

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.product_id.display_name
            self.unit_cost = self.product_id.standard_price

    @api.constrains('quantity', 'unit_cost')
    def _check_values(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_("Spare quantity must be greater than zero."))
            if line.unit_cost < 0:
                raise ValidationError(_("Unit cost cannot be negative."))

# ---------------------------------------------------------------------------
# Phase 2: approval limits, vendor bill link, requester verification
# ---------------------------------------------------------------------------
class SchoolMaintenanceApprovalRule(models.Model):
    _name = 'school.maintenance.approval.rule'
    _description = 'Maintenance Approval Limit'
    _order = 'amount_from'

    name = fields.Char(string='Rule Name', required=True)
    amount_from = fields.Float(
        string='Estimated Cost From', required=True,
        help="Tickets with an estimated cost equal to or above this amount need approval from the "
             "approver below. When several rules match, the one with the highest amount applies.")
    approver_id = fields.Many2one('res.users', string='Approver', required=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    _amount_from_positive = models.Constraint(
        'CHECK(amount_from >= 0)', 'The approval amount cannot be negative.')


class MaintenanceRequestApproval(models.Model):
    _inherit = 'maintenance.request'

    # --- Approval by amount limit ---
    approval_rule_id = fields.Many2one('school.maintenance.approval.rule', string='Applicable Rule',
                                       compute='_compute_approval_rule')
    approval_required = fields.Boolean(string='Approval Required', compute='_compute_approval_rule')
    approver_id = fields.Many2one('res.users', string='Approver', compute='_compute_approval_rule')
    approval_state = fields.Selection([
        ('none', 'Not Requested'),
        ('to_approve', 'Waiting for Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Approval Status', default='none', tracking=True, copy=False)
    approved_by_id = fields.Many2one('res.users', string='Decided By', readonly=True, copy=False)
    approved_date = fields.Datetime(string='Decision Date', readonly=True, copy=False)

    # --- Expense recording ---
    vendor_bill_id = fields.Many2one('account.move', string='Vendor Bill', tracking=True, copy=False,
                                     domain="[('move_type', '=', 'in_invoice')]")
    bill_currency_id = fields.Many2one('res.currency', string='Bill Currency', related='vendor_bill_id.currency_id',
                                       tracking=False)
    bill_amount = fields.Monetary(string='Bill Amount', related='vendor_bill_id.amount_total',
                                  currency_field='bill_currency_id')
    cost_variance = fields.Monetary(string='Bill vs Estimate', compute='_compute_cost_variance',
                                    currency_field='school_currency_id',
                                    help="Vendor bill amount minus estimated cost. Positive = over estimate.")

    # --- Verification & closure ---
    verification_state = fields.Selection([
        ('pending', 'Pending Verification'),
        ('verified', 'Verified'),
        ('not_satisfied', 'Not Satisfied'),
    ], string='Verification', default='pending', tracking=True, copy=False)
    verified_by_id = fields.Many2one('res.users', string='Verified By', readonly=True, copy=False)
    verified_date = fields.Datetime(string='Verified On', readonly=True, copy=False)
    closure_date = fields.Date(string='Closure Date', readonly=True, copy=False)
    closure_remarks = fields.Text(string='Closure Remarks')

    @api.depends('estimated_cost')
    def _compute_approval_rule(self):
        rules = self.env['school.maintenance.approval.rule'].search([], order='amount_from desc')
        for rec in self:
            rule = rules.filtered(lambda r: rec.estimated_cost >= r.amount_from)[:1]
            rec.approval_rule_id = rule
            rec.approver_id = rule.approver_id
            rec.approval_required = bool(rule) and rec.estimated_cost > 0

    @api.depends('bill_amount', 'estimated_cost', 'vendor_bill_id')
    def _compute_cost_variance(self):
        for rec in self:
            rec.cost_variance = (rec.bill_amount - rec.estimated_cost) if rec.vendor_bill_id else 0.0

    # --- guard: no work before approval ---
    def _check_stage_approval(self, stage_id):
        stages = self.env['maintenance.stage'].search([], order='sequence, id')
        if not stages or stage_id in (stages[0].id, stages[-1].id):
            return  # first stage (New) and last stage (Scrap) are always allowed
        for rec in self:
            if rec.stage_id.id == stage_id:
                continue
            if rec.approval_required and rec.approval_state != 'approved':
                raise UserError(_(
                    "Estimated cost %(cost)s needs approval from %(user)s before work can start. "
                    "Use 'Request Approval' first.",
                    cost=rec.estimated_cost, user=rec.approver_id.name))

    def write(self, vals):
        if vals.get('stage_id'):
            self._check_stage_approval(vals['stage_id'])
        changed = self.browse()
        if 'estimated_cost' in vals and 'approval_state' not in vals:
            changed = self.filtered(
                lambda r: r.approval_state != 'none' and abs(r.estimated_cost - vals['estimated_cost']) > 0.005)
        res = super().write(vals)
        if changed:
            changed.write({'approval_state': 'none'})
            for rec in changed:
                rec.message_post(body=_("Estimated cost changed: approval has been reset."))
        return res

    # --- approval buttons ---
    def action_request_approval(self):
        for rec in self:
            if not rec.approval_required:
                raise UserError(_("No approval is needed for this estimated cost."))
            rec.approval_state = 'to_approve'
            rec.activity_schedule(
                'mail.mail_activity_data_todo', user_id=rec.approver_id.id,
                summary=_("Approve maintenance estimate: %s", rec.name))

    def _check_can_decide(self):
        for rec in self:
            if rec.approval_state != 'to_approve':
                raise UserError(_("This ticket is not waiting for approval."))
            if self.env.user != rec.approver_id and not self.env.user.has_group('base.group_system'):
                raise UserError(_("Only %s can approve or reject this estimate.", rec.approver_id.name))

    def action_approve(self):
        self._check_can_decide()
        self.write({'approval_state': 'approved', 'approved_by_id': self.env.uid,
                    'approved_date': fields.Datetime.now()})

    def action_reject_approval(self):
        self._check_can_decide()
        self.write({'approval_state': 'rejected', 'approved_by_id': self.env.uid,
                    'approved_date': fields.Datetime.now()})

    # --- verification buttons ---
    def _check_can_verify(self):
        for rec in self:
            if 'done' in rec.stage_id._fields and not rec.stage_id.done:
                raise UserError(_("Move the ticket to the Repaired stage before verification."))
            if self.env.user != rec.create_uid and not self.env.user.has_group('maintenance.group_equipment_manager'):
                raise UserError(_(
                    "Only the person who raised the ticket (%s) or a maintenance manager can verify it.",
                    rec.create_uid.name))

    def action_verify(self):
        self._check_can_verify()
        self.write({'verification_state': 'verified', 'verified_by_id': self.env.uid,
                    'verified_date': fields.Datetime.now(), 'closure_date': fields.Date.context_today(self)})

    def action_not_satisfied(self):
        self._check_can_verify()
        for rec in self:
            if not rec.closure_remarks:
                raise UserError(_("Please enter the Closure Remarks (what is still wrong) first."))
        self.write({'verification_state': 'not_satisfied', 'verified_by_id': self.env.uid,
                    'verified_date': fields.Datetime.now(), 'closure_date': False})


# ---------------------------------------------------------------------------
# Phase 3: SLA / escalation, repeat-fault flag, ageing, reports support
# ---------------------------------------------------------------------------
class SchoolMaintenanceSla(models.Model):
    _name = 'school.maintenance.sla'
    _description = 'Maintenance SLA & Escalation Rule'
    _order = 'priority desc'

    name = fields.Char(string='Rule Name', required=True)
    priority = fields.Selection([
        ('0', '0 Star'),
        ('1', '1 Star'),
        ('2', '2 Stars'),
        ('3', '3 Stars'),
    ], string='Ticket Priority', required=True)
    target_hours = fields.Float(string='Resolve Within (Hours)', required=True,
                                help="Ticket must reach a Done stage within this many hours of creation.")
    escalation_user_id = fields.Many2one('res.users', string='Escalate To',
                                         help="This user gets a To-Do when the ticket crosses its deadline.")
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    _priority_company_uniq = models.Constraint(
        'unique(priority, company_id)', 'Only one SLA rule is allowed per priority.')
    _target_hours_positive = models.Constraint(
        'CHECK(target_hours > 0)', 'Resolve Within (Hours) must be greater than zero.')


class MaintenanceRequestPhase3(models.Model):
    _inherit = 'maintenance.request'

    stage_done = fields.Boolean(related='stage_id.done', string='Stage is Done')

    # --- SLA / ageing ---
    sla_deadline = fields.Datetime(string='SLA Deadline', compute='_compute_sla_deadline', store=True)
    is_overdue = fields.Boolean(string='Overdue', default=False, copy=False, index=True)
    escalated_date = fields.Datetime(string='Escalated On', readonly=True, copy=False)
    age_days = fields.Integer(string='Age (Days)', compute='_compute_age_days')
    closure_days = fields.Integer(string='Days to Close', compute='_compute_closure_days',
                                  store=True, aggregator='avg')

    # --- repeat fault ---
    repeat_count = fields.Integer(string='Earlier Tickets (Same Equipment / Location)',
                                  readonly=True, copy=False)
    repeat_fault = fields.Boolean(string='Repeated Fault', readonly=True, copy=False, index=True)

    @api.depends('priority', 'create_date')
    def _compute_sla_deadline(self):
        rules = {r.priority: r for r in self.env['school.maintenance.sla'].search([])}
        for rec in self:
            rule = rules.get(rec.priority or '0')  # no star = priority is empty in standard Maintenance
            base = rec.create_date or fields.Datetime.now()
            rec.sla_deadline = base + timedelta(hours=rule.target_hours) if rule else False

    @api.depends('request_date', 'close_date')
    def _compute_age_days(self):
        today = fields.Date.context_today(self)
        for rec in self:
            end = rec.close_date or today
            rec.age_days = (end - rec.request_date).days if rec.request_date else 0

    @api.depends('request_date', 'close_date')
    def _compute_closure_days(self):
        for rec in self:
            if rec.request_date and rec.close_date:
                rec.closure_days = (rec.close_date - rec.request_date).days
            else:
                rec.closure_days = 0

    def _get_sla_rule(self):
        self.ensure_one()
        return self.env['school.maintenance.sla'].search([('priority', '=', self.priority or '0')], limit=1)

    # --- repeat-fault detection (runs when a ticket is created) ---
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._update_repeat_fault()
        return records

    def _update_repeat_fault(self):
        params = self.env['ir.config_parameter'].sudo()
        days = int(params.get_param('school_maintenance.repeat_days', 30))
        threshold = int(params.get_param('school_maintenance.repeat_tickets', 2))
        for rec in self:
            if rec.equipment_id:
                key = [('equipment_id', '=', rec.equipment_id.id)]
            elif rec.school_location_id:
                key = [('school_location_id', '=', rec.school_location_id.id)]
            else:
                continue
            since = (rec.request_date or fields.Date.context_today(rec)) - timedelta(days=days)
            earlier = self.search_count(key + [('id', '!=', rec.id), ('request_date', '>=', since)])
            rec.write({'repeat_count': earlier, 'repeat_fault': earlier + 1 >= threshold})

    # --- close the approver's To-Do once a decision is made ---
    def _close_approval_activities(self, feedback):
        todo = self.env.ref('mail.mail_activity_data_todo')
        for rec in self:
            rec.activity_ids.filtered(
                lambda a: a.activity_type_id == todo and a.user_id == rec.approver_id
            ).action_feedback(feedback=feedback)

    def action_approve(self):
        res = super().action_approve()
        self._close_approval_activities(_("Approved"))
        return res

    def action_reject_approval(self):
        res = super().action_reject_approval()
        self._close_approval_activities(_("Rejected"))
        return res

    # --- scheduled action: flag and escalate overdue tickets ---
    @api.model
    def _cron_escalate_overdue(self):
        now = fields.Datetime.now()
        # refresh deadlines of open tickets (picks up SLA rules created or changed after the ticket)
        self.search([('stage_id.done', '=', False)])._compute_sla_deadline()
        self.search([('is_overdue', '=', True), ('stage_id.done', '=', True)]).write({'is_overdue': False})
        late = self.search([
            ('is_overdue', '=', False), ('stage_id.done', '=', False),
            ('sla_deadline', '!=', False), ('sla_deadline', '<', now),
        ])
        for rec in late:
            rule = rec._get_sla_rule()
            rec.write({'is_overdue': True, 'escalated_date': now})
            rec.message_post(body=_("SLA deadline %s has passed: this ticket is overdue.", rec.sla_deadline))
            if rule.escalation_user_id:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo', user_id=rule.escalation_user_id.id,
                    summary=_("Overdue maintenance ticket: %s", rec.name))


class MaintenanceRequestResponse(models.Model):
    _inherit = 'maintenance.request'

    first_response_date = fields.Datetime(string='First Response On', readonly=True, copy=False)
    response_hours = fields.Float(string='Response Time (Hours)', compute='_compute_response_hours',
                                  store=True, aggregator='avg',
                                  help="Hours between ticket creation and the first move out of the New stage.")

    @api.depends('first_response_date', 'create_date')
    def _compute_response_hours(self):
        for rec in self:
            if rec.first_response_date and rec.create_date:
                rec.response_hours = (rec.first_response_date - rec.create_date).total_seconds() / 3600.0
            else:
                rec.response_hours = 0.0

    def write(self, vals):
        res = super().write(vals)
        if vals.get('stage_id'):
            first_stage = self.env['maintenance.stage'].search([], order='sequence, id', limit=1)
            moved = self.filtered(lambda r: not r.first_response_date and r.stage_id != first_stage)
            if moved:
                moved.write({'first_response_date': fields.Datetime.now()})
        return res