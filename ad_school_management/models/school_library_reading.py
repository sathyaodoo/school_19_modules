from collections import Counter
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

from .school_library import READING_LEVELS

LEVEL_ORDER = [key for key, _label in READING_LEVELS]
READ_STATES = ('returned',)            # a book counts as "read" once returned


class SchoolBookReview(models.Model):
    """A student's rating and review of a book they borrowed and returned.

    Only the STUDENT writes and edits it, from the student portal (My Account
    > School Profiles > Library). Staff can read reviews and, as moderators
    (Library Manager / School Admin), hide or show them - nothing else."""
    _name = 'school.book.review'
    _description = 'Book Review'
    _order = 'date desc, id desc'
    _STAFF_EDITABLE = {'active'}       # moderation only

    book_id = fields.Many2one('school.book', string='Book', required=True, index=True, ondelete='cascade')
    student_id = fields.Many2one('school.student', string='Student', required=True, index=True)
    rating = fields.Selection([('1', '1'), ('2', '2'), ('3', '3'), ('4', '4'), ('5', '5')],
                              string='Rating', required=True, default='4')
    review = fields.Text(string='Review')
    date = fields.Date(string='Date', default=fields.Date.context_today, required=True)
    active = fields.Boolean(default=True, help='Untick to hide an inappropriate review.')

    _book_student_uniq = models.Constraint('unique(book_id, student_id)',
                                           'This student has already reviewed this book.')

    @api.constrains('book_id', 'student_id')
    def _check_has_borrowed(self):
        Issue = self.env['school.book.issue'].sudo()
        for rec in self:
            if rec.book_id.is_digital:
                continue
            if not Issue.search_count([('book_id', '=', rec.book_id.id), ('student_id', '=', rec.student_id.id),
                                       ('state', '=', 'returned')], limit=1):
                raise ValidationError(_("%(student)s can review %(book)s once the book has been returned.",
                                        student=rec.student_id.name, book=rec.book_id.name))

    # --- only the student writes reviews -------------------------------
    def _staff_message(self):
        return _("Book reviews are written by the student only, from the student portal "
                 "(My Account > School Profiles > Library). Staff can hide or show a review.")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('school_review_by_student'):
            raise UserError(self._staff_message())
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get('school_review_by_student') and set(vals) - self._STAFF_EDITABLE:
            raise UserError(self._staff_message())
        return super().write(vals)

    @api.model
    def _portal_save_review(self, student, book, rating, text):
        """Create or update the student's own review (called by the portal
        after checking that the logged-in user IS this student)."""
        rating = str(rating or '')
        if rating not in ('1', '2', '3', '4', '5'):
            raise UserError(_("Choose a rating from 1 to 5 stars."))
        text = (text or '').strip()[:2000]
        Review = self.sudo().with_context(active_test=False, school_review_by_student=True)
        review = Review.search([('book_id', '=', book.id), ('student_id', '=', student.id)], limit=1)
        vals = {'rating': rating, 'review': text, 'date': fields.Date.context_today(self)}
        if review:
            review.write(vals)
        else:
            review = Review.create(dict(vals, book_id=book.id, student_id=student.id))
        return review


class SchoolBookRecommendation(models.Model):
    """A teacher / librarian recommends a book to classes or students."""
    _name = 'school.book.recommendation'
    _description = 'Reading Recommendation'
    _order = 'date desc, id desc'

    book_id = fields.Many2one('school.book', string='Book', required=True, index=True, ondelete='cascade')
    recommended_by = fields.Many2one('res.users', string='Recommended By', default=lambda self: self.env.user,
                                     readonly=True)
    date = fields.Date(default=fields.Date.context_today, required=True)
    class_ids = fields.Many2many('school.class', string='Classes')
    student_ids = fields.Many2many('school.student', string='Students')
    note = fields.Char(string='Why this book?')
    active = fields.Boolean(default=True)

    @api.constrains('class_ids', 'student_ids')
    def _check_target(self):
        for rec in self:
            if not rec.class_ids and not rec.student_ids:
                raise ValidationError(_("Choose at least one class or student for the recommendation."))


