import logging
from odoo import models, fields, api, _
from odoo.tools import format_date, format_datetime
_logger = logging.getLogger(__name__)


class SchoolDashboard(models.TransientModel):
    _name = 'school.dashboard'
    _description = 'School Dashboard KPIs'

    name = fields.Char(string='Title', default='School KPIs Dashboard')

    @api.model
    def action_open_dashboard(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'school_dashboard',
            'name': _('Dashboard'),
            'target': 'current',
        }
        
    def _safe_count(self, model, domain=None):
        # a user who cannot read a model (for example a teacher and the fees) just sees 0 for it
        if model not in self.env:
            return 0
        try:
            with self.env.cr.savepoint():
                return self.env[model].search_count(domain or [])
        except Exception:
            _logger.warning("School dashboard: cannot count %s for user %s", model, self.env.user.login, exc_info=True)
            return 0

    def _safe_search(self, model, domain=None):
        if model not in self.env:
            return self.browse()
        try:
            with self.env.cr.savepoint():
                return self.env[model].search(domain or [])
        except Exception:
            _logger.warning("School dashboard: cannot read %s for user %s", model, self.env.user.login, exc_info=True)
            return self.env[model].browse()    

    @api.model
    def get_dashboard_stats(self):
        today = fields.Date.context_today(self)
        
        total_students = self._safe_count('school.student', [])
        enrolled_students = self._safe_count('school.student', [('student_status', '=', 'enrolled')])
        draft_students = self._safe_count('school.student', [('student_status', '=', 'draft')])
        promoted_students = self._safe_count('school.student', [('student_status', '=', 'promoted')])
        
        total_teachers = self._safe_count('school.teacher', [])
        total_parents = self._safe_count('school.parent', [])
        
        total_admissions = self._safe_count('school.admission', [])
        pending_admissions = self._safe_count('school.admission', [('state', 'in', ('submitted', 'documents', 'verification', 'approval'))])
        approved_admissions = self._safe_count('school.admission', [('state', '=', 'admitted')])
        

        # These are aggregate, school-wide KPI totals (headcounts, sums),
        # not individual sensitive records, and the dashboard itself is
        # already gated by menu/action security. So we compute the counts
        # with sudo() rather than requiring every role (teacher, parent,
        # accountant, ...) to also have its own explicit access row on
        # every single model the dashboard touches (library, hostel, etc).
        # Without this, any model missing an access row for the current
        # user's group raises an AccessError that crashes this whole call.
        Student = self.env['school.student'].sudo()
        Teacher = self.env['school.teacher'].sudo()
        Parent = self.env['school.parent'].sudo()
        Admission = self.env['school.admission'].sudo()
        Vehicle = self.env['school.vehicle'].sudo()
        Route = self.env['school.transport.route'].sudo()
        Fee = self.env['school.student.fee'].sudo()
        Attendance = self.env['school.attendance'].sudo()

        total_students = Student.search_count([])
        enrolled_students = Student.search_count([('student_status', '=', 'enrolled')])
        draft_students = Student.search_count([('student_status', '=', 'draft')])
        promoted_students = Student.search_count([('student_status', '=', 'promoted')])

        total_teachers = Teacher.search_count([])
        total_parents = Parent.search_count([])

        total_admissions = Admission.search_count([])
        pending_admissions = Admission.search_count([('state', '=', 'submitted')])
        approved_admissions = Admission.search_count([('state', '=', 'approved')])
        pending_admissions = Admission.search_count([('state', 'in', ('submitted', 'documents', 'verification', 'approval'))])
        approved_admissions = Admission.search_count([('state', '=', 'admitted')])

        has_library = 'school.book' in self.env
        total_books = self._safe_count('school.book', []) if has_library else 0
        total_borrowed = self._safe_count('school.book.issue', [('state', '=', 'issued')]) if has_library else 0

        total_vehicles = self._safe_count('school.vehicle', [])
        total_routes = self._safe_count('school.transport.route', [])

        has_hostel = 'school.hostel.room' in self.env
        if has_hostel:
            rooms = self._safe_search('school.hostel.room', [])
            total_beds = sum(rooms.mapped('capacity'))
            occupied_beds = self._safe_count('school.hostel.allocation', [('state', '=', 'allocated')])
            available_beds = max(total_beds - occupied_beds, 0)
        else:
            total_beds = 0
            occupied_beds = 0
            available_beds = 0

        fees = self._safe_search('school.student.fee', [])
        invoiced_fees = sum(fees.filtered(lambda f: f.state == 'invoiced').mapped('net_amount'))
        paid_fees = sum(fees.filtered(lambda f: f.state == 'paid').mapped('net_amount'))
        total_outstanding = invoiced_fees

        # Attendance is taken once a day (morning): Present / Absent.
        total_marked_today = Attendance.search_count([('date', '=', today), ('session', '=', 'morning')])
        present_today = Attendance.search_count([
            ('date', '=', today),
            ('session', '=', 'morning'),
            ('status', '=', 'present'),
        ])
        attendance_rate = round((present_today / total_marked_today) * 100, 1) if total_marked_today > 0 else 100.0

        return {
            'early_warning': self.env['school.early.warning'].get_dashboard_stats(),
            'championship': self.env['school.house.point'].get_championship(),
            'has_library': has_library,
            'has_hostel': has_hostel,
            'students': {
                'total': total_students,
                'enrolled': enrolled_students,
                'draft': draft_students,
                'promoted': promoted_students,
            },
            'faculty_parents': {
                'teachers': total_teachers,
                'parents': total_parents,
            },
            'admissions': {
                'total': total_admissions,
                'pending': pending_admissions,
                'approved': approved_admissions,
            },
            'library': {
                'books': total_books,
                'borrowed': total_borrowed,
            },
            'transport': {
                'vehicles': total_vehicles,
                'routes': total_routes,
            },
            'hostel': {
                'total_beds': total_beds,
                'occupied_beds': occupied_beds,
                'available_beds': available_beds,
                'occupancy_rate': round((occupied_beds / total_beds) * 100, 1) if total_beds > 0 else 0.0,
            },
            'finance': {
                'paid': paid_fees,
                'outstanding': total_outstanding,
                'total': paid_fees + total_outstanding,
                'collection_rate': round((paid_fees / (paid_fees + total_outstanding)) * 100, 1) if (paid_fees + total_outstanding) > 0 else 0.0,
            },
            'attendance': {
                'marked': total_marked_today,
                'present': present_today,
                'rate': attendance_rate,
            }
        }

    @api.model
    def get_leave_stats(self):
        """Pending staff leave requests (Teacher Development > Growth Dashboard),
        also called when a new leave request arrives (live refresh)."""
        return self._get_leave_stats()

    @api.model
    def _get_leave_stats(self):
        """Pending staff leave requests for the Leave Requests panel.

        Only Admin, HR Manager and Principal see it (the same people who
        approve leaves); for everybody else 'visible' is False.
        """
        user = self.env.user
        visible = self.env.is_superuser() or any(
            user.has_group(xmlid) for xmlid in (
                'ad_school_management.group_school_admin',
                'ad_school_management.group_school_hr_manager',
                'ad_school_management.group_school_principal',
            ))
        result = {'visible': visible, 'pending_admin': 0, 'pending_hr': 0,
                  'pending_principal': 0, 'total_pending': 0, 'recent': []}
        if not visible:
            return result

        Leave = self.env['hr.leave'].sudo()
        base_domain = [('holiday_status_id.school_approval_workflow', '=', True)]
        if user.company_ids:
            base_domain.append(('employee_company_id', 'in', user.company_ids.ids))
        counts = dict(Leave._read_group(
            base_domain + [('school_approval_stage', 'in', ('admin', 'hr', 'principal'))],
            ['school_approval_stage'], ['__count']))
        result.update({
            'pending_admin': counts.get('admin', 0),
            'pending_hr': counts.get('hr', 0),
            'pending_principal': counts.get('principal', 0),
        })
        result['total_pending'] = result['pending_admin'] + result['pending_hr'] + result['pending_principal']

        stage_labels = dict(Leave._fields['school_approval_stage']._description_selection(self.env))
        recent = Leave.search(
            base_domain + [('school_approval_stage', 'in', ('admin', 'hr', 'principal'))],
            order='create_date desc, id desc', limit=6)
        result['recent'] = [{
            'id': leave.id,
            'employee': leave.employee_id.name or '',
            'leave_type': leave.holiday_status_id.name or '',
            'date_from': format_date(self.env, leave.request_date_from) if leave.request_date_from else '',
            'date_to': format_date(self.env, leave.request_date_to) if leave.request_date_to else '',
            'days': round(leave.number_of_days, 2),
            'reason': leave.private_name or '',
            'stage': leave.school_approval_stage,
            'stage_label': stage_labels.get(leave.school_approval_stage, ''),
            'applied_on': format_datetime(self.env, leave.create_date, dt_format='short') if leave.create_date else '',
        } for leave in recent]
        return result
