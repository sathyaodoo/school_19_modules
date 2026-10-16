from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrLeaveType(models.Model):
    """School rules on top of the standard Time Off Type.

    A type with 'School 3-Level Approval' enabled always uses the standard
    'both' validation (To Approve -> Second Approval -> Approved). The school
    levels are mapped onto those standard states by hr.leave:

        To Approve       -> Admin (1st level)
        Second Approval  -> HR Manager (2nd level), then Principal (final)
        Approved         -> done
    """
    _inherit = 'hr.leave.type'

    school_approval_workflow = fields.Boolean(
        string='School 3-Level Approval',
        help='Admin (1st level) -> HR Manager (2nd level) -> Principal (final approval).',
    )
    school_is_medical = fields.Boolean(
        string='Medical Leave',
        help='Exempt from the prior-notice rules, but a medical certificate '
             'is mandatory for any duration.',
    )
    school_notice_days = fields.Integer(
        string='Pre-Inform (days before)', default=3,
        help='Minimum number of days between the request and the first day of leave.',
    )
    school_long_leave_days = fields.Integer(
        string='Long Leave From (days)', default=30,
        help='Leaves of this many calendar days or more need the long-leave notice below.',
    )
    school_long_leave_notice_days = fields.Integer(
        string='Long Leave Notice (days)', default=10,
        help='Minimum prior notice for long leaves.',
    )
    school_principal_lead_days = fields.Integer(
        string='Principal Approval (days before)', default=1,
        help='The Principal must approve at least this many days before the leave starts.',
    )

    @api.onchange('school_approval_workflow')
    def _onchange_school_approval_workflow(self):
        if self.school_approval_workflow:
            self.leave_validation_type = 'both'

    @api.onchange('school_is_medical')
    def _onchange_school_is_medical(self):
        if self.school_is_medical:
            self.support_document = True

    @api.constrains('school_approval_workflow', 'leave_validation_type')
    def _check_school_validation_type(self):
        for leave_type in self:
            if leave_type.school_approval_workflow and leave_type.leave_validation_type != 'both':
                raise ValidationError(_(
                    "Time off type '%s' uses the School 3-Level Approval, so its Approval "
                    "must be \"By Employee's Approver and Time Off Officer\".",
                    leave_type.name,
                ))

    @api.constrains('school_notice_days', 'school_long_leave_days',
                    'school_long_leave_notice_days', 'school_principal_lead_days')
    def _check_school_numbers(self):
        for leave_type in self:
            if min(leave_type.school_notice_days, leave_type.school_long_leave_days,
                   leave_type.school_long_leave_notice_days, leave_type.school_principal_lead_days) < 0:
                raise ValidationError(_("School leave rule values cannot be negative."))