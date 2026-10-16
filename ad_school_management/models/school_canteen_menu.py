from datetime import timedelta

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
    food_item_ids = fields.Many2many(
        'product.template', string='Food Items',
        domain=[('is_canteen_item', '=', True)],
    )
    remarks = fields.Char(string='Remarks')