class SchoolReadingChallenge(models.Model):
    _name = 'school.reading.challenge'
    _description = 'Reading Challenge'
    _inherit = ['mail.thread']
    _order = 'date_start desc, id desc'

    name = fields.Char(string='Challenge', required=True, tracking=True)
    description = fields.Text()
    date_start = fields.Date(string='Start', required=True, default=fields.Date.context_today)
    date_end = fields.Date(string='End', required=True,
                           default=lambda self: fields.Date.context_today(self) + timedelta(days=30))
    target_books = fields.Integer(string='Target (books)', required=True, default=5)
    genre_ids = fields.Many2many('school.book.genre', string='Only These Genres',
                                 help='Leave empty to count every book.')
    class_ids = fields.Many2many('school.class', string='Classes',
                                 help='Classes taking part (leave empty and add students below, or use all students).')
    house_points = fields.Integer(string='House Points on Completion', default=5,
                                  help='Reading points given to the house of each student who completes the '
                                       'challenge (0 = none).')
    state = fields.Selection([('draft', 'Draft'), ('running', 'Running'), ('closed', 'Closed')],
                             default='draft', required=True, tracking=True)
    participant_ids = fields.One2many('school.reading.challenge.participant', 'challenge_id', string='Participants')
    participant_count = fields.Integer(compute='_compute_stats', string='No. of Participants')
    completed_count = fields.Integer(compute='_compute_stats', string='Completed')

    @api.constrains('date_start', 'date_end', 'target_books')
    def _check_dates(self):
        for rec in self:
            if rec.date_end < rec.date_start:
                raise ValidationError(_("The challenge must end after it starts."))
            if rec.target_books <= 0:
                raise ValidationError(_("The target must be at least 1 book."))

    def _compute_stats(self):
        for rec in self:
            rec.participant_count = len(rec.participant_ids)
            rec.completed_count = len(rec.participant_ids.filtered('completed'))

    def action_add_participants(self):
        """Add the students of the chosen classes (or all students)."""
        for rec in self:
            domain = [('class_id', 'in', rec.class_ids.ids)] if rec.class_ids else []
            students = self.env['school.student'].search(domain) - rec.participant_ids.student_id
            rec.participant_ids = [(0, 0, {'student_id': s.id}) for s in students]

    def action_start(self):
        for rec in self:
            if not rec.participant_ids:
                rec.action_add_participants()
            rec.state = 'running'

    def action_close(self):
        self.write({'state': 'closed'})

    def action_award_house_points(self):
        """Give Reading house points to the house of every student who has
        completed the challenge (once per student)."""
        category = self.env['school.house.point.category']._get_by_code('reading') \
            if 'school.house.point.category' in self.env else False
        for rec in self:
            if not rec.house_points:
                raise UserError(_("Set 'House Points on Completion' first."))
            todo = rec.participant_ids.filtered(lambda p: p.completed and not p.house_points_awarded
                                                and p.student_id.house_id)
            for part in todo:
                self.env['school.house.point'].sudo().create({
                    'name': _("Completed reading challenge: %s", rec.name),
                    'house_id': part.student_id.house_id.id,
                    'category_id': category.id if category else False,
                    'nature': 'achievement',
                    'points': rec.house_points,
                    'student_ids': [(6, 0, part.student_id.ids)],
                    'class_ids': [(6, 0, part.student_id.class_id.ids)],
                })
                part.house_points_awarded = True
            rec.message_post(body=_("House points awarded to %s student(s).", len(todo)))


