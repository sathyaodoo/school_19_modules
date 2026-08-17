from odoo import models, fields, api, _
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
