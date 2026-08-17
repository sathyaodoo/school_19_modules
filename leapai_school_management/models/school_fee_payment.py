# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SchoolFeePayment(models.Model):
    _name = 'school.fee.payment'
    _description = 'Fee Payment'
    _order = 'payment_date desc'

    name = fields.Char(string='Receipt Number', readonly=True, copy=False, default='New')
    student_id = fields.Many2one('school.student', string='Student', required=True)
    fee_structure_id = fields.Many2one('school.fee.structure', string='Fee Structure')
    amount = fields.Monetary(string='Amount', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    payment_date = fields.Date(string='Payment Date', default=fields.Date.today)
    payment_method = fields.Selection([
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('online', 'Online'),
    ], string='Payment Method', default='cash')
    reference = fields.Char(string='Reference')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft')
    note = fields.Char(string='Notes')

    @api.onchange('fee_structure_id')
    def _onchange_fee_structure(self):
        if self.fee_structure_id:
            self.amount = self.fee_structure_id.amount
            self.currency_id = self.fee_structure_id.currency_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('school.fee.payment') or 'New'
        return super().create(vals_list)

    def action_pay(self):
        for record in self:
            if record.state != 'draft':
                raise UserError(_('Only draft payments can be confirmed.'))
            record.state = 'paid'

    def action_cancel(self):
        for record in self:
            if record.state == 'cancelled':
                raise UserError(_('Payment is already cancelled.'))
            record.state = 'cancelled'

    def action_reset_draft(self):
        for record in self:
            if record.state != 'cancelled':
                raise UserError(_('Only cancelled payments can be reset to draft.'))
            record.state = 'draft'
