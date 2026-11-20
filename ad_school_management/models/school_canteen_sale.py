from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    """Canteen Sale = Odoo's standard Sales Order (sale.order).

    Every sale at the canteen counter is a normal Sales Order, so everything
    is tracked by the standard apps:

    * one order line per DISH bought, at that dish's Selling Price
      (the bill differs with the dishes and quantities actually taken);
    * each dish is a Kit (its recipe), so the standard Delivery takes the
      recipe's INGREDIENTS out of stock (Inventory + Manufacturing);
    * the customer is invoiced with a standard Customer Invoice and pays
      with the standard Register Payment (Accounting);
    * Sales > Reporting and the Canteen Sales Analysis show every item sold.
    """
    _inherit = 'sale.order'

    is_canteen_sale = fields.Boolean(string='Canteen Sale', copy=True, index=True)
    canteen_customer_type = fields.Selection([
        ('student', 'Student'),
        ('staff', 'Staff'),
        ('guest', 'Guest'),
    ], string='Customer Type', default='student')
    canteen_student_id = fields.Many2one('school.student', string='Student')
    canteen_employee_id = fields.Many2one('hr.employee.public', string='Staff Member')
    canteen_meal_id = fields.Many2one('school.canteen.meal', string='Meal')
    canteen_date = fields.Date(string='Canteen Date', default=fields.Date.context_today)

    @api.onchange('canteen_customer_type')
    def _onchange_canteen_customer_type(self):
        if not self.is_canteen_sale:
            return
        if self.canteen_customer_type != 'student':
            self.canteen_student_id = False
        if self.canteen_customer_type != 'staff':
            self.canteen_employee_id = False
        if self.canteen_customer_type == 'guest':
            walk_in = self.env.ref('ad_school_management.partner_canteen_walk_in', raise_if_not_found=False)
            if walk_in:
                self.partner_id = walk_in

    @api.model
    def _canteen_student_partner(self, student):
        """Students are billed to their first parent/guardian, or to the
        student's own contact when no parent is linked."""
        return student.parent_ids[:1].partner_id or student.partner_id

    @api.onchange('canteen_student_id')
    def _onchange_canteen_student_id(self):
        if self.canteen_student_id:
            self.partner_id = self._canteen_student_partner(self.canteen_student_id)

    @api.onchange('canteen_employee_id')
    def _onchange_canteen_employee_id(self):
        if self.canteen_employee_id:
            partner = self.canteen_employee_id.work_contact_id or self.canteen_employee_id.user_partner_id
            if partner:
                self.partner_id = partner

    @api.onchange('canteen_meal_id')
    def _onchange_canteen_meal_id(self):
        """Choosing a meal pre-fills today's menu dishes (quantity 1 each);
        the cashier then removes what was not taken or changes quantities."""
        if self.is_canteen_sale and self.canteen_meal_id and not self.order_line:
            self._canteen_add_menu_lines()

    def _canteen_menu_items(self):
        """Dishes of the published menu for this order's date and meal."""
        self.ensure_one()
        date = self.canteen_date or fields.Date.context_today(self)
        day = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][date.weekday()]
        menu = self.env['school.canteen.menu'].search([
            ('state', '=', 'published'),
            ('week_start_date', '<=', date),
            ('week_end_date', '>=', date),
        ], order='week_start_date desc', limit=1)
        lines = menu.menu_line_ids.filtered(lambda l: l.day == day and l.meal_id == self.canteen_meal_id)
        return lines.food_item_ids

    def _canteen_add_menu_lines(self):
        self.ensure_one()
        items = self._canteen_menu_items()
        existing = self.order_line.product_id.product_tmpl_id
        commands = [
            fields.Command.create({'product_id': item.product_variant_id.id, 'product_uom_qty': 1.0})
            for item in items - existing if item.product_variant_id
        ]
        if commands:
            self.order_line = commands
        return bool(items)

    def action_canteen_load_menu(self):
        """'Load Menu Items' button."""
        for order in self:
            if order.state not in ('draft', 'sent'):
                raise UserError(_("Menu items can only be added to a draft canteen sale."))
            if not order.canteen_meal_id:
                raise UserError(_("Choose the meal first."))
            if not order._canteen_add_menu_lines():
                raise UserError(_(
                    "No published menu has dishes for %(meal)s on %(date)s. Add the dishes manually.",
                    meal=order.canteen_meal_id.name, date=order.canteen_date))
        return True

    def _canteen_check_lines(self):
        for order in self:
            if not order.is_canteen_sale:
                raise UserError(_("%s is not a canteen sale.", order.name))
            if not order.order_line.filtered(lambda l: not l.display_type and l.product_uom_qty > 0):
                raise UserError(_("Add at least one dish."))
            not_dishes = order.order_line.filtered(
                lambda l: not l.display_type and not l.product_id.product_tmpl_id.is_canteen_dish)
            if not_dishes:
                raise UserError(_(
                    "Only dishes are sold at the canteen counter. Remove: %s",
                    ', '.join(not_dishes.product_id.mapped('name'))))

    def _canteen_check_accounting(self):
        """Clear message instead of an accounting error when the company has
        no Sales journal or the dishes have no income account."""
        for company, orders in self.grouped('company_id').items():
            journal = self.env['account.journal'].search([
                ('type', '=', 'sale'), ('company_id', 'parent_of', company.id),
            ], limit=1)
            dishes = orders.order_line.filtered(lambda l: not l.display_type).product_id
            no_income = dishes.filtered(
                lambda p: not p.product_tmpl_id.with_company(company)._get_product_accounts()['income'])
            if not journal or no_income:
                raise UserError(_(
                    "Accounting is not set up for %(company)s, so the canteen bill cannot be created. "
                    "Set the company's country and install its accounting localisation "
                    "(e.g. India - Accounting) so it has a Sales journal and income accounts, "
                    "or set an Income Account on the dish or its product category.%(details)s",
                    company=company.name,
                    details=(_(" Dishes without an income account: %s.", ', '.join(no_income.mapped('name')))
                             if journal and no_income else _(" There is no Sales journal."))))

    def _canteen_confirm_and_deliver(self):
        """Confirm the Sales Order (standard) and close its Delivery: the
        dishes have been served. A dish WITH a recipe is a Kit, so its
        delivery moves are the recipe's ingredients and they leave stock. A
        dish WITHOUT a recipe has nothing to take out of stock: its move is
        cancelled (it is invoiced on the ordered quantity anyway)."""
        for order in self:
            if order.state in ('draft', 'sent'):
                order.action_confirm()
            for picking in order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
                moves = picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel'))
                recipe_moves = moves.filtered(lambda m: m.bom_line_id)
                (moves - recipe_moves)._action_cancel()
                if not recipe_moves:
                    continue
                for move in recipe_moves:
                    move.quantity = move.product_uom_qty
                    move.picked = True
                picking.with_context(skip_backorder=True, skip_sms=True, skip_immediate=True).button_validate()

    def action_canteen_confirm_later(self):
        """'Confirm (bill later)' button: confirm and deliver now, invoice
        later with 'Bill Selected' (one invoice per customer)."""
        self._canteen_check_lines()
        self._canteen_confirm_and_deliver()
        return True

    def action_canteen_bill_selected(self):
        """'Bill Selected' (Canteen Sales list): one DRAFT customer invoice
        per customer for the selected confirmed orders that are still to
        invoice (standard sale invoicing groups them by customer)."""
        orders = self.filtered(lambda o: o.is_canteen_sale and o.state == 'sale'
                               and o.invoice_status == 'to invoice')
        if not orders:
            raise UserError(_("Nothing to bill: the selected canteen sales are not confirmed yet or "
                              "are already invoiced."))
        orders._canteen_check_accounting()
        invoices = orders._create_invoices()
        action = self.env['ir.actions.act_window']._for_xml_id('account.action_move_out_invoice_type')
        action.update({
            'domain': [('id', 'in', invoices.ids)],
            'context': {'default_move_type': 'out_invoice'},
        })
        if len(invoices) == 1:
            action.update({'views': [(False, 'form')], 'view_mode': 'form', 'res_id': invoices.id})
        return action

    def action_canteen_checkout(self):
        """'Confirm & Invoice' button: one click at the counter.

        Confirms the Sales Order (standard), closes its Delivery (ingredients
        of dishes with a recipe leave stock), creates and posts the Customer
        Invoice (standard Accounting), then opens the invoice so the cashier
        can click Register Payment."""
        self.ensure_one()
        self._canteen_check_lines()
        invoices = self.invoice_ids.filtered(lambda m: m.state != 'cancel')
        if not invoices:
            self._canteen_check_accounting()
        self._canteen_confirm_and_deliver()
        if not invoices:
            invoices = self._create_invoices()
        invoices.filtered(lambda m: m.state == 'draft').action_post()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Canteen Invoice'),
            'res_model': 'account.move',
            'res_id': invoices[:1].id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }


class PurchaseOrder(models.Model):
    """Canteen Purchase = Odoo's standard Purchase Order: vendors, vendor
    prices, the school's MMD approval, Receipts into stock and Vendor Bills
    all work exactly as for any other purchase."""
    _inherit = 'purchase.order'

    is_canteen_purchase = fields.Boolean(string='Canteen Purchase', copy=True, index=True)