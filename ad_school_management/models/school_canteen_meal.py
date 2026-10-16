from odoo import models, fields


class SchoolCanteenCategory(models.Model):
    _name = 'school.canteen.category'
    _description = 'Canteen Applicable Category (Hosteller/Staff/Day Scholar/Guest)'
    _order = 'name'

    name = fields.Char(required=True)


class SchoolCanteenMeal(models.Model):
    _name = 'school.canteen.meal'
    _description = 'Canteen Meal Master'
    _order = 'start_time'

    name = fields.Char(string='Meal Name', required=True, help='e.g. Breakfast, Lunch, Snack, Dinner')
    description = fields.Text(string='Description')
    start_time = fields.Float(
        string='Start Time', required=True,
        help='24-hour format, e.g. 7.0 = 7:00 AM, 8.5 = 8:30 AM',
    )
    end_time = fields.Float(
        string='End Time', required=True,
        help='24-hour format, e.g. 7.0 = 7:00 AM, 8.5 = 8:30 AM',
    )
    default_rate = fields.Float(string='Default Rate (₹)', help='Standard price per meal')
    applicable_category_ids = fields.Many2many(
        'school.canteen.category', string='Applicable Categories',
        help='Hosteller / Staff / Day Scholar / Guest',
    )
    active = fields.Boolean(default=True)