class SchoolReadingChallengeParticipant(models.Model):
    _name = 'school.reading.challenge.participant'
    _description = 'Reading Challenge Participant'
    _order = 'books_read desc, id'

    challenge_id = fields.Many2one('school.reading.challenge', required=True, ondelete='cascade', index=True)
    student_id = fields.Many2one('school.student', string='Student', required=True, index=True)
    class_id = fields.Many2one(related='student_id.class_id', string='Class')
    house_id = fields.Many2one(related='student_id.house_id', string='House')
    books_read = fields.Integer(string='Books Read', compute='_compute_progress', store=True)
    progress = fields.Float(string='Progress (%)', compute='_compute_progress', store=True)
    completed = fields.Boolean(compute='_compute_progress', store=True)
    house_points_awarded = fields.Boolean(readonly=True)

    _uniq = models.Constraint('unique(challenge_id, student_id)', 'This student is already taking part.')

    @api.depends('student_id', 'challenge_id.date_start', 'challenge_id.date_end',
                 'challenge_id.genre_ids', 'challenge_id.target_books')
    def _compute_progress(self):
        Issue = self.env['school.book.issue'].sudo()
        for part in self:
            ch = part.challenge_id
            if not (part.student_id and ch.date_start and ch.date_end):
                part.books_read = part.progress = 0
                part.completed = False
                continue
            domain = [('student_id', '=', part.student_id.id), ('state', 'in', READ_STATES),
                      ('return_date', '>=', ch.date_start), ('return_date', '<=', ch.date_end)]
            if ch.genre_ids:
                domain.append(('book_id.genre_ids', 'in', ch.genre_ids.ids))
            books = Issue.search(domain).book_id
            part.books_read = len(books)
            part.progress = min(100.0, 100.0 * len(books) / ch.target_books) if ch.target_books else 0
            part.completed = len(books) >= ch.target_books


class SchoolBookIssueReading(models.Model):
    """Returning a book updates the reading challenges of that student."""
    _inherit = 'school.book.issue'

    def write(self, vals):
        result = super().write(vals)
        if 'state' in vals or 'return_date' in vals:
            students = self.student_id
            if students:
                parts = self.env['school.reading.challenge.participant'].sudo().search(
                    [('student_id', 'in', students.ids)])
                if parts:
                    self.env.add_to_compute(parts._fields['books_read'], parts)
                    self.env.add_to_compute(parts._fields['progress'], parts)
                    self.env.add_to_compute(parts._fields['completed'], parts)
        return result


