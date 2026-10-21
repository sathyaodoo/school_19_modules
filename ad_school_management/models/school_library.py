import base64
import logging
from datetime import timedelta
from urllib.parse import quote

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

READING_LEVELS = [
    ('early', 'Early Reader'),
    ('primary', 'Primary'),
    ('middle', 'Middle School'),
    ('secondary', 'Secondary'),
    ('senior', 'Senior Secondary'),
]
RESOURCE_TYPES = [
    ('print', 'Printed Book'),
    ('ebook', 'E-book'),
    ('audiobook', 'Audiobook'),
    ('online', 'Online Resource'),
]
COPY_STATES = [
    ('available', 'Available'),
    ('issued', 'Issued'),
    ('reserved', 'Held for Reservation'),
    ('damaged', 'Damaged'),
    ('missing', 'Missing (Stock Verification)'),
    ('lost', 'Lost'),
    ('written_off', 'Written Off'),
]
# copies that still belong to the library stock
STOCK_STATES = ('available', 'issued', 'reserved', 'damaged')


def _company_setting(env, name, default):
    company = env.company
    return company[name] if name in company._fields else default


def _next_sequence(env, code):
    """Next number of an ir.sequence, whatever company is active.

    ir.sequence.next_by_code() only sees sequences of the ACTIVE company (or
    with no company). The library sequences are created for the main company,
    so on a branch (CBSE / State Board) next_by_code() returns False and the
    record would get '/'. Fall back to the sequence of any company.
    """
    number = env['ir.sequence'].next_by_code(code)
    if number:
        return number
    seq = env['ir.sequence'].sudo().search([('code', '=', code)], limit=1)
    return seq.next_by_id() if seq else False


def _barcode_data_uri(env, value, barcode_type='Code128', width=600, height=120):
    """PNG barcode / QR code embedded in the PDF (no web request needed)."""
    if not value:
        return ''
    try:
        png = env['ir.actions.report'].barcode(barcode_type, value, width=width, height=height)
    except Exception as error:  # e.g. RenderPMError: backend rlPyCairo not installed
        _logger.warning("Library: barcode / QR image could not be drawn (%s). Install the ReportLab "
                        "backend in the Odoo environment: pip install rlPyCairo", error)
        return ''
    return 'data:image/png;base64,%s' % base64.b64encode(png).decode()


# ======================================================================
# Racks / shelves and genres
# ======================================================================
class SchoolLibraryRack(models.Model):
    _name = 'school.library.rack'
    _description = 'Library Rack / Shelf'
    _order = 'name'

    name = fields.Char(string='Rack / Shelf', required=True)
    location = fields.Char(string='Location', help='e.g. Ground floor, left wing')
    description = fields.Text()
    active = fields.Boolean(default=True)
    copy_ids = fields.One2many('school.book.copy', 'rack_id', string='Copies')
    copy_count = fields.Integer(compute='_compute_copy_count', string='No. of Copies')

    _name_uniq = models.Constraint('unique(name)', 'This rack / shelf already exists!')

    def _compute_copy_count(self):
        for rack in self:
            rack.copy_count = len(rack.copy_ids.filtered(lambda c: c.state in STOCK_STATES))


class SchoolBookGenre(models.Model):
    _name = 'school.book.genre'
    _description = 'Book Genre'
    _order = 'name'

    name = fields.Char(string='Genre', required=True, translate=True)
    color = fields.Integer()
    description = fields.Text()
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint('unique(name)', 'This genre already exists!')


