from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SchoolAlumniDonationInvoice(models.Model):
    """Adds Odoo customer invoices to alumni donations.

    Kept in its own file and added with _inherit, so the original
    donation model (alumni_donation.py) is not changed at all.

    Works like the standard Odoo invoice flow:
        Create Invoice -> Draft -> (Confirm) -> Posted -> (Pay) -> Paid
    The invoice is NOT confirmed automatically.
    """
    _inherit = 'school.alumni.donation'

    invoice_id = fields.Many2one(
        'account.move', string='Invoice', readonly=True, copy=False,
        help='Customer invoice created for this donation.')
    invoice_state = fields.Selection(
        related='invoice_id.state', string='Invoice Status')
    invoice_payment_state = fields.Selection(
        related='invoice_id.payment_state', string='Payment Status', store=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_donation_product(self):
        product = self.env.ref('ad_school_alumni.product_alumni_donation',
                               raise_if_not_found=False)
        if not product:
            raise UserError(_("The 'Alumni Donation' product is missing. "
                              "Please upgrade the Alumni Management module."))
        return product

    def _prepare_invoice_vals(self, product):
        self.ensure_one()
        purposes = dict(self._fields['purpose'].selection)
        return {
            'move_type': 'out_invoice',
            'partner_id': self.alumni_id.partner_id.id,
            'invoice_date': self.date,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'ref': self.payment_reference or self.name,
            'invoice_origin': self.name,
            'invoice_line_ids': [(0, 0, {
                'product_id': product.id,
                'name': _("Donation %(no)s - %(purpose)s",
                          no=self.name, purpose=purposes.get(self.purpose)),
                'quantity': 1,
                'price_unit': self.amount,
                'tax_ids': [(6, 0, [])],
            })],
        }

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_create_invoice(self):
        product = self._get_donation_product()
        for rec in self:
            if rec.invoice_id and rec.invoice_id.state != 'cancel':
                raise UserError(_("Donation %s already has an invoice.", rec.name))
            if rec.state == 'cancelled':
                raise UserError(_("A cancelled donation cannot be invoiced."))
            if not rec.alumni_id.partner_id:
                raise UserError(_("Alumni %s has no contact linked. Link a contact "
                                  "before creating the invoice.", rec.alumni_id.display_name))
            if rec.amount <= 0:
                raise UserError(_("Donation %s has no amount to invoice.", rec.name))

            # Standard behaviour: the invoice stays in DRAFT.
            # The user reviews it and clicks "Confirm" on the invoice to post it.
            invoice = self.env['account.move'].create(rec._prepare_invoice_vals(product))
            rec.invoice_id = invoice
            rec.message_post(body=_("Draft invoice %s created. Confirm it to post it, "
                                    "then register the payment.",
                                    invoice._get_html_link()))
        if len(self) == 1:
            return self.action_view_invoice()
        return True

    def action_view_invoice(self):
        self.ensure_one()
        return {
            'name': _("Invoice"),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.invoice_id.id,
            'context': {'create': False},
        }

    def action_cancel(self):
        """Extra step only for donations that HAVE an invoice; the original
        cancel logic still runs through super()."""
        for rec in self.filtered('invoice_id'):
            invoice = rec.invoice_id
            if invoice.payment_state in ('paid', 'in_payment', 'partial'):
                raise UserError(_("Donation %s has a paid invoice. Reverse the "
                                  "payment in Accounting before cancelling.", rec.name))
            if invoice.state == 'posted':
                invoice.button_draft()
            if invoice.state == 'draft':
                invoice.button_cancel()
        return super().action_cancel()