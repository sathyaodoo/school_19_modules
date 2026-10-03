from odoo import models, fields, api, _, Command
from odoo.exceptions import ValidationError

class SchoolBook(models.Model):
    _name = 'school.book'
    _description = 'Library Book'
    _order = 'name'

    name = fields.Char(string='Book Title', required=True)
    code = fields.Char(string='Book Code', required=True)
    author = fields.Char(string='Author')
    publisher = fields.Char(string='Publisher')
    isbn = fields.Char(string='ISBN')
    category = fields.Selection([
        ('academic', 'Academic'),
        ('fiction', 'Fiction'),
        ('non-fiction', 'Non-Fiction'),
        ('science', 'Science'),
        ('history', 'History'),
        ('other', 'Other')
    ], string='Category', default='academic')
    qty_total = fields.Integer(string='Total Quantity', default=1, required=True)
    qty_available = fields.Integer(string='Available Quantity', compute='_compute_qty_available', store=True)
    issue_ids = fields.One2many('school.book.issue', 'book_id', string='Issues')
    issue_count = fields.Integer(string='Total Issues', compute='_compute_issue_count')

    _code_uniq = models.Constraint(
        'unique(code)', 'The book code must be unique!'
    )

    @api.constrains('qty_total')
    def _check_qty(self):
        for book in self:
            if book.qty_total < 0:
                raise ValidationError(_("Total quantity cannot be negative."))

    @api.depends('qty_total', 'issue_ids.state')
    def _compute_qty_available(self):
        for book in self:
            issued_qty = self.env['school.book.issue'].search_count([
                ('book_id', '=', book.id),
                ('state', 'in', ('issued', 'overdue'))
            ])
            book.qty_available = max(book.qty_total - issued_qty, 0)

    def _compute_issue_count(self):
        for book in self:
            book.issue_count = len(book.issue_ids)

    def action_view_issues(self):
        self.ensure_one()
        return {
            'name': _('Book Issues'),
            'type': 'ir.actions.act_window',
            'res_model': 'school.book.issue',
            'view_mode': 'list,form,pivot,graph',
            'domain': [('book_id', '=', self.id)],
            'context': {'default_book_id': self.id},
        }

class SchoolBookIssue(models.Model):
    _name = 'school.book.issue'
    _description = 'Book Issue'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Issue Ref', required=True, readonly=True, default='/', copy=False)
    book_id = fields.Many2one('school.book', string='Book', required=True, tracking=True)
    student_id = fields.Many2one('school.student', string='Student', required=True, tracking=True)
    partner_id = fields.Many2one('res.partner', string='Partner', related='student_id.partner_id', store=True)
    issue_date = fields.Date(string='Issue Date', required=True, default=fields.Date.context_today, tracking=True)
    due_date = fields.Date(string='Due Date', required=True, tracking=True)
    return_date = fields.Date(string='Return Date', tracking=True)
    fine_amount = fields.Float(string='Fine Amount', compute='_compute_fine', store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('issued', 'Issued'),
        ('returned', 'Returned'),
        ('overdue', 'Overdue')
    ], string='Status', default='draft', required=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('school.book.issue.seq') or '/'
        return super(SchoolBookIssue, self).create(vals_list)

    @api.constrains('issue_date', 'due_date')
    def _check_issue_dates(self):
        for record in self:
            if record.issue_date and record.due_date and record.issue_date > record.due_date:
                raise ValidationError(_("Due date must be after the issue date!"))

    @api.depends('due_date', 'return_date', 'state')
    def _compute_fine(self):
        for rec in self:
            if rec.state in ('issued', 'overdue'):
                end_date = rec.return_date or fields.Date.context_today(rec)
                if end_date > rec.due_date:
                    rec.fine_amount = (end_date - rec.due_date).days * 5.0
                else:
                    rec.fine_amount = 0.0
            elif rec.state == 'returned' and rec.return_date:
                if rec.return_date > rec.due_date:
                    rec.fine_amount = (rec.return_date - rec.due_date).days * 5.0
                else:
                    rec.fine_amount = 0.0
            else:
                rec.fine_amount = 0.0

    def action_issue(self):
        for rec in self:
            if rec.book_id.qty_available <= 0:
                raise ValidationError(_("This book is currently out of stock."))
            rec.write({'state': 'issued'})

    def action_return(self):
        for rec in self:
            today = fields.Date.context_today(rec)
            rec.write({
                'return_date': today,
                'state': 'returned'
            })
            
    def action_mark_overdue(self):
        for rec in self:
            if rec.state == 'issued' and fields.Date.context_today(rec) > rec.due_date:
                rec.write({'state': 'overdue'})

