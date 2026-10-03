from odoo import models, fields, api, _

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

    @api.model
    def get_dashboard_stats(self):
        today = fields.Date.context_today(self)

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

        has_library = 'school.book' in self.env
        total_books = self.env['school.book'].sudo().search_count([]) if has_library else 0
        total_borrowed = self.env['school.book.issue'].sudo().search_count([('state', '=', 'issued')]) if has_library else 0

        total_vehicles = Vehicle.search_count([])
        total_routes = Route.search_count([])

        has_hostel = 'school.hostel.room' in self.env
        if has_hostel:
            rooms = self.env['school.hostel.room'].sudo().search([])
            total_beds = sum(rooms.mapped('capacity'))
            occupied_beds = self.env['school.hostel.allocation'].sudo().search_count([('state', '=', 'allocated')])
            available_beds = max(total_beds - occupied_beds, 0)
        else:
            total_beds = 0
            occupied_beds = 0
            available_beds = 0

        fees = Fee.search([])
        invoiced_fees = sum(fees.filtered(lambda f: f.state == 'invoiced').mapped('net_amount'))
        paid_fees = sum(fees.filtered(lambda f: f.state == 'paid').mapped('net_amount'))
        total_outstanding = invoiced_fees

        total_marked_today = Attendance.search_count([('date', '=', today)])
        present_today = Attendance.search_count([
            ('date', '=', today),
            ('status', 'in', ('present', 'late'))
        ])
        attendance_rate = round((present_today / total_marked_today) * 100, 1) if total_marked_today > 0 else 100.0

        return {
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