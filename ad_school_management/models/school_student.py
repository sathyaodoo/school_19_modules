from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SchoolStudent(models.Model):
    _name = 'school.student'
    _description = 'Student'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _inherits = {'res.partner': 'partner_id'}
    _order = 'roll_number, name'

    partner_id = fields.Many2one('res.partner', string='Partner', required=True, ondelete='cascade')
    
    admission_no = fields.Char(string='Admission No.', readonly=True, copy=False)
    class_id = fields.Many2one('school.class', string='Class', required=True, tracking=True)
    section_id = fields.Many2one('school.section', string='Section', required=True, tracking=True)
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', required=True, tracking=True)
    roll_number = fields.Char(string='Roll Number', tracking=True, copy=False)
    parent_ids = fields.Many2many('school.parent', 'school_student_parent_rel', 'student_id', 'parent_id', string='Parents/Guardians')
    
    transport_route_id = fields.Many2one('school.transport.route', string='Transport Route')
    
    exam_result_ids = fields.One2many('school.exam.result', 'student_id', string='Exam Results')
    gpa = fields.Float(string='GPA', compute='_compute_gpa', store=True)

    photo = fields.Binary(related='partner_id.image_1920', readonly=False, string='Photo')

    birthday_display = fields.Char(
        string='Birthday Date',
        compute='_compute_birthday_display',
    )
    is_birthday_today = fields.Boolean(
        string='Birthday Today',
        compute='_compute_is_birthday_today',
    )

    @api.depends('date_of_birth')
    def _compute_birthday_display(self):
        for student in self:
            student.birthday_display = (
                student.date_of_birth.strftime('%d %B') if student.date_of_birth else False
            )

    @api.depends('date_of_birth')
    def _compute_is_birthday_today(self):
        today = fields.Date.context_today(self)
        for student in self:
            dob = student.date_of_birth
            student.is_birthday_today = bool(
                dob and dob.day == today.day and dob.month == today.month
            )
 
    _admission_no_uniq = models.Constraint(
        'unique(admission_no)', 'The admission number must be unique!'
    )

    @api.depends('exam_result_ids.gpa')
    def _compute_gpa(self):
        for student in self:
            results = student.exam_result_ids
            if results:
                student.gpa = sum(results.mapped('gpa')) / len(results)
            else:
                student.gpa = 0.0
 
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('admission_no'):
                vals['admission_no'] = self.env['ir.sequence'].next_by_code('school.student.admission') or '/'
            vals['is_student'] = True
            
            if 'student_status' not in vals:
                partner_id = vals.get('partner_id')
                if partner_id:
                    partner = self.env['res.partner'].browse(partner_id)
                    vals['student_status'] = partner.student_status or 'draft'
                else:
                    vals['student_status'] = 'draft'
        return super(SchoolStudent, self).create(vals_list)

    @api.constrains('roll_number', 'class_id', 'section_id', 'academic_year_id')
    def _check_roll_number(self):
        for student in self:
            if student.roll_number:
                duplicate = self.search([
                    ('id', '!=', student.id),
                    ('roll_number', '=', student.roll_number),
                    ('class_id', '=', student.class_id.id),
                    ('section_id', '=', student.section_id.id),
                    ('academic_year_id', '=', student.academic_year_id.id)
                ])
                if duplicate:
                    raise ValidationError(_(
                        "Roll number %s already exists in class %s, section %s for academic year %s!"
                    ) % (student.roll_number, student.class_id.name, student.section_id.name, student.academic_year_id.name))

    @api.constrains('class_id', 'section_id')
    def _check_section_capacity(self):
        for student in self:
            if student.section_id:
                student_count = self.search_count([
                    ('class_id', '=', student.class_id.id),
                    ('section_id', '=', student.section_id.id),
                    ('academic_year_id', '=', student.academic_year_id.id),
                    ('id', '!=', student.id)
                ])
                if student_count >= student.section_id.capacity:
                    raise ValidationError(_(
                        "Section %s has reached its maximum capacity of %s students!"
                    ) % (student.section_id.name, student.section_id.capacity))

    def action_view_partner(self):
        self.ensure_one()
        return {
            'name': _('Contact Details'),
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': self.partner_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_current_month_birthdays(self):
        """Menu action: shows the students with a birthday in the CURRENT
        month, recomputed fresh every time it's opened — so a teacher can
        check this at any point during the month, not just at the moment
        the pop-up first appeared.

        Deliberately does NOT rely on rule_teacher_assigned_classes for
        this particular screen: that rule also lets a mere SUBJECT teacher
        (class_id.teacher_ids) see a class's students, which is correct
        for ordinary student browsing but wider than the birthday spec,
        which says "Class teacher for each student" — i.e. only the one
        teacher who is class_id.class_teacher_id, not every teacher
        assigned to that class. So we search with sudo() to see everyone
        first, then filter down explicitly and strictly to just the
        logged-in teacher's own class(es). Admin/Principal keep seeing
        the full school-wide list, same as anywhere else in the app.
        """
        today = fields.Date.context_today(self)
        current_month = today.month

        all_students = self.sudo().search([('date_of_birth', '!=', False)]).filtered(
            lambda s: s.date_of_birth.month == current_month
        )

        is_admin_or_principal = (
            self.env.user.has_group('ad_school_management.group_school_admin')
            or self.env.user.has_group('ad_school_management.group_school_principal')
        )

        if is_admin_or_principal:
            students = all_students
        else:
            own_teacher = self.env['school.teacher'].sudo().search(
                [('user_id', '=', self.env.uid)], limit=1
            )
            students = all_students.filtered(
                lambda s: own_teacher and s.class_id.class_teacher_id.id == own_teacher.id
            )

        return {
            'name': _('Student Birthdays This Month'),
            'type': 'ir.actions.act_window',
            'res_model': 'school.student',
            'views': [(self.env.ref('ad_school_management.view_school_student_birthday_tree').id, 'list')],
            'domain': [('id', 'in', students.ids)],
            'context': {'create': False},
            'target': 'current',
        }

    @api.model
    def _cron_notify_class_teacher_birthdays(self):
        """Scheduled action (runs on the 1st of every month): find every
        student whose birthday falls in the current month, group them by
        their class teacher, and push a pop-up notification (plus an inbox
        message as a fallback) to each teacher listing their students."""
        today = fields.Date.context_today(self)
        current_month = today.month
        month_name = today.strftime('%B')

        students = self.search([('date_of_birth', '!=', False)])
        birthday_students = students.filtered(
            lambda s: s.date_of_birth.month == current_month
        )
        if not birthday_students:
            return

        # Group the students by their class's class teacher
        students_by_teacher = {}
        for student in birthday_students:
            teacher = student.class_id.class_teacher_id
            if not teacher:
                continue
            students_by_teacher.setdefault(teacher, self.env['school.student'])
            students_by_teacher[teacher] |= student

        for teacher, teacher_students in students_by_teacher.items():
            partner = teacher.user_id.partner_id if teacher.user_id else False
            if not partner:
                continue

            ordered_students = teacher_students.sorted(key=lambda s: s.date_of_birth.day)

            # Build one line per student: Name, DOB, birthday date this month.
            # Used for BOTH the pop-up and the inbox message, so the pop-up
            # itself carries the required content, not just a headcount.
            student_lines_plain = [
                _(
                    "%(name)s — DOB: %(dob)s (birthday: %(day)s %(month)s)"
                ) % {
                    'name': student.name,
                    'dob': student.date_of_birth,
                    'day': student.date_of_birth.day,
                    'month': month_name,
                }
                for student in ordered_students
            ]

            # Inbox message (fallback, and a durable record of the notification)
            body = _(
                "Students in your class with a birthday this month (%(month)s):"
            ) % {'month': month_name}
            body += "<ul>%s</ul>" % "".join(
                "<li>%s</li>" % line for line in student_lines_plain
            )
            self.env['mail.thread'].message_notify(
                partner_ids=partner.ids,
                subject=_("Student Birthdays This Month – %s") % month_name,
                body=body,
            )

            # Real-time pop-up toast, shown immediately if the teacher's
            # browser session is open (same mechanism Odoo's own UI uses
            # for its toast notifications). Carries the same name/DOB/date
            # content required by the spec, not just a count.
            self.env['bus.bus']._sendone(
                partner,
                'simple_notification',
                {
                    'type': 'info',
                    'title': _("Student Birthdays This Month"),
                    'message': "\n".join(student_lines_plain),
                    'sticky': True,
                },
            )