class SchoolStudent(models.Model):
    _inherit = 'school.student'

    book_issue_ids = fields.One2many('school.book.issue', 'student_id', string='Book Issues')
    book_issue_count = fields.Integer(string='Issued Books Count', compute='_compute_book_issue_count')

    def _compute_book_issue_count(self):
        for student in self:
            student.book_issue_count = len(student.book_issue_ids.filtered(lambda i: i.state in ('issued', 'overdue')))

    def action_view_book_issues(self):
        self.ensure_one()
        return {
            'name': _('Book Issues'),
            'type': 'ir.actions.act_window',
            'res_model': 'school.book.issue',
            'view_mode': 'list,form,pivot,graph',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id},
        }

STORE_CATEGORIES = [
    ('textbook', 'Textbook'),
    ('notebook', 'Notebook'),
    ('stationery', 'Stationery'),
    ('uniform', 'Uniform'),
    ('accessories', 'Accessories'),
]


# ---------------------------------------------------------------------------
# 28. Student Store - Item Master (standard product)
# ---------------------------------------------------------------------------
class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_school_store_item = fields.Boolean(string='Student Store Item', default=False)
    store_category = fields.Selection(STORE_CATEGORIES, string='Store Category')

    def action_store_update_stock(self):
        """Open Odoo's stock update screen for this item (method name differs between versions)."""
        self.ensure_one()
        variants = self.product_variant_ids
        for target in (self, variants):
            for method in ('action_update_quantity_on_hand', 'action_open_quants'):
                if hasattr(target, method):
                    return getattr(target, method)()
        raise ValidationError(_("Inventory app is not installed. Install Inventory to manage store stock."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            is_store = vals.get('is_school_store_item', self.env.context.get('default_is_school_store_item'))
            if is_store and not vals.get('default_code'):
                vals['default_code'] = self.env['ir.sequence'].next_by_code('school.store.item') or False
        return super().create(vals_list)


# ---------------------------------------------------------------------------
# 29. Student Store - Class-wise Book List
# ---------------------------------------------------------------------------
class SchoolBookList(models.Model):
    _name = 'school.book.list'
    _description = 'Class-wise Book List'
    _inherit = ['mail.thread']
    _order = 'academic_year_id desc, class_id, section_id'

    name = fields.Char(string='List ID', required=True, readonly=True, default='/', copy=False)
    class_id = fields.Many2one('school.class', string='Class', required=True, tracking=True)
    section_id = fields.Many2one('school.section', string='Section', domain="[('class_id', '=', class_id)]",
                                 help="Leave empty if the list applies to every section of the class.")
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', required=True, tracking=True)
    board = fields.Selection([
        ('cbse', 'CBSE'),
        ('state', 'State Board'),
    ], string='Board', required=True, default='cbse', tracking=True)
    line_ids = fields.One2many('school.book.list.line', 'list_id', string='Books & Items', copy=True)
    total_estimated_cost = fields.Float(string='Total Estimated Cost (per student)',
                                        compute='_compute_total', store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('published', 'Published'),
    ], string='Status', default='draft', required=True, tracking=True)
    published_date = fields.Date(string='Published Date', readonly=True, copy=False)
    active = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('school.book.list') or '/'
        return super().create(vals_list)

    @api.depends('line_ids.subtotal')
    def _compute_total(self):
        for rec in self:
            rec.total_estimated_cost = sum(rec.line_ids.mapped('subtotal'))

    def action_publish(self):
        for rec in self:
            if not rec.line_ids:
                raise ValidationError(_("Add at least one book or item before publishing."))
        self.write({'state': 'published', 'published_date': fields.Date.context_today(self)})

    def action_reset_draft(self):
        self.write({'state': 'draft', 'published_date': False})


class SchoolBookListLine(models.Model):
    _name = 'school.book.list.line'
    _description = 'Book List Line'
    _order = 'sequence, id'

    list_id = fields.Many2one('school.book.list', string='Book List', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one('product.product', string='Item', required=True,
                                 domain="[('is_school_store_item', '=', True)]")
    store_category = fields.Selection(related='product_id.store_category', string='Category')
    quantity = fields.Float(string='Quantity', default=1.0, required=True)
    price_unit = fields.Float(related='product_id.lst_price', string='Unit Price')
    subtotal = fields.Float(string='Subtotal', compute='_compute_subtotal', store=True)

    @api.depends('quantity', 'product_id.lst_price')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.product_id.lst_price

    @api.constrains('quantity')
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_("Quantity must be greater than zero."))


# ---------------------------------------------------------------------------
# 30. Student Store - Counter Sale & Student-wise Sales (standard Sales Order)
# ---------------------------------------------------------------------------
class SaleOrder(models.Model):
    _inherit = 'sale.order'

    is_store_sale = fields.Boolean(string='Student Store Sale', default=False, copy=True)
    student_id = fields.Many2one('school.student', string='Student',
                                 help="Leave empty for a walk-in counter sale.")
    book_list_id = fields.Many2one('school.book.list', string='Book List',
                                   domain="[('state', '=', 'published')]")
    store_payment_mode = fields.Selection([
        ('cash', 'Cash'),
        ('student_account', 'Student Account'),
        ('cheque', 'Cheque'),
        ('online', 'Online'),
    ], string='Payment Mode', default='cash')
    store_payment_status = fields.Selection([
        ('pending', 'Pending'),
        ('partial', 'Partial'),
        ('paid', 'Paid'),
    ], string='Payment Status', compute='_compute_store_payment')
    store_receipt_number = fields.Char(string='Receipt Number', compute='_compute_store_payment')
    store_gross_amount = fields.Monetary(string='Total Amount', compute='_compute_store_amounts')
    store_discount_amount = fields.Monetary(string='Discount', compute='_compute_store_amounts')

    @api.depends('order_line.price_unit', 'order_line.product_uom_qty', 'order_line.discount')
    def _compute_store_amounts(self):
        for order in self:
            lines = order.order_line.filtered(lambda l: not l.display_type)
            order.store_gross_amount = sum(l.price_unit * l.product_uom_qty for l in lines)
            order.store_discount_amount = sum(l.price_unit * l.product_uom_qty * l.discount / 100.0 for l in lines)

    def action_confirm(self):
        res = super().action_confirm()
        # Counter sale: items are handed over immediately, so validate the delivery right away.
        for order in self.filtered('is_store_sale'):
            for picking in order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
                for move in picking.move_ids:
                    move.quantity = move.product_uom_qty
                picking.move_ids.picked = True
                picking.with_context(skip_backorder=True, skip_sms=True)._action_done()
        return res

    def action_store_invoice(self):
        self.ensure_one()
        if self.state in ('draft', 'sent'):
            self.action_confirm()
        invoices = self._create_invoices()
        invoices.action_post()
        return self.action_view_invoice(invoices=invoices)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('default_is_store_sale') and not res.get('partner_id'):
            counter = self.env.ref('ad_school_management.partner_store_counter_customer', raise_if_not_found=False)
            if counter:
                res['partner_id'] = counter.id
        return res

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            is_store = vals.get('is_store_sale', self.env.context.get('default_is_store_sale'))
            if is_store and vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('school.store.sale') or _('New')
        return super().create(vals_list)

    @api.onchange('student_id')
    def _onchange_student_id(self):
        if not self.student_id:
            return
        self.partner_id = self.student_id.partner_id
        lists = self.env['school.book.list'].search([
            ('state', '=', 'published'),
            ('class_id', '=', self.student_id.class_id.id),
            ('academic_year_id', '=', self.student_id.academic_year_id.id),
            ('section_id', 'in', [self.student_id.section_id.id, False]),
        ], order='section_id', limit=2)
        # prefer the section-specific list over the class-wide one
        specific = lists.filtered(lambda l: l.section_id == self.student_id.section_id)
        self.book_list_id = specific[:1] or lists[:1]

    def action_load_book_list(self):
        for order in self:
            if order.state not in ('draft', 'sent'):
                raise ValidationError(_("Book list items can only be loaded on a draft quotation."))
            if not order.book_list_id:
                raise ValidationError(_("Please select a Book List first."))
            existing = order.order_line.mapped('product_id')
            commands = [Command.create({
                'product_id': line.product_id.id,
                'product_uom_qty': line.quantity,
            }) for line in order.book_list_id.line_ids if line.product_id not in existing]
            if not commands:
                raise ValidationError(_("All items of this book list are already on the order."))
            order.write({'order_line': commands})

    @api.depends('invoice_ids.state', 'invoice_ids.payment_state')
    def _compute_store_payment(self):
        for order in self:
            invoices = order.invoice_ids.filtered(lambda m: m.state == 'posted' and m.move_type == 'out_invoice')
            order.store_receipt_number = ', '.join(invoices.mapped('name')) or False
            states = invoices.mapped('payment_state')
            if invoices and all(s in ('paid', 'in_payment') for s in states):
                order.store_payment_status = 'paid'
            elif any(s in ('paid', 'in_payment', 'partial') for s in states):
                order.store_payment_status = 'partial'
            else:
                order.store_payment_status = 'pending'


class SchoolStudent(models.Model):
    _inherit = 'school.student'

    store_order_ids = fields.One2many('sale.order', 'student_id', string='Store Purchases',
                                      domain=[('is_store_sale', '=', True)])