import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# The 12 BRS areas in which houses earn points. They are created as records
# of school.house.point.category (data/house_point_category_data.xml, codes
# below); more categories can be created from the screen.
POINT_CATEGORIES = [
    ('academics', 'Academics'),
    ('sports', 'Sports'),
    ('arts', 'Arts'),
    ('discipline', 'Discipline'),
    ('attendance', 'Attendance'),
    ('reading', 'Reading'),
    ('environment', 'Environment'),
    ('innovation', 'Innovation'),
    ('community_service', 'Community Service'),
    ('leadership', 'Leadership'),
    ('cleanliness', 'Cleanliness'),
    ('cultural', 'Cultural Activities'),
]

# Why the points were earned. The championship is meant to reward
# cooperation and community contribution, not only winning (Document 1).
POINT_NATURES = [
    ('achievement', 'Achievement'),
    ('cooperation', 'Teamwork & Cooperation'),
    ('community', 'Community Contribution'),
]

# Default nature of the 12 BRS categories (stored on each category record).
DEFAULT_NATURE = {
    'community_service': 'community',
    'environment': 'community',
    'cleanliness': 'community',
    'leadership': 'cooperation',
    'discipline': 'cooperation',
    'attendance': 'cooperation',
}

# Activity type -> code of the championship category
ACTIVITY_CATEGORY = {
    'sports': 'sports',
    'arts': 'arts',
    'cultural': 'cultural',
    'academic': 'academics',
}

# The points given automatically from Activities (1st / 2nd / 3rd place,
# participation, group participation) are NOT hard-coded: they are set in
# Settings > School Management > House Championship (res.company fields,
# see res_config_settings.py) and read by event.event._school_sync_house_points.


class SchoolHousePointCategory(models.Model):
    """An area in which houses earn points (Academics, Sports, ... or any
    category the school creates)."""
    _name = 'school.house.point.category'
    _description = 'House Point Category'
    _order = 'sequence, name'

    name = fields.Char(string='Category', required=True, translate=True)
    code = fields.Char(string='Code', readonly=True, copy=False,
                       help='Technical code of the built-in BRS categories (used by Activities).')
    # The 12 BRS categories use 10..120; new categories go after them.
    sequence = fields.Integer(default=200)
    default_nature = fields.Selection(
        POINT_NATURES, string='Default Nature', required=True, default='achievement',
        help='Nature suggested when this category is chosen on an award (can be changed there).')
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description')

    _name_uniq = models.Constraint('unique(name)', 'This category already exists!')

    @api.model
    def _get_by_code(self, code):
        return self.sudo().with_context(active_test=False).search([('code', '=', code)], limit=1)


