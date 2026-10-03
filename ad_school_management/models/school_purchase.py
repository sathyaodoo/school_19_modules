from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SchoolPurchaseRequest(models.Model):
    _name = 'school.purchase.request'
    _description = 'Purchase Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Request ID', required=True, readonly=True, default='/', copy=False)
    request_date = fields.Date(string='Request Date', required=True, default=fields.Date.context_today,
                               tracking=True)
    requested_by_id = fields.Many2one('res.users', string='Created By', readonly=True,
                                      default=lambda self: self.env.user)
    department_id = fields.Many2one('hr.department', string='Department', tracking=True)
    priority = fields.Selection([
        ('urgent', 'Urgent'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ], string='Priority', required=True, default='medium', tracking=True)
    justification = fields.Text(string='Justification', help="Why is this needed?")
    line_ids = fields.One2many('school.purchase.request.line', 'request_id', string='Products')
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')
    total_amount = fields.Monetary(string='Total', currency_field='currency_id',
                                   compute='_compute_total_amount', store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('po_created', 'PO Created'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False, index=True)

    # approval (BRS: MMD approval date / comments)
    approver_id = fields.Many2one('res.users', string='Approver (MMD)', tracking=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True, copy=False)
    approval_comments = fields.Text(string='Approver Comments')

    # purchase order
    vendor_id = fields.Many2one('res.partner', string='Preferred Vendor')
    purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order', readonly=True, copy=False)

    @api.depends('line_ids.subtotal')
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(rec.line_ids.mapped('subtotal'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('school.purchase.request') or '/'
        return super().create(vals_list)

    # --- workflow ---
    def action_submit(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_("Add at least one product before submitting."))
            if not rec.justification:
                raise UserError(_("Please enter the Justification."))
            if not rec.approver_id:
                raise UserError(_("Please choose the Approver (MMD)."))
            rec.state = 'submitted'
            rec.activity_schedule(
                'mail.mail_activity_data_todo', user_id=rec.approver_id.id,
                summary=_("Approve purchase request: %s", rec.name))

    def _check_can_decide(self):
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_("This request is not waiting for approval."))
            if self.env.user != rec.approver_id and not self.env.user.has_group('base.group_system'):
                raise UserError(_("Only %s can approve or reject this request.", rec.approver_id.name))

    def _close_approval_activities(self, feedback):
        todo = self.env.ref('mail.mail_activity_data_todo')
        for rec in self:
            rec.activity_ids.filtered(
                lambda a: a.activity_type_id == todo and a.user_id == rec.approver_id
            ).action_feedback(feedback=feedback)

    def action_approve(self):
        self._check_can_decide()
        self.write({'state': 'approved', 'approval_date': fields.Datetime.now()})
        self._close_approval_activities(_("Approved"))

    def action_reject(self):
        self._check_can_decide()
        for rec in self:
            if not rec.approval_comments:
                raise UserError(_("Please enter the Approver Comments (reason) before rejecting."))
        self.write({'state': 'rejected', 'approval_date': fields.Datetime.now()})
        self._close_approval_activities(_("Rejected"))

    def action_reset_draft(self):
        for rec in self:
            if rec.state != 'rejected':
                raise UserError(_("Only a rejected request can be set back to draft."))
        self.write({'state': 'draft', 'approval_date': False})

    def action_create_po(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_("Only an approved request can be converted to a Purchase Order."))
            if not rec.vendor_id:
                raise UserError(_("Please choose the Preferred Vendor before creating the Purchase Order."))
            po = self.env['purchase.order'].sudo().create({
                'partner_id': rec.vendor_id.id,
                'origin': rec.name,
                'company_id': rec.company_id.id,
                'order_line': [Command.create({
                    'product_id': line.product_id.id,
                    'product_qty': line.quantity,
                    'price_unit': line.unit_cost,
                }) for line in rec.line_ids],
            })
            rec.write({'purchase_order_id': po.id, 'state': 'po_created'})

    def action_view_po(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Purchase Order'),
            'res_model': 'purchase.order',
            'res_id': self.purchase_order_id.id,
            'view_mode': 'form',
        }


class SchoolPurchaseRequestLine(models.Model):
    _name = 'school.purchase.request.line'
    _description = 'Purchase Request Line'

    request_id = fields.Many2one('school.purchase.request', string='Request', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    name = fields.Char(string='Description')
    quantity = fields.Float(string='Quantity', default=1.0, required=True)
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure')
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
            self.uom_id = self.product_id.uom_id
            self.unit_cost = self.product_id.standard_price

    @api.constrains('quantity', 'unit_cost')
    def _check_values(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_("Quantity must be greater than zero."))
            if line.unit_cost < 0:
                raise ValidationError(_("Unit cost cannot be negative."))


class MaintenanceRequestPurchase(models.Model):
    _inherit = 'maintenance.request'

    purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order', tracking=True, copy=False)


class ResPartnerVendor(models.Model):
    _inherit = 'res.partner'

    quality_rating = fields.Selection([
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('average', 'Average'),
        ('poor', 'Poor'),
    ], string='Quality Rating', tracking=True)


# ---------------------------------------------------------------------------
# Multi-branch: CBSE / State Board (BRS 4.1 Multi-Board Admission Workflows)
# Each record belongs to a branch (company). Records of the parent company are
# shared with all its branches. See record rules in security/school_security.xml.
# ---------------------------------------------------------------------------
from odoo import api as _mb_api, fields as _mb_fields, models as _mb_models

_BRANCH_MODELS = ['school.academic.year', 'school.academic.term', 'school.class', 'school.section', 'school.subject', 'school.attendance', 'school.exam', 'school.exam.result', 'school.timetable', 'school.promotion', 'school.hostel', 'school.hostel.room', 'school.hostel.allocation', 'school.book', 'school.book.issue', 'school.book.list', 'school.vehicle', 'school.transport.route', 'school.student.transport.fee', 'school.transport.route.change.request', 'school.transport.attendance']

for _model_name in _BRANCH_MODELS:
    type('SchoolBranch_' + _model_name.replace('.', '_'), (_mb_models.Model,), {
        '_inherit': _model_name,
        '__module__': __name__,
        'company_id': _mb_fields.Many2one(
            'res.company', string='Branch', index=True,
            default=lambda self: self.env.company,
            help="Branch (CBSE / State Board). Records of the main school are shared with all branches."),
    })


class SchoolStudentBranchDefault(_mb_models.Model):
    _inherit = 'school.student'

    @_mb_api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'company_id' in fields_list and not res.get('company_id'):
            res['company_id'] = self.env.company.id
        return res


class SchoolParentBranchDefault(_mb_models.Model):
    _inherit = 'school.parent'

    @_mb_api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'company_id' in fields_list and not res.get('company_id'):
            res['company_id'] = self.env.company.id
        return res