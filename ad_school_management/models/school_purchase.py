from odoo import fields, models


class MaintenanceRequestPurchase(models.Model):
    _inherit = 'maintenance.request'

    purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order', tracking=True, copy=False)


class ResPartnerVendor(models.Model):
    _inherit = 'res.partner'

    quality_rating = fields.Selection([
        ('excellent', 'Excellent'),
        ('good', 'Good'),
        ('average', 'Average'),
        ('poor', 'Poor'),
    ], string='Quality Rating', tracking=True)


# ---------------------------------------------------------------------------
# Multi-branch: CBSE / State Board (BRS 4.1 Multi-Board Admission Workflows)
# Each record belongs to a branch (company). Records of the parent company are
# shared with all its branches. See record rules in security/school_security.xml.
# ---------------------------------------------------------------------------
from odoo import api as _mb_api, fields as _mb_fields, models as _mb_models

_BRANCH_MODELS = ['school.academic.year', 'school.academic.term', 'school.class', 'school.section', 'school.subject', 'school.attendance', 'school.exam', 'school.exam.result', 'school.timetable', 'school.promotion', 'school.hostel', 'school.hostel.room', 'school.hostel.allocation', 'school.book', 'school.book.issue', 'school.vehicle', 'school.transport.route', 'school.student.transport.fee', 'school.transport.route.change.request', 'school.transport.attendance']

for _model_name in _BRANCH_MODELS:
    type('SchoolBranch_' + _model_name.replace('.', '_'), (_mb_models.Model,), {
        '_inherit': _model_name,
        '__module__': __name__,
        'company_id': _mb_fields.Many2one(
            'res.company', string='Branch', index=True,
            default=lambda self: self.env.company,
            help="Branch (CBSE / State Board). Records of the main school are shared with all branches."),
    })


class SchoolStudentBranchDefault(_mb_models.Model):
    _inherit = 'school.student'

    @_mb_api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'company_id' in fields_list and not res.get('company_id'):
            res['company_id'] = self.env.company.id
        return res


class SchoolParentBranchDefault(_mb_models.Model):
    _inherit = 'school.parent'

    @_mb_api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'company_id' in fields_list and not res.get('company_id'):
            res['company_id'] = self.env.company.id
        return res