class SchoolStudentLibrary(models.Model):
    """Library and reading profile of a student."""
    _inherit = 'school.student'

    book_issue_ids = fields.One2many('school.book.issue', 'student_id', string='Book Issues')
    book_issue_count = fields.Integer(string='Issued Books Count', compute='_compute_book_issue_count')
    library_membership_id = fields.Many2one('school.library.membership', string='Library Card',
                                            compute='_compute_library_membership')
    reading_level = fields.Selection(READING_LEVELS, string='Reading Level',
                                     help='Set by the teacher / librarian. Used for "Recommended for you".')
    suggested_reading_level = fields.Selection(READING_LEVELS, string='Suggested Level',
                                               compute='_compute_reading_stats')
    books_read_count = fields.Integer(string='Books Read', compute='_compute_reading_stats')
    books_read_this_year = fields.Integer(string='Books Read (Last 12 Months)', compute='_compute_reading_stats')
    reading_frequency = fields.Float(string='Books per Month', compute='_compute_reading_stats', digits=(4, 1),
                                     help='Average over the last 6 months.')
    favourite_genre_ids = fields.Many2many('school.book.genre', string='Favourite Genres',
                                           compute='_compute_reading_stats')
    books_read_ids = fields.Many2many('school.book', string='Books Read List', compute='_compute_reading_stats')
    book_review_ids = fields.One2many('school.book.review', 'student_id', string='Reviews')
    reading_challenge_ids = fields.One2many('school.reading.challenge.participant', 'student_id',
                                            string='Reading Challenges')
    recommended_book_ids = fields.Many2many('school.book', string='Recommended for You',
                                            compute='_compute_recommended_books')

    def _compute_book_issue_count(self):
        # counted with sudo: staff without library access (e.g. the accountant)
        # can still open a student; the issues themselves stay protected.
        Issue = self.env['school.book.issue'].sudo()
        for student in self:
            student.book_issue_count = Issue.search_count(
                [('student_id', '=', student.id), ('state', 'in', ('issued', 'overdue'))]) if student.id else 0

    def _compute_library_membership(self):
        Membership = self.env['school.library.membership'].sudo()
        for student in self:
            student.library_membership_id = Membership.search(
                [('member_type', '=', 'student'), ('student_id', '=', student.id)], limit=1)

    def _read_issues(self):
        self.ensure_one()
        return self.env['school.book.issue'].sudo().search(
            [('student_id', '=', self.id), ('state', 'in', READ_STATES)], order='return_date desc')

    def _compute_reading_stats(self):
        today = fields.Date.context_today(self)
        for student in self:
            issues = student._read_issues()
            books = issues.book_id
            student.books_read_ids = books
            student.books_read_count = len(books)
            student.books_read_this_year = len(issues.filtered(
                lambda i: i.return_date and i.return_date >= today - timedelta(days=365)).book_id)
            recent = issues.filtered(lambda i: i.return_date and i.return_date >= today - timedelta(days=182))
            student.reading_frequency = round(len(recent) / 6.0, 1)
            genre_counter = Counter(g.id for book in books for g in book.genre_ids)
            student.favourite_genre_ids = [(6, 0, [gid for gid, _n in genre_counter.most_common(3)])]
            levels = [LEVEL_ORDER.index(b.reading_level) for b in books if b.reading_level]
            student.suggested_reading_level = LEVEL_ORDER[round(sum(levels) / len(levels))] if levels else False

    def _get_recommended_books(self, limit=6):
        """'Recommended for you': [(book, reason)].

        1. books recommended by a teacher to the student or their class;
        2. books in the student's favourite genres at their reading level;
        3. popular, well-rated books at their level.
        Books already read or currently borrowed are never suggested."""
        self.ensure_one()
        Book = self.env['school.book'].sudo()
        Issue = self.env['school.book.issue'].sudo()
        seen = Issue.search([('student_id', '=', self.id),
                             ('state', 'in', ('issued', 'overdue', 'returned', 'lost'))]).book_id
        level = self.reading_level or self.suggested_reading_level
        levels = []
        if level:
            idx = LEVEL_ORDER.index(level)
            levels = LEVEL_ORDER[max(idx - 1, 0): idx + 2]      # own level and the next one
        result, picked = [], set(seen.ids)

        def add(books, reason):
            for book in books:
                if len(result) >= limit:
                    return
                if book.id not in picked:
                    picked.add(book.id)
                    result.append((book, reason))

        recos = self.env['school.book.recommendation'].sudo().search(
            ['|', ('student_ids', 'in', self.id), ('class_ids', 'in', self.class_id.ids or [0])])
        for reco in recos:
            add(reco.book_id, _("Recommended by %s", reco.recommended_by.name) + (
                ": %s" % reco.note if reco.note else ''))
        level_domain = ['|', ('reading_level', 'in', levels), ('reading_level', '=', False)] if levels else []
        genres = self.favourite_genre_ids
        if genres:
            add(Book.search([('genre_ids', 'in', genres.ids), ('id', 'not in', list(picked))] + level_domain,
                            order='avg_rating desc, times_borrowed desc', limit=limit * 2),
                _("Because you like %s", ', '.join(genres.mapped('name'))))
        add(Book.search([('id', 'not in', list(picked))] + level_domain,
                        order='times_borrowed desc, avg_rating desc', limit=limit * 2),
            _("Popular with readers at your level") if levels else _("Popular in the library"))
        return result

    def _compute_recommended_books(self):
        for student in self:
            student.recommended_book_ids = [(6, 0, [b.id for b, _r in student._get_recommended_books()])]

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