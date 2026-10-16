from lxml import etree

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    """Adds the school's procurement fields on top of the native
    Purchase Order (purchase.order), plus an extra workflow stage:

        RFQ -> RFQ Sent -> MMD Approval -> Purchase Order

    "Send for MMD Approval" works exactly where Odoo's own "Confirm Order"
    does: from the RFQ stage and from RFQ Sent (sending the RFQ to the
    vendor is optional).

    After MMD approves, the order is handed back to Odoo's STANDARD
    confirmation (button_confirm), so everything native keeps working:
    double validation ('To Approve') if enabled, receipts, vendor
    bills, supplier info on products, locking, etc.

    The 'state' field is extended via selection_add with position
    anchors so MMD Approval sits between RFQ Sent and Purchase Order.
    The statusbar ORDER follows the selection order; statusbar_visible
    (set in get_view()) only controls WHICH states are shown.
    """
    _inherit = 'purchase.order'

    justification = fields.Text(
        string='Justification', help='Reason / business justification for this purchase',
    )
    priority = fields.Selection(
        [
            ('low', 'Low'),
            ('medium', 'Medium'),
            ('high', 'High'),
            ('urgent', 'Urgent'),
        ],
        string='Priority', default='medium', tracking=True,
    )
    department_id = fields.Many2one(
        'hr.department', string='Department', tracking=True,
        help='Requesting/purchasing department',
    )
    mmd_command_ref = fields.Char(
        string='MMD Command Ref.',
        help='Material Management Department approval code/reference',
        tracking=True,
    )

    # --- New workflow stage: MMD Approval ------------------------------
    # Single-element tuples reference EXISTING states and act as position
    # anchors. Resulting order:
    # draft, sent, to approve, mmd_approval, purchase, done, cancel, mmd_rejected
    state = fields.Selection(
        selection_add=[
            ('sent',),
            ('mmd_approval', 'MMD Approval'),
            ('purchase',),
            ('cancel',),
            ('mmd_rejected', 'Rejected'),
        ],
        ondelete={'mmd_approval': 'set default', 'mmd_rejected': 'set default'},
    )

    mmd_approved = fields.Boolean(string='MMD Approved', copy=False, tracking=True)
    mmd_approved_by = fields.Many2one('res.users', string='MMD Reviewed By', copy=False)
    mmd_approved_date = fields.Datetime(string='MMD Review Date', copy=False)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _check_mmd_group(self):
        if not (self.env.user.has_group('ad_school_management.group_school_mmd')
                or self.env.user.has_group('ad_school_management.group_school_admin')):
            raise UserError(_("Only MMD (Material Management Department) or an Administrator can do this."))

    def _mmd_reset_values(self):
        return {
            'mmd_approved': False,
            'mmd_approved_by': False,
            'mmd_approved_date': False,
        }

    # ------------------------------------------------------------------
    # MMD workflow actions
    # ------------------------------------------------------------------
    def action_send_for_mmd_approval(self):
        """Replaces the native "Confirm Order": available from the RFQ stage
        and from RFQ Sent, like the standard button."""
        for order in self:
            if order.state not in ('draft', 'sent'):
                raise UserError(_("Only an RFQ (new or sent) can be sent for MMD Approval."))
            if not order.order_line.filtered(lambda l: not l.display_type):
                raise UserError(_("Please add at least one product line before sending for MMD Approval."))
            order.state = 'mmd_approval'
            order.message_post(body=_("Sent for MMD Approval by %s.", self.env.user.name))
        return True

    def action_mmd_approve(self):
        """Kept for backward compatibility: approving == native Confirm Order."""
        return self.with_context(validate_analytic=True).button_confirm()

    def action_mmd_reject(self):
        for order in self:
            order._check_mmd_group()
            if order.state != 'mmd_approval':
                raise UserError(_("Only an order awaiting MMD Approval can be rejected."))
            order.write({
                'state': 'mmd_rejected',
                'mmd_approved': False,
                'mmd_approved_by': self.env.uid,
                'mmd_approved_date': fields.Datetime.now(),
            })
            order.message_post(body=_("Rejected by MMD (%s).", self.env.user.name))
        return True

    def action_mmd_reset_to_draft(self):
        for order in self:
            order._check_mmd_group()
            if order.state != 'mmd_rejected':
                raise UserError(_("Only a rejected order can be reset to RFQ."))
            vals = order._mmd_reset_values()
            vals['state'] = 'draft'
            order.write(vals)
        return True

    # ------------------------------------------------------------------
    # Native method overrides
    # ------------------------------------------------------------------
    def button_confirm(self):
        """Native 'Confirm Order', gated by MMD Approval.

        - draft / sent  -> blocked unless already MMD-approved
        - mmd_approval  -> MMD/Admin only; the order is marked approved,
                           moved back to 'sent', and then Odoo's DEFAULT
                           confirmation runs unchanged (super()). That
                           default flow sets state 'purchase' (or
                           'to approve' with double validation), creates
                           the Receipt (Receive button + Receipt smart
                           button), enables vendor bills, etc.
        """
        approved_now = self.browse()
        for order in self:
            if order.state == 'mmd_approval':
                order._check_mmd_group()
                order.write({
                    'mmd_approved': True,
                    'mmd_approved_by': self.env.uid,
                    'mmd_approved_date': fields.Datetime.now(),
                    'state': 'sent',
                })
                approved_now |= order
            elif order.state in ('draft', 'sent') and not order.mmd_approved:
                raise UserError(_(
                    "This RFQ must go through MMD Approval before it can be confirmed. "
                    "Please click 'Send for MMD Approval'."
                ))
        res = super().button_confirm()
        for order in approved_now:
            order.message_post(body=_("Approved by MMD (%s) and confirmed.", self.env.user.name))
        return res

    def button_draft(self):
        # Native "Set to Draft" (e.g. after cancel): approval must be redone.
        res = super().button_draft()
        self.write(self._mmd_reset_values())
        return res

    # ------------------------------------------------------------------
    # Form view customisation
    # ------------------------------------------------------------------
    @api.model
    def get_view(self, view_id=None, view_type='form', **options):
        result = super().get_view(view_id, view_type, **options)
        if view_type == 'form':
            arch = etree.fromstring(result['arch'])
            sheet = arch.xpath('//sheet')
            if sheet and not arch.xpath("//field[@name='justification']"):
                # Department, Priority and Justification: header info block,
                # left column, in that order (Justification below Priority).
                header_groups = arch.xpath('//sheet/group[1]/group')
                if len(header_groups) >= 1:
                    left_col = header_groups[0]
                    etree.SubElement(left_col, 'field', {'name': 'department_id'})
                    etree.SubElement(left_col, 'field', {'name': 'priority'})
                    etree.SubElement(left_col, 'field', {
                        'name': 'justification',
                        'placeholder': 'Reason / business justification for this purchase',
                    })

                # MMD Command Ref: directly below Terms and Conditions.
                terms_field = arch.xpath(
                    "//field[contains(@placeholder, 'erms and condition')]"
                )
                mmd_field = etree.Element('field', {'name': 'mmd_command_ref'})
                if terms_field:
                    terms_field[0].addnext(mmd_field)
                elif len(header_groups) >= 2:
                    header_groups[1].append(mmd_field)

                # Fallback only: if the standard header columns were not found,
                # show Justification in its own group after the header.
                if not header_groups:
                    first_group = arch.xpath('//sheet/group[1]')
                    if first_group:
                        justification_group = etree.Element('group', {'string': 'Justification'})
                        etree.SubElement(justification_group, 'field', {'name': 'justification', 'nolabel': '1'})
                        first_group[0].addnext(justification_group)

                # Rejected banner, shown only when state == 'mmd_rejected'.
                banner = etree.Element('div', {
                    'class': 'alert alert-danger',
                    'role': 'alert',
                    'invisible': "state != 'mmd_rejected'",
                })
                banner.text = 'This order was REJECTED by MMD (Material Management Department).'
                sheet[0].insert(0, banner)

            # --- MMD Approval workflow buttons + statusbar ---
            header = arch.xpath('//header')
            if header and not arch.xpath("//button[@name='action_send_for_mmd_approval']"):
                # Turn Odoo's own "Confirm Order" buttons into "Send for MMD
                # Approval" IN PLACE: same position, style, visibility and
                # shortcut. Standard Odoo has two of them:
                #   RFQ stage -> grey button (Send RFQ is the main one)
                #   RFQ Sent  -> purple (highlighted) main button
                native_confirm = arch.xpath("//header/button[@name='button_confirm']")
                for btn in native_confirm:
                    btn.set('name', 'action_send_for_mmd_approval')
                    btn.set('string', 'Send for MMD Approval')
                    btn.attrib.pop('context', None)

                statusbar = arch.xpath("//header/field[@widget='statusbar']")
                mmd_groups = 'ad_school_management.group_school_mmd,ad_school_management.group_school_admin'

                # Fallback if a future Odoo version renames those buttons.
                send_btns = []
                if not native_confirm:
                    send_btns.append(etree.Element('button', {
                        'name': 'action_send_for_mmd_approval', 'type': 'object',
                        'string': 'Send for MMD Approval', 'class': 'oe_highlight',
                        'invisible': "state not in ('draft', 'sent')",
                    }))
                # The Approve button IS the native Confirm Order method,
                # with the same context the standard button uses.
                approve_btn = etree.Element('button', {
                    'name': 'button_confirm', 'type': 'object',
                    'string': 'Approve & Confirm Order', 'class': 'oe_highlight',
                    'invisible': "state != 'mmd_approval'",
                    'context': "{'validate_analytic': True}",
                    'groups': mmd_groups,
                    'data-hotkey': 'q',
                })
                reject_btn = etree.Element('button', {
                    'name': 'action_mmd_reject', 'type': 'object',
                    'string': 'Reject',
                    'invisible': "state != 'mmd_approval'",
                    'groups': mmd_groups,
                    'confirm': 'Are you sure you want to reject this order?',
                })
                reset_btn = etree.Element('button', {
                    'name': 'action_mmd_reset_to_draft', 'type': 'object',
                    'string': 'Reset to RFQ',
                    'invisible': "state != 'mmd_rejected'",
                    'groups': mmd_groups,
                })
                new_buttons = send_btns + [approve_btn, reject_btn, reset_btn]

                if statusbar:
                    for btn in new_buttons:
                        statusbar[0].addprevious(btn)
                    statusbar[0].set('statusbar_visible', 'draft,sent,mmd_approval,purchase')
                else:
                    for btn in reversed(new_buttons):
                        header[0].insert(0, btn)

            result['arch'] = etree.tostring(arch, encoding='unicode')
        return result