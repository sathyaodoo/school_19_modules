from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SchoolAlumniGuidance(models.Model):
    """Career guidance session given by one or more alumni to current students."""
    _name = 'school.alumni.guidance'
    _description = 'Alumni Career Guidance'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char(string='Title', required=True, tracking=True)
    alumni_ids = fields.Many2many('school.alumni', 'school_alumni_guidance_speaker_rel',
                                  'guidance_id', 'alumni_id', string='Alumni Speakers / Counsellors',
                                  domain="[('stage', 'in', ('alumni', 'mentor'))]")
    topic = fields.Selection([
        ('career_planning', 'Career Planning'),
        ('higher_studies', 'Higher Studies & Admissions'),
        ('competitive_exams', 'Competitive Exams'),
        ('study_abroad', 'Study Abroad'),
        ('entrepreneurship', 'Entrepreneurship'),
        ('skills', 'Skills & Employability'),
        ('other', 'Other'),
    ], string='Topic', required=True, default='career_planning', tracking=True)
    mode = fields.Selection([
        ('seminar', 'Seminar'),
        ('workshop', 'Workshop'),
        ('one_on_one', 'One-to-One Counselling'),
        ('webinar', 'Webinar'),
    ], string='Mode', required=True, default='seminar')
    date_start = fields.Datetime(string='Start', required=True, default=fields.Datetime.now)
    duration = fields.Float(string='Duration (hours)', default=1.0)
    venue = fields.Char(string='Venue / Link')
    class_ids = fields.Many2many('school.class', string='For Classes')
    student_ids = fields.Many2many('school.student', 'school_alumni_guidance_student_rel', 'guidance_id',
                                   'student_id', string='Students Attended',
                                   domain="[('student_status', '!=', 'alumni')]")
    student_count = fields.Integer(string='Students', compute='_compute_student_count', store=True)
    description = fields.Html(string='Agenda / Notes')
    feedback = fields.Text(string='Feedback Summary')
    rating = fields.Selection([
        ('1', 'Poor'), ('2', 'Fair'), ('3', 'Good'), ('4', 'Very Good'), ('5', 'Excellent'),
    ], string='Rating')
    organizer_id = fields.Many2one('res.users', string='Organized By', default=lambda self: self.env.user)
    state = fields.Selection([
        ('planned', 'Planned'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='planned', required=True, tracking=True, group_expand=True)

    @api.depends('student_ids')
    def _compute_student_count(self):
        for rec in self:
            rec.student_count = len(rec.student_ids)

    @api.constrains('duration')
    def _check_duration(self):
        if any(rec.duration < 0 for rec in self):
            raise ValidationError(_("The duration cannot be negative."))

    def action_load_class_students(self):
        """Add every current student of the selected classes as attendees."""
        for rec in self:
            if not rec.class_ids:
                raise UserError(_("Select the classes first."))
            students = self.env['school.student'].search([
                ('class_id', 'in', rec.class_ids.ids), ('student_status', '!=', 'alumni')])
            rec.student_ids = [(4, sid) for sid in students.ids]

    def action_done(self):
        for rec in self:
            if not rec.alumni_ids:
                raise UserError(_("Add at least one alumni speaker / counsellor to %s.", rec.name))
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset(self):
        self.write({'state': 'planned'})