from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    library_fine_per_day = fields.Float(
        string='Library Fine per Day', default=5.0,
        help='Fine charged for each day a library book is returned after its due date.')

    @api.constrains('library_fine_per_day')
    def _check_library_fine_per_day(self):
        for company in self:
            if company.library_fine_per_day < 0:
                raise ValidationError(_("The late return fine cannot be negative."))


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    library_fine_per_day = fields.Float(
        related='company_id.library_fine_per_day', readonly=False,
        string='Fine per Day')
    library_currency_id = fields.Many2one(
        related='company_id.currency_id', string='Library Currency', readonly=True)