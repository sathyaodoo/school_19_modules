from odoo import models, fields, api, _


class SchoolCanteenMealBooking(models.Model):
    _name = 'school.canteen.meal.booking'
    _description = 'Canteen Meal Booking (Day Scholars)'
    _order = 'booking_date desc'

    student_id = fields.Many2one('school.student', string='Student', required=True)
    meal_id = fields.Many2one('school.canteen.meal', string='Meal', required=True)
    booking_date = fields.Date(
        string='Booking Date', required=True, default=fields.Date.context_today,
    )


class SchoolCanteenDailyPlanning(models.Model):
    _name = 'school.canteen.daily.planning'
    _description = 'Canteen Daily Meal Planning'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'planning_date desc'

    name = fields.Char(
        string='Planning ID', required=True, copy=False, readonly=True, default=lambda self: _('New'),
    )
    planning_date = fields.Date(
        string='Planning Date', required=True, default=fields.Date.context_today,
    )
    generated_at = fields.Datetime(
        string='Generated At', readonly=True,
        help='Auto-filled when created by the 6:00 AM scheduled action',
    )

    hosteller_count = fields.Integer(
        string='Hosteller Count', compute='_compute_counts', store=True,
        help='From hostel check-in (allocated) records',
    )
    staff_count = fields.Integer(
        string='Staff Count', compute='_compute_counts', store=True,
        help='From HR attendance, meal_entitled = True',
    )
    booked_day_scholar_count = fields.Integer(
        string='Booked Day Scholar Count', compute='_compute_counts', store=True,
        help='From meal bookings',
    )
    event_participant_count = fields.Integer(
        string='Event Participant Count', default=0,
        help='From events/registrations (manually entered — no Events module in this system yet)',
    )
    total_expected_qty = fields.Integer(
        string='Total Expected Qty', compute='_compute_total_expected_qty', store=True,
    )

    planning_line_ids = fields.One2many(
        'school.canteen.daily.planning.line', 'planning_id', string='Planning Lines',
    )

    @api.depends('planning_date')
    def _compute_counts(self):
        for rec in self:
            if not rec.planning_date:
                rec.hosteller_count = 0
                rec.staff_count = 0
                rec.booked_day_scholar_count = 0
                continue

            rec.hosteller_count = self.env['school.hostel.allocation'].search_count([
                ('state', '=', 'allocated'),
            ])

            # NOTE: this system has no daily HR/staff attendance model
            # (school.attendance is STUDENT attendance only) — so "staff
            # entitled to a meal today" is simplified to: every active
            # employee flagged meal_entitled=True on hr.employee, rather
            # than a true day-by-day present/absent staff attendance
            # check. Revisit this if/when a staff attendance module is
            # added to the system.
            rec.staff_count = self.env['hr.employee'].search_count([
                ('meal_entitled', '=', True),
            ])

            rec.booked_day_scholar_count = self.env['school.canteen.meal.booking'].search_count([
                ('booking_date', '=', rec.planning_date),
            ])

    @api.depends('hosteller_count', 'staff_count', 'booked_day_scholar_count', 'event_participant_count')
    def _compute_total_expected_qty(self):
        for rec in self:
            rec.total_expected_qty = (
                rec.hosteller_count + rec.staff_count
                + rec.booked_day_scholar_count + rec.event_participant_count
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('school.canteen.daily.planning') or _('New')
        return super().create(vals_list)

    def _build_planning_lines(self):
        """Create one planning line per active meal, split by category
        counts. Kept simple: each meal gets the SAME total headcount
        (hosteller + staff + day scholar + event) as its expected qty;
        refine per-meal category logic later if the canteen team wants
        different splits per meal (e.g. Guests only at Lunch)."""
        PlanningLine = self.env['school.canteen.daily.planning.line']
        meals = self.env['school.canteen.meal'].search([('active', '=', True)])
        for rec in self:
            rec.planning_line_ids.unlink()
            for meal in meals:
                PlanningLine.create({
                    'planning_id': rec.id,
                    'meal_id': meal.id,
                    'expected_qty': rec.total_expected_qty,
                })

    def action_recalculate(self):
        for rec in self:
            rec._compute_counts()
            rec._compute_total_expected_qty()
            rec._build_planning_lines()

    @api.model
    def _cron_generate_daily_planning(self):
        """Scheduled action: runs at 6:00 AM every day, auto-creating
        today's Daily Meal Planning record with counts already computed."""
        today = fields.Date.context_today(self)
        existing = self.search([('planning_date', '=', today)], limit=1)
        if existing:
            record = existing
        else:
            record = self.create({
                'planning_date': today,
                'generated_at': fields.Datetime.now(),
            })
        record._build_planning_lines()


class SchoolCanteenDailyPlanningLine(models.Model):
    _name = 'school.canteen.daily.planning.line'
    _description = 'Canteen Daily Meal Planning Line (Meal-wise Breakdown)'
    _order = 'id'

    planning_id = fields.Many2one(
        'school.canteen.daily.planning', string='Planning', required=True, ondelete='cascade',
    )
    meal_id = fields.Many2one('school.canteen.meal', string='Meal', required=True)
    expected_qty = fields.Integer(string='Expected Qty')