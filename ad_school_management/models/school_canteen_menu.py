from datetime import timedelta

from odoo.tools import format_amount
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SchoolCanteenMenu(models.Model):
    _name = 'school.canteen.menu'
    _description = 'Canteen Weekly/Monthly Menu'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'week_start_date desc'

    name = fields.Char(
        string='Menu ID', required=True, copy=False, readonly=True, default=lambda self: _('New'),
    )
    week_start_date = fields.Date(string='Week Start Date', required=True, tracking=True)
    week_end_date = fields.Date(
        string='Week End Date', compute='_compute_week_end_date', store=True,
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('published', 'Published'),
            ('archived', 'Archived'),
        ],
        string='Status', default='draft', required=True, tracking=True,
    )
    created_by = fields.Many2one(
        'res.users', string='Created By', default=lambda self: self.env.uid, readonly=True,
    )
    published_date = fields.Datetime(string='Published Date', copy=False, readonly=True)
    menu_line_ids = fields.One2many(
        'school.canteen.menu.line', 'menu_id', string='Menu Lines',
    )
    notes = fields.Text(string='Notes')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

    @api.depends('week_start_date')
    def _compute_week_end_date(self):
        for rec in self:
            rec.week_end_date = rec.week_start_date + timedelta(days=6) if rec.week_start_date else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('school.canteen.menu') or _('New')
        return super().create(vals_list)

    def action_publish(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only a Draft menu can be published."))
            if not rec.menu_line_ids:
                raise UserError(_("Please add at least one menu line before publishing."))
            rec.write({
                'state': 'published',
                'published_date': fields.Datetime.now(),
            })

    def action_archive_menu(self):
        for rec in self:
            rec.state = 'archived'

    def action_reset_to_draft(self):
        for rec in self:
            rec.state = 'draft'


class SchoolCanteenMenuLine(models.Model):
    _name = 'school.canteen.menu.line'
    _description = 'Canteen Menu Line (Daily Menu Item)'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    menu_id = fields.Many2one(
        'school.canteen.menu', string='Menu', required=True, ondelete='cascade',
    )
    day = fields.Selection(
        [
            ('mon', 'Monday'), ('tue', 'Tuesday'), ('wed', 'Wednesday'),
            ('thu', 'Thursday'), ('fri', 'Friday'), ('sat', 'Saturday'), ('sun', 'Sunday'),
        ],
        string='Day', required=True,
    )
    meal_id = fields.Many2one('school.canteen.meal', string='Meal', required=True)
    # Dishes served (Sambar Rice, Bread Omelette ...): standard products
    # marked "Can be Sold" (Sales app). Their recipes are standard Bills of
    # Materials (Manufacturing app). Field name kept so existing menus stay.
    food_item_ids = fields.Many2many(
        'product.template', string='Dishes',
        domain=[('sale_ok', '=', True)],
    )
    dish_prices = fields.Char(
        string='Dish Prices', compute='_compute_menu_price',
        help="Each dish with its Sales Price, e.g. 'Bread Omelette ₹40.00 · Sambar Rice ₹60.00'.")
    currency_id = fields.Many2one(related='menu_id.currency_id')
    menu_price = fields.Monetary(
        string='Price (all dishes)', compute='_compute_menu_price', currency_field='currency_id',
        help="Sum of the Selling Prices of this meal's dishes (one plate of each). The actual "
             "bill depends on the dishes and quantities the customer takes.")
    remarks = fields.Char(string='Remarks')

    @api.depends('food_item_ids.list_price', 'food_item_ids.name')
    def _compute_menu_price(self):
        for line in self:
            line.menu_price = sum(line.food_item_ids.mapped('list_price'))
            line.dish_prices = ' · '.join(
                '%s %s' % (dish.name, format_amount(self.env, dish.list_price, dish.currency_id))
                for dish in line.food_item_ids)
