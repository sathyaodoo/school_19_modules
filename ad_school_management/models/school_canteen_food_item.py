from odoo import models, fields, api


class ProductTemplate(models.Model):
    """Food Item Master (BRS 27.2) is explicitly specified as the
    DEFAULT PRODUCT MASTER — so this extends Odoo's own product.template
    rather than duplicating it as a separate custom model, and does NOT
    replace or customize the product form itself. Name, Description,
    Category (categ_id), Unit of Measure (uom_id), Standard Cost
    (standard_price) and Selling Price (list_price) are ALL already
    native product.template fields.

    Reorder Level and Maximum Stock (BRS 27.2) are ALSO already native
    Odoo functionality via the 'stock' module's Reordering Rules
    (stock.warehouse.orderpoint: product_min_qty = Reorder Level,
    product_max_qty = Maximum Stock) — accessed through the
    'Reordering Rules' smart button Odoo adds to the product form
    automatically once 'stock' is installed. So there is NOTHING left
    to add here beyond the is_canteen_item flag used to filter which
    products appear in the Canteen menu."""
    _inherit = 'product.template'

    is_canteen_item = fields.Boolean(
        string='Canteen Food Item',
        help='Tick to make this product appear in the Canteen Food Item Master',
    )

    @api.model
    def _canteen_food_item_domain(self):
        return [('is_canteen_item', '=', True)]