# ======================================================================
# Book (title) and its physical copies (accession register)
# ======================================================================
class SchoolBook(models.Model):
    _name = 'school.book'
    _description = 'Library Book'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(string='Book Title', required=True, tracking=True)
    code = fields.Char(string='Book Code', required=True, tracking=True)
    author = fields.Char(string='Author')
    publisher = fields.Char(string='Publisher')
    isbn = fields.Char(string='ISBN', tracking=True)
    edition = fields.Char(string='Edition', help='e.g. 3rd Edition, 2024')
    language = fields.Char(string='Language', default='English')
    # old fixed category, kept for existing data (replaced by genres)
    category = fields.Selection([
        ('academic', 'Academic'),
        ('fiction', 'Fiction'),
        ('non-fiction', 'Non-Fiction'),
        ('science', 'Science'),
        ('history', 'History'),
        ('other', 'Other')
    ], string='Category (old)', default='academic')
    genre_ids = fields.Many2many('school.book.genre', string='Genres')
    reading_level = fields.Selection(READING_LEVELS, string='Reading Level')
    description = fields.Text(string='Summary')
    cover_image = fields.Image(string='Cover', max_width=512, max_height=512)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    price = fields.Monetary(string='Price', currency_field='currency_id',
                            help='Used as the replacement fine when a copy is lost.')
    vendor_id = fields.Many2one('res.partner', string='Vendor / Source')
    rack_id = fields.Many2one('school.library.rack', string='Default Rack / Shelf')

    # Digital resources
    resource_type = fields.Selection(RESOURCE_TYPES, string='Resource Type', default='print', required=True)
    is_digital = fields.Boolean(compute='_compute_is_digital', store=True)
    digital_url = fields.Char(string='Digital Link', help='Link to the e-book, audiobook or online resource.')
    digital_file = fields.Binary(string='Digital File', attachment=True)
    digital_filename = fields.Char()

    # Stock
    copy_ids = fields.One2many('school.book.copy', 'book_id', string='Copies (Accession Register)')
    qty_total = fields.Integer(string='Total Copies', compute='_compute_qty', store=True)
    qty_available = fields.Integer(string='Available Copies', compute='_compute_qty', store=True)

    # Circulation
    issue_ids = fields.One2many('school.book.issue', 'book_id', string='Issues')
    issue_count = fields.Integer(string='Total Issues', compute='_compute_issue_count')
    reservation_ids = fields.One2many('school.book.reservation', 'book_id', string='Reservations')
    waiting_reservation_count = fields.Integer(compute='_compute_reservation_count', string='Waiting Reservations')

    # Reading intelligence
    review_ids = fields.One2many('school.book.review', 'book_id', string='Reviews')
    avg_rating = fields.Float(string='Average Rating', compute='_compute_rating', store=True, digits=(3, 1))
    review_count = fields.Integer(string='No. of Reviews', compute='_compute_rating', store=True)
    times_borrowed = fields.Integer(string='Times Borrowed', compute='_compute_times_borrowed', store=True)

    _code_uniq = models.Constraint('unique(code)', 'The book code must be unique!')

    @api.depends('resource_type')
    def _compute_is_digital(self):
        for book in self:
            book.is_digital = book.resource_type != 'print'

    @api.depends('copy_ids.state')
    def _compute_qty(self):
        for book in self:
            book.qty_total = len(book.copy_ids.filtered(lambda c: c.state in STOCK_STATES))
            book.qty_available = len(book.copy_ids.filtered(lambda c: c.state == 'available'))

    def _compute_issue_count(self):
        for book in self:
            book.issue_count = len(book.issue_ids)

    def _compute_reservation_count(self):
        for book in self:
            book.waiting_reservation_count = len(book.reservation_ids.filtered(lambda r: r.state == 'waiting'))

    @api.depends('review_ids.rating', 'review_ids.active')
    def _compute_rating(self):
        for book in self:
            ratings = [int(r.rating) for r in book.review_ids if r.rating]
            book.review_count = len(ratings)
            book.avg_rating = sum(ratings) / len(ratings) if ratings else 0.0

    @api.depends('issue_ids.state')
    def _compute_times_borrowed(self):
        for book in self:
            book.times_borrowed = len(book.issue_ids.filtered(
                lambda i: i.state in ('issued', 'overdue', 'returned', 'lost')))

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

    def action_view_reservations(self):
        self.ensure_one()
        return {
            'name': _('Reservations'),
            'type': 'ir.actions.act_window',
            'res_model': 'school.book.reservation',
            'view_mode': 'list,form',
            'domain': [('book_id', '=', self.id)],
            'context': {'default_book_id': self.id},
        }

    def action_add_copies(self):
        """'Add Copies' button: opens the accession register of this book."""
        self.ensure_one()
        return {
            'name': _('Copies – %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'school.book.copy',
            'view_mode': 'list,form',
            'domain': [('book_id', '=', self.id)],
            'context': {'default_book_id': self.id, 'default_rack_id': self.rack_id.id,
                        'default_price': self.price, 'default_vendor_id': self.vendor_id.id},
        }

    def action_open_digital(self):
        self.ensure_one()
        if self.digital_url:
            return {'type': 'ir.actions.act_url', 'url': self.digital_url, 'target': 'new'}
        if self.digital_file:
            return {'type': 'ir.actions.act_url', 'target': 'new',
                    'url': '/web/content/school.book/%s/digital_file/%s?download=true'
                           % (self.id, self.digital_filename or 'resource')}
        raise UserError(_("This resource has no digital link or file."))


class SchoolBookCopy(models.Model):
    """One physical copy of a book: the accession register."""
    _name = 'school.book.copy'
    _description = 'Book Copy (Accession)'
    _inherit = ['mail.thread']
    _order = 'accession_no desc'
    _rec_names_search = ['accession_no', 'barcode', 'book_id.name']

    accession_no = fields.Char(string='Accession No.', required=True, readonly=True, copy=False,
                               default='/', index=True)
    book_id = fields.Many2one('school.book', string='Book', required=True, ondelete='cascade',
                              index=True, tracking=True)
    barcode = fields.Char(string='Barcode', copy=False, index=True,
                          help='Printed on the book label (Code128 barcode and QR code). '
                               'Generated automatically (numeric); can be replaced by a '
                               'pre-printed sticker number.')
    rack_id = fields.Many2one('school.library.rack', string='Rack / Shelf', tracking=True)
    state = fields.Selection(COPY_STATES, string='Status', default='available', required=True,
                             tracking=True, index=True)
    # Acquisition history
    acquisition_date = fields.Date(string='Acquired On', default=fields.Date.context_today)
    acquisition_type = fields.Selection([('purchase', 'Purchase'), ('donation', 'Donation'),
                                         ('other', 'Other')], string='Acquired By', default='purchase')
    vendor_id = fields.Many2one('res.partner', string='Vendor / Donor')
    currency_id = fields.Many2one(related='book_id.currency_id')
    price = fields.Monetary(string='Purchase Price', currency_field='currency_id')
    invoice_ref = fields.Char(string='Invoice / Bill Ref')
    # Condition and write-off
    condition_note = fields.Char(string='Condition Note')
    write_off_date = fields.Date(string='Written Off On', readonly=True)
    write_off_reason = fields.Char(string='Write-off Reason')
    last_verified_date = fields.Date(string='Last Stock Verification', readonly=True)
    issue_ids = fields.One2many('school.book.issue', 'copy_id', string='Issue History')
    current_issue_id = fields.Many2one('school.book.issue', compute='_compute_current_issue',
                                       string='Current Issue')
    # Generated from the Barcode (or the accession number): shown in the views, printed on labels.
    # Image addresses (Odoo's own /report/barcode route, the same engine as the printed labels).
    # The views show them with the image_url widget, so nothing is stored.
    barcode_img_url = fields.Char(string='Barcode Image', compute='_compute_barcode_urls')
    qr_img_url = fields.Char(string='QR Code', compute='_compute_barcode_urls')

    _accession_uniq = models.Constraint('unique(accession_no)', 'Accession number must be unique!')
    _barcode_uniq = models.Constraint('unique(barcode)', 'This barcode is already used by another copy!')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('accession_no') or vals.get('accession_no') == '/':
                vals['accession_no'] = _next_sequence(self.env, 'school.book.copy') or '/'
            if not vals.get('barcode'):
                vals['barcode'] = self._new_barcode() or vals['accession_no']
            if not vals.get('rack_id') and vals.get('book_id'):
                vals['rack_id'] = self.env['school.book'].browse(vals['book_id']).rack_id.id
        return super().create(vals_list)

    @api.model
    def _new_barcode(self):
        """Next barcode number (its own numeric sequence, separate from the accession number)."""
        return _next_sequence(self.env, 'school.book.copy.barcode')

    def write(self, vals):
        # The list shows '/' as a placeholder for the read-only accession number.
        # Never let it overwrite a real accession number.
        if 'accession_no' in vals and vals['accession_no'] in ('/', False, ''):
            vals = {k: v for k, v in vals.items() if k != 'accession_no'}
        return super().write(vals)

    @api.depends('book_id.name', 'accession_no')
    def _compute_display_name(self):
        for copy in self:
            copy.display_name = '%s – %s' % (copy.accession_no or '', copy.book_id.name or '')

    def _compute_current_issue(self):
        for copy in self:
            copy.current_issue_id = copy.issue_ids.filtered(lambda i: i.state in ('issued', 'overdue'))[:1]

    @api.depends('barcode', 'accession_no')
    def _compute_barcode_urls(self):
        for copy in self:
            value = copy.barcode or (copy.accession_no if copy.accession_no != '/' else False)
            if value:
                code = quote(value, safe='')
                copy.barcode_img_url = '/report/barcode/Code128/%s?width=400&height=80' % code
                copy.qr_img_url = '/report/barcode/QR/%s?width=150&height=150' % code
            else:
                copy.barcode_img_url = False
                copy.qr_img_url = False

    def _label_barcode(self):
        return _barcode_data_uri(self.env, self.barcode or self.accession_no)

    def _label_qr(self):
        return _barcode_data_uri(self.env, self.barcode or self.accession_no, 'QR', 200, 200)

    def action_mark_damaged(self):
        for copy in self:
            if copy.state == 'issued':
                raise UserError(_("%s is issued. Return it first (Return Damaged).", copy.display_name))
            copy.state = 'damaged'

    def action_mark_available(self):
        """Repaired / found again."""
        for copy in self:
            if copy.state in ('issued', 'written_off'):
                raise UserError(_("%s cannot be made available from this status.", copy.display_name))
            copy.state = 'available'
            copy._assign_to_next_reservation()

    def action_write_off(self):
        for copy in self:
            if copy.state == 'issued':
                raise UserError(_("%s is issued. Return it or mark it lost first.", copy.display_name))
            if not copy.write_off_reason:
                raise UserError(_("Enter the Write-off Reason for %s first.", copy.display_name))
            copy.write({'state': 'written_off', 'write_off_date': fields.Date.context_today(copy)})
            copy.message_post(body=_("Written off: %s", copy.write_off_reason))

    def _assign_to_next_reservation(self):
        """A copy became available: hold it for the first waiting reservation."""
        for copy in self.filtered(lambda c: c.state == 'available'):
            reservation = self.env['school.book.reservation'].search(
                [('book_id', '=', copy.book_id.id), ('state', '=', 'waiting')],
                order='request_date, id', limit=1)
            if reservation:
                reservation._make_ready(copy)


# ======================================================================
# Membership
# ======================================================================
class SchoolLibraryMembership(models.Model):
    _name = 'school.library.membership'
    _description = 'Library Membership'
    _inherit = ['mail.thread']
    _order = 'name desc'

    name = fields.Char(string='Card No.', required=True, readonly=True, copy=False, default='/')
    member_type = fields.Selection([('student', 'Student'), ('staff', 'Staff')], string='Member Type',
                                   required=True, default='student')
    student_id = fields.Many2one('school.student', string='Student', index=True)
    employee_id = fields.Many2one('hr.employee', string='Staff Member', index=True)
    member_name = fields.Char(string='Member', compute='_compute_member_name', store=True)
    start_date = fields.Date(string='Valid From', required=True, default=fields.Date.context_today)
    end_date = fields.Date(string='Valid Until')
    max_books = fields.Integer(string='Max Books at a Time',
                               default=lambda self: _company_setting(self.env, 'library_max_books', 3))
    suspended = fields.Boolean(string='Suspended', tracking=True)
    state = fields.Selection([('active', 'Active'), ('expired', 'Expired'), ('suspended', 'Suspended')],
                             string='Status', compute='_compute_state')
    issue_count = fields.Integer(compute='_compute_issue_count', string='Books Out')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = _next_sequence(self.env, 'school.library.membership') or '/'
        return super().create(vals_list)

    @api.depends('student_id.name', 'employee_id.name', 'member_type')
    def _compute_member_name(self):
        for rec in self:
            rec.member_name = (rec.student_id.name if rec.member_type == 'student' else rec.employee_id.name) or ''

    @api.depends('suspended', 'start_date', 'end_date')
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.suspended:
                rec.state = 'suspended'
            elif (rec.end_date and rec.end_date < today) or (rec.start_date and rec.start_date > today):
                rec.state = 'expired'
            else:
                rec.state = 'active'

    def _compute_issue_count(self):
        Issue = self.env['school.book.issue']
        for rec in self:
            rec.issue_count = Issue.search_count(rec._issue_domain() + [('state', 'in', ('issued', 'overdue'))])

    def _issue_domain(self):
        self.ensure_one()
        if self.member_type == 'student':
            return [('student_id', '=', self.student_id.id)]
        return [('employee_id', '=', self.employee_id.id)]

    @api.constrains('member_type', 'student_id', 'employee_id')
    def _check_member(self):
        for rec in self:
            if rec.member_type == 'student' and not rec.student_id:
                raise ValidationError(_("Choose the student."))
            if rec.member_type == 'staff' and not rec.employee_id:
                raise ValidationError(_("Choose the staff member."))
            dup = self.search([('id', '!=', rec.id), ('member_type', '=', rec.member_type),
                               ('student_id', '=', rec.student_id.id), ('employee_id', '=', rec.employee_id.id)],
                              limit=1)
            if dup:
                raise ValidationError(_("%s already has library card %s.", rec.member_name, dup.name))

    def _card_barcode(self):
        return _barcode_data_uri(self.env, self.name)

    def _card_qr(self):
        return _barcode_data_uri(self.env, self.name, 'QR', 200, 200)

    def action_print_card(self):
        return self.env.ref('ad_school_management.action_report_library_card').report_action(self, config=False)


# ======================================================================
# Reservation queue
# ======================================================================
class SchoolBookReservation(models.Model):
    _name = 'school.book.reservation'
    _description = 'Book Reservation'
    _inherit = ['mail.thread']
    _order = 'request_date, id'

    book_id = fields.Many2one('school.book', string='Book', required=True, index=True, tracking=True)
    student_id = fields.Many2one('school.student', string='Student', required=True, index=True, tracking=True)
    request_date = fields.Datetime(string='Requested On', default=fields.Datetime.now, required=True)
    state = fields.Selection([('waiting', 'Waiting'), ('ready', 'Ready to Collect'),
                              ('fulfilled', 'Collected'), ('cancelled', 'Cancelled'), ('expired', 'Expired')],
                             string='Status', default='waiting', required=True, tracking=True)
    copy_id = fields.Many2one('school.book.copy', string='Held Copy', readonly=True)
    hold_until = fields.Date(string='Hold Until', readonly=True)
    queue_position = fields.Integer(string='Queue Position', compute='_compute_queue_position')

    def _compute_queue_position(self):
        for rec in self:
            if rec.state != 'waiting':
                rec.queue_position = 0
                continue
            rec.queue_position = self.search_count([
                ('book_id', '=', rec.book_id.id), ('state', '=', 'waiting'),
                '|', ('request_date', '<', rec.request_date),
                '&', ('request_date', '=', rec.request_date), ('id', '<', rec.id)]) + 1

    @api.constrains('book_id', 'student_id', 'state')
    def _check_duplicate(self):
        for rec in self.filtered(lambda r: r.state in ('waiting', 'ready')):
            if self.search_count([('id', '!=', rec.id), ('book_id', '=', rec.book_id.id),
                                  ('student_id', '=', rec.student_id.id), ('state', 'in', ('waiting', 'ready'))]):
                raise ValidationError(_("%s has already reserved this book.", rec.student_id.name))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.book_id.is_digital:
                raise ValidationError(_("Digital resources do not need a reservation."))
            # a copy is on the shelf right now: hold it immediately
            copy = rec.book_id.copy_ids.filtered(lambda c: c.state == 'available')[:1]
            if copy:
                rec._make_ready(copy)
        return records

    def _make_ready(self, copy):
        self.ensure_one()
        days = _company_setting(self.env, 'library_reservation_hold_days', 3)
        copy.state = 'reserved'
        self.write({'state': 'ready', 'copy_id': copy.id,
                    'hold_until': fields.Date.context_today(self) + timedelta(days=days)})
        partner = self.student_id.partner_id
        self.message_post(
            body=_("%(book)s is ready to collect (copy %(acc)s). It is held until %(date)s.",
                   book=self.book_id.name, acc=copy.accession_no, date=self.hold_until),
            partner_ids=partner.ids if partner.email else [])

    def action_cancel(self):
        for rec in self:
            copy = rec.copy_id if rec.state == 'ready' else False
            rec.write({'state': 'cancelled'})
            if copy and copy.state == 'reserved':
                copy.state = 'available'
                copy._assign_to_next_reservation()

    @api.model
    def _cron_expire_reservations(self):
        today = fields.Date.context_today(self)
        for rec in self.search([('state', '=', 'ready'), ('hold_until', '<', today)]):
            copy = rec.copy_id
            rec.write({'state': 'expired'})
            rec.message_post(body=_("Reservation expired: the book was not collected in time."))
            if copy and copy.state == 'reserved':
                copy.state = 'available'
                copy._assign_to_next_reservation()


# ======================================================================
# Issue / return / renewal / fines
# ======================================================================
class SchoolBookIssue(models.Model):
    _name = 'school.book.issue'
    _description = 'Book Issue'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Issue Ref', required=True, readonly=True, default='/', copy=False)
    book_id = fields.Many2one('school.book', string='Book', required=True, tracking=True, index=True)
    copy_id = fields.Many2one('school.book.copy', string='Copy (Accession / Barcode)', tracking=True,
                              domain="[('book_id', '=', book_id)]",
                              help='Scan or type the barcode / accession number. Left empty, an '
                                   'available copy is chosen when issuing.')
    borrower_type = fields.Selection([('student', 'Student'), ('staff', 'Staff')], string='Borrower',
                                     default='student', required=True)
    student_id = fields.Many2one('school.student', string='Student', tracking=True, index=True)
    employee_id = fields.Many2one('hr.employee', string='Staff Member', tracking=True, index=True)
    borrower_name = fields.Char(string='Borrower Name', compute='_compute_borrower', store=True)
    partner_id = fields.Many2one('res.partner', string='Partner', compute='_compute_borrower', store=True)
    class_id = fields.Many2one(related='student_id.class_id', string='Class', store=True)
    membership_id = fields.Many2one('school.library.membership', string='Library Card', readonly=True)
    issue_date = fields.Date(string='Issue Date', required=True, default=fields.Date.context_today, tracking=True)
    due_date = fields.Date(string='Due Date', required=True, tracking=True,
                           default=lambda self: fields.Date.context_today(self) + timedelta(
                               days=_company_setting(self.env, 'library_loan_days', 14)))
    return_date = fields.Date(string='Return Date', tracking=True)
    renewal_count = fields.Integer(string='Renewals', readonly=True, default=0)
    # --- student review of this book (written from the issue, after the book is returned) ---
    review_id = fields.Many2one('school.book.review', string='Student Review', compute='_compute_review',
                                help="The borrowing student's review of this book (one review per student per book).")
    review_rating = fields.Selection([('1', '1'), ('2', '2'), ('3', '3'), ('4', '4'), ('5', '5')],
                                     string='Rating', compute='_compute_review')
    review_text = fields.Text(string='Review', compute='_compute_review')
    fine_per_day = fields.Float(
        string='Fine per Day', readonly=True, copy=False,
        default=lambda self: self._default_fine_per_day(),
        help='Rate taken from Settings > School Management when the issue is created. '
             'Changing the setting later does not affect existing issues.')
    fine_amount = fields.Float(string='Late Fine', compute='_compute_fine', store=True)
    lost_fine = fields.Float(string='Lost Book Fine', tracking=True)
    damage_fine = fields.Float(string='Damage Fine', tracking=True)
    total_fine = fields.Float(string='Total Fine', compute='_compute_total_fine', store=True)
    fine_state = fields.Selection([('none', 'No Fine'), ('due', 'Due'), ('paid', 'Paid'), ('waived', 'Waived')],
                                  string='Fine Status', compute='_compute_fine_state', store=True,
                                  readonly=False, tracking=True)
    overdue_notified = fields.Boolean(readonly=True, copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('issued', 'Issued'),
        ('overdue', 'Overdue'),
        ('returned', 'Returned'),
        ('lost', 'Lost'),
    ], string='Status', default='draft', required=True, tracking=True)

    @api.model
    def _default_fine_per_day(self):
        return _company_setting(self.env, 'library_fine_per_day', 5.0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = _next_sequence(self.env, 'school.book.issue.seq') or '/'
        return super().create(vals_list)

    @api.depends('borrower_type', 'student_id', 'employee_id')
    def _compute_borrower(self):
        for rec in self:
            if rec.borrower_type == 'staff':
                rec.borrower_name = rec.employee_id.name or ''
                rec.partner_id = rec.employee_id.work_contact_id
            else:
                rec.borrower_name = rec.student_id.name or ''
                rec.partner_id = rec.student_id.partner_id

    @api.constrains('borrower_type', 'student_id', 'employee_id')
    def _check_borrower(self):
        for rec in self:
            if rec.borrower_type == 'student' and not rec.student_id:
                raise ValidationError(_("Choose the student."))
            if rec.borrower_type == 'staff' and not rec.employee_id:
                raise ValidationError(_("Choose the staff member."))

    @api.constrains('issue_date', 'due_date')
    def _check_issue_dates(self):
        for record in self:
            if record.issue_date and record.due_date and record.issue_date > record.due_date:
                raise ValidationError(_("Due date must be after the issue date!"))

    @api.onchange('copy_id')
    def _onchange_copy_id(self):
        if self.copy_id:
            self.book_id = self.copy_id.book_id

    @api.depends('due_date', 'return_date', 'state', 'fine_per_day')
    def _compute_fine(self):
        for rec in self:
            fine = 0.0
            if rec.due_date:
                if rec.state in ('issued', 'overdue'):
                    end_date = rec.return_date or fields.Date.context_today(rec)
                elif rec.state in ('returned', 'lost') and rec.return_date:
                    end_date = rec.return_date
                else:
                    end_date = False
                if end_date and end_date > rec.due_date:
                    fine = (end_date - rec.due_date).days * rec.fine_per_day
            rec.fine_amount = fine

    @api.depends('fine_amount', 'lost_fine', 'damage_fine')
    def _compute_total_fine(self):
        for rec in self:
            rec.total_fine = rec.fine_amount + rec.lost_fine + rec.damage_fine

    @api.depends('total_fine')
    def _compute_fine_state(self):
        for rec in self:
            if rec.fine_state in ('paid', 'waived'):
                continue
            rec.fine_state = 'due' if rec.total_fine > 0 else 'none'

    @api.depends('book_id', 'student_id', 'borrower_type', 'state')
    def _compute_review(self):
        Review = self.env['school.book.review']
        for rec in self:
            review = Review
            if rec.id and rec.borrower_type == 'student' and rec.student_id and rec.book_id:
                review = Review.search([('book_id', '=', rec.book_id.id),
                                        ('student_id', '=', rec.student_id.id)], limit=1)
            rec.review_id = review
            rec.review_rating = review.rating
            rec.review_text = review.review

    # --- helpers -------------------------------------------------------
    def _membership(self):
        self.ensure_one()
        Membership = self.env['school.library.membership']
        if self.borrower_type == 'student':
            return Membership.search([('member_type', '=', 'student'), ('student_id', '=', self.student_id.id)], limit=1)
        return Membership.search([('member_type', '=', 'staff'), ('employee_id', '=', self.employee_id.id)], limit=1)

    def _check_can_borrow(self):
        self.ensure_one()
        membership = self._membership()
        required = _company_setting(self.env, 'library_membership_required', False)
        if not membership and required:
            raise UserError(_("%s has no library membership. Create a library card first.", self.borrower_name))
        limit = membership.max_books if membership else _company_setting(self.env, 'library_max_books', 3)
        if membership and membership.state != 'active':
            raise UserError(_("Library card %(card)s of %(name)s is %(state)s.", card=membership.name,
                              name=self.borrower_name,
                              state=dict(membership._fields['state']._description_selection(self.env))[membership.state]))
        domain = ([('student_id', '=', self.student_id.id)] if self.borrower_type == 'student'
                  else [('employee_id', '=', self.employee_id.id)])
        out = self.search_count(domain + [('state', 'in', ('issued', 'overdue')), ('id', '!=', self.id)])
        if limit and out >= limit:
            raise UserError(_("%(name)s already has %(n)s book(s); the limit is %(limit)s.",
                              name=self.borrower_name, n=out, limit=limit))
        return membership

    # --- actions -------------------------------------------------------
    def action_issue(self):
        for rec in self:
            if rec.state != 'draft':
                continue
            if rec.book_id.is_digital:
                raise UserError(_("%s is a digital resource: open it with 'Open Digital Resource'.", rec.book_id.name))
            membership = rec._check_can_borrow()
            reservation = self.env['school.book.reservation']
            if rec.borrower_type == 'student':
                reservation = reservation.search([('book_id', '=', rec.book_id.id), ('student_id', '=', rec.student_id.id),
                                                  ('state', '=', 'ready')], limit=1)
            copy = rec.copy_id
            if not copy:
                copy = reservation.copy_id or rec.book_id.copy_ids.filtered(lambda c: c.state == 'available')[:1]
            if not copy:
                raise ValidationError(_("No copy of %s is available. Create a reservation instead.", rec.book_id.name))
            if copy.book_id != rec.book_id:
                raise ValidationError(_("Copy %s is not a copy of this book.", copy.accession_no))
            if copy.state == 'reserved' and copy != reservation.copy_id:
                raise ValidationError(_("Copy %s is held for another student's reservation.", copy.accession_no))
            if copy.state not in ('available', 'reserved'):
                raise ValidationError(_("Copy %(acc)s is %(state)s.", acc=copy.accession_no,
                                        state=dict(COPY_STATES)[copy.state]))
            copy.state = 'issued'
            if reservation:
                reservation.write({'state': 'fulfilled'})
            rec.write({'state': 'issued', 'copy_id': copy.id, 'membership_id': membership.id})

    def _release_copy(self, copy_state='available'):
        for rec in self:
            copy = rec.copy_id
            if not copy:
                continue
            copy.state = copy_state
            if copy_state == 'available':
                copy._assign_to_next_reservation()

    def action_return(self):
        for rec in self.filtered(lambda r: r.state in ('issued', 'overdue')):
            rec.write({'return_date': fields.Date.context_today(rec), 'state': 'returned'})
            rec._release_copy('available')

    def action_return_damaged(self):
        for rec in self.filtered(lambda r: r.state in ('issued', 'overdue')):
            rec.write({'return_date': fields.Date.context_today(rec), 'state': 'returned'})
            rec._release_copy('damaged')
            rec.message_post(body=_("Returned damaged. Set the Damage Fine if needed."))

    def action_mark_lost(self):
        for rec in self.filtered(lambda r: r.state in ('issued', 'overdue')):
            rec.write({'return_date': fields.Date.context_today(rec), 'state': 'lost',
                       'lost_fine': rec.book_id.price or rec.lost_fine})
            rec._release_copy('lost')

    def action_renew(self):
        max_renewals = _company_setting(self.env, 'library_max_renewals', 2)
        days = _company_setting(self.env, 'library_loan_days', 14)
        for rec in self:
            if rec.state != 'issued':
                raise UserError(_("Only an issued book that is not overdue can be renewed."))
            if rec.renewal_count >= max_renewals:
                raise UserError(_("%s has already been renewed %s time(s) (the limit).", rec.book_id.name, max_renewals))
            if rec.book_id.waiting_reservation_count:
                raise UserError(_("%s is reserved by other students and cannot be renewed.", rec.book_id.name))
            rec.write({'due_date': max(rec.due_date, fields.Date.context_today(rec)) + timedelta(days=days),
                       'renewal_count': rec.renewal_count + 1})
            rec.message_post(body=_("Renewed until %s.", rec.due_date))

    def action_mark_overdue(self):
        for rec in self:
            if rec.state == 'issued' and fields.Date.context_today(rec) > rec.due_date:
                rec.write({'state': 'overdue'})

    def action_pay_fine(self):
        self.filtered(lambda r: r.total_fine > 0).write({'fine_state': 'paid'})

    def action_waive_fine(self):
        self.filtered(lambda r: r.total_fine > 0).write({'fine_state': 'waived'})

    @api.model
    def _cron_overdue_alerts(self):
        """Daily: mark overdue books and alert the borrower once."""
        today = fields.Date.context_today(self)
        late = self.search([('state', 'in', ('issued', 'overdue')), ('due_date', '<', today)])
        late.filtered(lambda r: r.state == 'issued').write({'state': 'overdue'})
        for rec in late.filtered(lambda r: not r.overdue_notified):
            partner = rec.partner_id
            rec.message_post(
                body=_("Overdue alert: %(book)s was due on %(due)s. Please return it; a fine of "
                       "%(rate)s per day applies.", book=rec.book_id.name, due=rec.due_date, rate=rec.fine_per_day),
                partner_ids=partner.ids if partner.email else [])
            rec.overdue_notified = True
        # recompute running late fines
        late._compute_fine()


# ======================================================================
# Stock verification
# ======================================================================
class SchoolLibraryStockVerification(models.Model):
    _name = 'school.library.stock.verification'
    _description = 'Library Stock Verification'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False, default='/')
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    rack_ids = fields.Many2many('school.library.rack', string='Racks / Shelves',
                                help='Leave empty to verify the whole library.')
    state = fields.Selection([('draft', 'Draft'), ('in_progress', 'Counting'), ('done', 'Done')],
                             default='draft', required=True, tracking=True)
    line_ids = fields.One2many('school.library.stock.verification.line', 'verification_id', string='Copies')
    scan_barcode = fields.Char(string='Scan Barcode', help='Scan or type a barcode / accession number and press Enter.')
    expected_count = fields.Integer(compute='_compute_counts', string='Expected')
    found_count = fields.Integer(compute='_compute_counts', string='Found')
    missing_count = fields.Integer(compute='_compute_counts', string='Missing')
    issued_count = fields.Integer(compute='_compute_counts', string='Out on Loan')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = _next_sequence(self.env, 'school.library.stock.verification') or '/'
        return super().create(vals_list)

    @api.depends('line_ids.found')
    def _compute_counts(self):
        Copy = self.env['school.book.copy']
        for rec in self:
            rec.expected_count = len(rec.line_ids)
            rec.found_count = len(rec.line_ids.filtered('found'))
            rec.missing_count = rec.expected_count - rec.found_count
            domain = [('state', '=', 'issued')]
            if rec.rack_ids:
                domain.append(('rack_id', 'in', rec.rack_ids.ids))
            rec.issued_count = Copy.search_count(domain)

    def action_start(self):
        for rec in self:
            domain = [('state', 'in', ('available', 'reserved', 'damaged', 'missing'))]
            if rec.rack_ids:
                domain.append(('rack_id', 'in', rec.rack_ids.ids))
            copies = self.env['school.book.copy'].search(domain)
            rec.line_ids = [(5, 0, 0)] + [(0, 0, {'copy_id': c.id, 'expected_state': c.state}) for c in copies]
            rec.state = 'in_progress'

    @api.onchange('scan_barcode')
    def _onchange_scan_barcode(self):
        code = (self.scan_barcode or '').strip()
        if not code:
            return
        line = self.line_ids.filtered(lambda l: code in (l.copy_id.barcode, l.copy_id.accession_no))[:1]
        self.scan_barcode = False
        if line:
            line.found = True
        else:
            return {'warning': {'title': _("Not in this count"),
                                'message': _("%s is not expected in this stock verification "
                                             "(other rack, issued, lost or unknown).", code)}}

    def action_validate(self):
        today = fields.Date.context_today(self)
        for rec in self:
            for line in rec.line_ids:
                copy = line.copy_id
                if line.found:
                    vals = {'last_verified_date': today}
                    if copy.state == 'missing':
                        vals['state'] = 'available'
                    copy.write(vals)
                elif copy.state != 'missing':
                    copy.write({'state': 'missing'})
            rec.state = 'done'
            rec.message_post(body=_("Stock verification done: %(found)s found, %(missing)s missing.",
                                    found=rec.found_count, missing=rec.missing_count))


class SchoolLibraryStockVerificationLine(models.Model):
    _name = 'school.library.stock.verification.line'
    _description = 'Stock Verification Line'
    _order = 'rack_name, book_name'

    verification_id = fields.Many2one('school.library.stock.verification', required=True, ondelete='cascade')
    copy_id = fields.Many2one('school.book.copy', string='Copy', required=True)
    book_name = fields.Char(related='copy_id.book_id.name', store=True, string='Book')
    rack_name = fields.Char(related='copy_id.rack_id.name', store=True, string='Rack / Shelf')
    barcode = fields.Char(related='copy_id.barcode')
    expected_state = fields.Selection(COPY_STATES, string='Status Before Count', readonly=True)
    found = fields.Boolean(string='Found')
