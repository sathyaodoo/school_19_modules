from odoo import models, fields, api, _
from odoo.tools import format_amount


class ProductTemplate(models.Model):
    """Canteen products are Odoo's standard products (product.template):

    * INGREDIENTS (is_canteen_item): bread, egg, dal, rice, oil, salt ...
      Bought through Canteen Purchases and kept in stock. Not sold.
    * DISHES (is_canteen_dish): sambar, sambar rice, bread omelette ...
      Sold at the counter. Each dish has a RECIPE = a standard Bill of
      Materials of type "Kit" (Manufacturing app) listing the ingredients
      and quantities for ONE plate. When a dish is sold, the standard
      delivery takes exactly those ingredients out of stock.
    """
    _inherit = 'product.template'

    is_canteen_item = fields.Boolean(
        string='Canteen Ingredient',
        help='Raw material bought for the canteen kitchen (kept in stock, not sold directly).',
    )
    is_canteen_dish = fields.Boolean(
        string='Canteen Dish',
        help='Dish sold at the canteen counter, made from ingredients (see its Recipe).',
    )
    canteen_recipe_bom_id = fields.Many2one(
        'mrp.bom', string='Recipe', compute='_compute_canteen_recipe')
    canteen_recipe_cost = fields.Monetary(
        string='Ingredient Cost', compute='_compute_canteen_recipe', currency_field='currency_id',
        help='Cost of the ingredients for one plate (recipe quantity x ingredient Cost).')
    canteen_margin = fields.Monetary(
        string='Margin', compute='_compute_canteen_recipe', currency_field='currency_id',
        help='Selling Price - Ingredient Cost')
    canteen_recipe_summary = fields.Char(
        string='Ingredients per Plate', compute='_compute_canteen_recipe')

    @api.model
    def _canteen_food_item_domain(self):
        return [('is_canteen_item', '=', True)]

    @api.depends('is_canteen_dish', 'list_price', 'bom_ids.type', 'bom_ids.product_qty',
                 'bom_ids.bom_line_ids.product_qty', 'bom_ids.bom_line_ids.product_uom_id',
                 'bom_ids.bom_line_ids.product_id.standard_price')
    def _compute_canteen_recipe(self):
        for template in self:
            bom = template.bom_ids.filtered(lambda b: b.type == 'phantom' and b.active)[:1] \
                if template.is_canteen_dish else self.env['mrp.bom']
            cost = 0.0
            parts = []
            for line in bom.bom_line_ids:
                component = line.product_id
                qty = line.product_uom_id._compute_quantity(line.product_qty, component.uom_id)
                cost += qty * component.standard_price
                parts.append('%s %g %s' % (component.name, line.product_qty, line.product_uom_id.name))
            per_plate = cost / (bom.product_qty or 1.0) if bom else 0.0
            template.canteen_recipe_bom_id = bom
            template.canteen_recipe_cost = per_plate
            template.canteen_margin = (template.list_price - per_plate) if bom else 0.0
            template.canteen_recipe_summary = ', '.join(parts)

    def action_canteen_open_recipe(self):
        """'Recipe' button: open the dish's Kit Bill of Materials (create it
        the first time) to list the ingredients for ONE plate."""
        self.ensure_one()
        bom = self.canteen_recipe_bom_id
        if not bom:
            bom = self.env['mrp.bom'].create({
                'product_tmpl_id': self.id,
                'type': 'phantom',
                'product_qty': 1.0,
                'product_uom_id': self.uom_id.id,
            })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Recipe: %s', self.name),
            'res_model': 'mrp.bom',
            'res_id': bom.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    @api.depends('name', 'default_code', 'list_price', 'is_canteen_item', 'is_canteen_dish')
    @api.depends_context('canteen_show_price', 'formatted_display_name', 'display_default_code')
    def _compute_display_name(self):
        """On the canteen menu each dish shows its own price, e.g.
        "Sambar Rice – ₹60.00". Only when the context asks for it
        (canteen_show_price); everywhere else products keep their names."""
        super()._compute_display_name()
        if not self.env.context.get('canteen_show_price'):
            return
        for template in self:
            if (template.is_canteen_dish or template.is_canteen_item) and template.display_name:
                price = format_amount(self.env, template.list_price, template.currency_id)
                template.display_name = '%s – %s' % (template.display_name, price)