class SchoolHousePoint(models.Model):
    """One award of house points: which house, for what, how many, why."""
    _name = 'school.house.point'
    _description = 'House Points'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string='Reason', required=True, tracking=True,
                       help='What the points are for, e.g. "Cleanest classroom of the week".')
    house_id = fields.Many2one('school.house', string='House (Group)', required=True, index=True,
                               tracking=True, ondelete='cascade')
    house_color = fields.Integer(related='house_id.color')
    board = fields.Selection(related='house_id.board', store=True)
    # Category record (the 12 BRS areas + any category created from the
    # screen). Required in the form and checked on save.
    category_id = fields.Many2one('school.house.point.category', string='Category', tracking=True,
                                  index=True, ondelete='restrict')
    nature = fields.Selection(POINT_NATURES, string='Nature', required=True, default='achievement',
                              tracking=True, index=True,
                              help='Achievement, Teamwork & Cooperation or Community Contribution. '
                                   'The Team Spirit Award goes to the house with the most '
                                   'cooperation and community points.')
    points = fields.Integer(string='Points', required=True, default=1, tracking=True)
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, index=True)
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year',
                                       compute='_compute_academic_year', store=True, index=True)
    # Several students and several classes can share one award (e.g. a
    # cleanliness drive by students of Class 9 and Class 10).
    student_ids = fields.Many2many(
        'school.student', 'school_house_point_student_rel', 'point_id', 'student_id',
        string='Students (Contributors)',
        help='Optional: the students whose effort earned the points. They must belong to this house.')
    class_ids = fields.Many2many(
        'school.class', 'school_house_point_class_rel', 'point_id', 'class_id',
        string='Classes',
        help="Filled in from the students' classes; classes can also be chosen on their own.")
    awarded_by = fields.Many2one('res.users', string='Awarded By', default=lambda self: self.env.user,
                                 readonly=True)
    source = fields.Selection([('manual', 'Awarded by Staff'), ('activity', 'Activity')],
                              string='Source', default='manual', required=True, readonly=True)
    event_id = fields.Many2one('event.event', string='Activity', readonly=True, ondelete='cascade', index=True)
    state = fields.Selection([('confirmed', 'Counted'), ('cancelled', 'Cancelled')],
                             string='Status', default='confirmed', required=True, tracking=True)

    _points_positive = models.Constraint(
        'CHECK(points > 0)',
        'House points must be positive: the championship rewards effort and contribution.',
    )

    @api.depends('date')
    def _compute_academic_year(self):
        Year = self.env['school.academic.year'].sudo()
        for rec in self:
            rec.academic_year_id = rec.date and Year.search(
                [('date_start', '<=', rec.date), ('date_end', '>=', rec.date)], limit=1)

    @api.onchange('category_id')
    def _onchange_category_id(self):
        if self.category_id:
            self.nature = self.category_id.default_nature

    # name / house_id are always saved, so this also runs on create when
    # no category was given at all.
    @api.constrains('category_id', 'name', 'house_id')
    def _check_category(self):
        if self.filtered(lambda rec: not rec.category_id):
            raise ValidationError(_("Choose a Category for the house points."))

    @api.onchange('student_ids')
    def _onchange_student_ids(self):
        houses = self.student_ids.house_id
        if not self.house_id and len(houses) == 1:
            self.house_id = houses
        # add the students' classes (classes chosen by hand are kept)
        self.class_ids |= self.student_ids.class_id

    @api.constrains('student_ids', 'house_id')
    def _check_student_house(self):
        for rec in self:
            wrong = rec.student_ids.filtered(lambda s: s.house_id and s.house_id != rec.house_id)
            if wrong:
                raise ValidationError(_(
                    "These students do not belong to %(house)s: %(students)s.",
                    house=rec.house_id.name,
                    students=", ".join('%s (%s)' % (s.name, s.house_id.name) for s in wrong)))

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_restore(self):
        self.write({'state': 'confirmed'})

    # ------------------------------------------------------------------
    # Championship standings (dashboard)
    # ------------------------------------------------------------------
    @api.model
    def _school_company_board(self, company):
        """Board of a company / branch: its "School Board" field, or, when
        that is empty, guessed from the name ("...CBSE..." -> CBSE,
        "...State..." -> State Board). The main school returns False (= all)."""
        company = company.sudo()
        if company.school_board:
            return company.school_board
        name = (company.name or '').lower()
        if company.parent_id:          # only branches get a board from their name
            if 'cbse' in name:
                return 'cbse'
            if 'state' in name:
                return 'state'
        return False

    @api.model
    def get_championship(self):
        """Standings per board for the current academic year (or all time if
        today is in no academic year)."""
        today = fields.Date.context_today(self)
        year = self.env['school.academic.year'].sudo().search(
            [('date_start', '<=', today), ('date_end', '>=', today)], limit=1)
        domain = [('state', '=', 'confirmed')]
        if year:
            domain.append(('academic_year_id', '=', year.id))
        Point = self.sudo()
        by_nature = {}
        for house, nature, total in Point._read_group(domain, ['house_id', 'nature'], ['points:sum']):
            by_nature.setdefault(house.id, {})[nature] = total
        by_category = {}
        for house, category, total in Point._read_group(domain, ['house_id', 'category_id'], ['points:sum']):
            by_category.setdefault(house.id, {})[category.id] = total
        category_labels = {c.id: c.name for c in self.env['school.house.point.category'].sudo()
                           .with_context(active_test=False).search([])}
        boards = []
        board_labels = dict(self.env['school.house']._fields['board']._description_selection(self.env))
        # Branches selected in the company switcher (top right):
        # CBSE branch -> CBSE only, State Board branch -> State Board only;
        # the main school (no board) or both branches -> both boards.
        # Boards to show, based on the companies ticked in the company
        # switcher (top right):
        #   * only the CBSE branch ticked             -> CBSE only
        #   * only the State Board branch ticked      -> State Board only
        #   * both branches ticked                    -> both boards
        #   * only the main school (no board) ticked  -> both boards
        # Odoo may keep the parent "Santhigiri School" ticked together with a
        # branch, so the parent does NOT force "show all" when at least one
        # ticked branch has a board.
        companies = self.env.companies | self.env.company
        boards_in_scope = {board for board in (self._school_company_board(c) for c in companies) if board}
        show_all = not boards_in_scope
        _logger.info("House Championship: companies %s -> boards %s",
                     companies.mapped('name'), sorted(boards_in_scope) or 'all')
        for board, label in board_labels.items():
            if not show_all and board not in boards_in_scope:
                continue
            houses = self.env['school.house'].sudo().search([('board', '=', board)])
            if not houses:
                continue
            rows = []
            for house in houses:
                natures = by_nature.get(house.id, {})
                categories = by_category.get(house.id, {})
                total = sum(natures.values())
                spirit = natures.get('cooperation', 0) + natures.get('community', 0)
                top = sorted(((v, k) for k, v in categories.items() if v), reverse=True)[:3]
                rows.append({
                    'id': house.id,
                    'name': house.name,
                    'color': house.color,
                    'total': total,
                    'achievement': natures.get('achievement', 0),
                    'cooperation': natures.get('cooperation', 0),
                    'community': natures.get('community', 0),
                    'spirit': spirit,
                    'spirit_share': round(100.0 * spirit / total) if total else 0,
                    'top_categories': ', '.join('%s %s' % (category_labels.get(k, ''), v) for v, k in top),
                })
            rows.sort(key=lambda r: (-r['total'], -r['spirit'], r['name']))
            for rank, row in enumerate(rows, start=1):
                row['rank'] = rank
            leader = rows[0] if rows and rows[0]['total'] else False
            spirit_rows = sorted(rows, key=lambda r: (-r['spirit'], r['name']))
            spirit_leader = spirit_rows[0] if spirit_rows and spirit_rows[0]['spirit'] else False
            boards.append({
                'board': board,
                'label': label,
                'rows': rows,
                'champion': leader and leader['name'],
                'spirit_award': spirit_leader and spirit_leader['name'],
            })
        return {
            'year': year.name if year else False,
            'boards': boards,
            'total_points': sum(r['total'] for b in boards for r in b['rows']),
        }


class SchoolHouse(models.Model):
    _inherit = 'school.house'

    point_ids = fields.One2many('school.house.point', 'house_id', string='House Points')
    total_points = fields.Integer(string='Total Points', compute='_compute_house_points')
    spirit_points = fields.Integer(string='Cooperation & Community Points', compute='_compute_house_points')

    @api.depends('point_ids.points', 'point_ids.state', 'point_ids.nature')
    def _compute_house_points(self):
        totals, spirit = {}, {}
        for house, nature, total in self.env['school.house.point'].sudo()._read_group(
                [('house_id', 'in', self.ids), ('state', '=', 'confirmed')],
                ['house_id', 'nature'], ['points:sum']):
            totals[house.id] = totals.get(house.id, 0) + total
            if nature in ('cooperation', 'community'):
                spirit[house.id] = spirit.get(house.id, 0) + total
        for house in self:
            house.total_points = totals.get(house.id, 0)
            house.spirit_points = spirit.get(house.id, 0)

    def action_view_points(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('House Points – %s', self.name),
            'res_model': 'school.house.point',
            'view_mode': 'list,form,pivot,graph',
            'domain': [('house_id', '=', self.id)],
            'context': {'default_house_id': self.id},
        }