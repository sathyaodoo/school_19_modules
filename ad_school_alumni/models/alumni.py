from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


STAGES = [
    ('graduate', 'Graduate'),
    ('alumni', 'Alumni'),
    ('mentor', 'Mentor'),
]


class SchoolAlumni(models.Model):
    """An alumni of the school.

    Life cycle (the "Student" step is the school.student record itself):
        Student -> Graduate -> Alumni -> Mentor
      * Graduate : created when a student is graduated (Graduate Students
                   wizard / "Graduate" button on the student), or entered by hand
                   for older batches.
      * Alumni   : profile confirmed and registered in the alumni network.
      * Mentor   : alumni who volunteers to mentor current students.

    Contact details (name, photo, e-mail, phone, address) live on the linked
    contact (res.partner); a graduated student keeps the SAME contact.
    """
    _name = 'school.alumni'
    _description = 'Alumni'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _inherits = {'res.partner': 'partner_id'}
    _order = 'graduation_year desc, name'

    partner_id = fields.Many2one('res.partner', string='Contact', required=True, ondelete='restrict',
                                 index=True)
    code = fields.Char(string='Alumni Code', readonly=True, copy=False, default='/')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    stage = fields.Selection(STAGES, string='Stage', default='graduate', required=True, tracking=True,
                             group_expand=True)

    # ----- School details (filled from the student when graduated) -----
    student_id = fields.Many2one('school.student', string='Student Record', index=True, copy=False,
                                 help='The student record this alumni graduated from (if in the system).')
    admission_no = fields.Char(string='Admission No', copy=False)
    last_class_id = fields.Many2one('school.class', string='Last Class')
    last_section_id = fields.Many2one('school.section', string='Last Section')
    graduation_academic_year_id = fields.Many2one('school.academic.year', string='Graduation Academic Year')
    graduation_year = fields.Integer(string='Graduation Year', required=True, tracking=True,
                                     default=lambda self: fields.Date.context_today(self).year)
    graduation_date = fields.Date(string='Graduation Date')
    batch = fields.Char(string='Batch', compute='_compute_batch', store=True,
                        help='e.g. "Batch of 2026"')

    # ----- Personal / contact extras -----
    gender = fields.Selection([('male', 'Male'), ('female', 'Female'), ('other', 'Other')], string='Gender')
    linkedin_url = fields.Char(string='LinkedIn')
    current_city = fields.Char(string='Current City')
    current_country_id = fields.Many2one('res.country', string='Current Country')

    # ----- Higher education -----
    education_ids = fields.One2many('school.alumni.education', 'alumni_id', string='Higher Education')
    highest_qualification = fields.Char(string='Highest Qualification', compute='_compute_highest_qualification',
                                        store=True)

    # ----- Profession -----
    profession = fields.Char(string='Profession / Designation', tracking=True)
    organization = fields.Char(string='Organization', tracking=True)
    industry_id = fields.Many2one('school.alumni.industry', string='Industry')
    employment_status = fields.Selection([
        ('studying', 'Higher Studies'),
        ('employed', 'Employed'),
        ('self_employed', 'Self-employed / Business'),
        ('seeking', 'Seeking Opportunity'),
        ('other', 'Other'),
    ], string='Current Status', tracking=True)
    career_ids = fields.One2many('school.alumni.career', 'alumni_id', string='Career History')

    # ----- Achievements -----
    achievement_ids = fields.One2many('school.alumni.achievement', 'alumni_id', string='Achievements')
    achievement_count = fields.Integer(compute='_compute_counts')

    # ----- Mentorship -----
    expertise_ids = fields.Many2many('school.alumni.expertise', string='Expertise Areas')
    mentor_available = fields.Boolean(string='Available to Mentor', default=True)
    max_mentees = fields.Integer(string='Maximum Active Mentees', default=0,
                                 help='How many students this mentor can guide at the same time. 0 = no limit.')
    mentorship_ids = fields.One2many('school.alumni.mentorship', 'mentor_id', string='Mentorships')
    mentorship_count = fields.Integer(compute='_compute_counts')
    active_mentee_count = fields.Integer(string='Active Mentees', compute='_compute_counts')

    # ----- Donations -----
    donation_ids = fields.One2many('school.alumni.donation', 'alumni_id', string='Donations')
    donation_count = fields.Integer(compute='_compute_counts')
    currency_id = fields.Many2one(related='company_id.currency_id')
    donation_total = fields.Monetary(string='Total Donated', compute='_compute_counts',
                                     currency_field='currency_id')

    # ----- Career guidance & events -----
    guidance_ids = fields.Many2many('school.alumni.guidance', 'school_alumni_guidance_speaker_rel',
                                    'alumni_id', 'guidance_id', string='Career Guidance Sessions')
    guidance_count = fields.Integer(compute='_compute_counts')
    event_attendee_ids = fields.One2many('school.alumni.event.attendee', 'alumni_id', string='Event Participation')
    event_count = fields.Integer(compute='_compute_counts')

    notes = fields.Html(string='Notes')

    _student_uniq = models.Constraint('unique(student_id)',
                                      'This student already has an alumni profile!')
    _code_uniq = models.Constraint('unique(code)', 'The alumni code must be unique!')

    # ------------------------------------------------------------------
    # computes
    # ------------------------------------------------------------------
    @api.depends('graduation_year')
    def _compute_batch(self):
        for rec in self:
            rec.batch = _('Batch of %s', rec.graduation_year) if rec.graduation_year else False

    @api.depends('education_ids.degree', 'education_ids.end_year', 'education_ids.sequence')
    def _compute_highest_qualification(self):
        for rec in self:
            edu = rec.education_ids.sorted(lambda e: (e.end_year or 9999, e.sequence), reverse=True)[:1]
            rec.highest_qualification = edu.degree if edu else False

    @api.depends('achievement_ids', 'mentorship_ids.state', 'donation_ids.state', 'donation_ids.amount',
                 'guidance_ids', 'event_attendee_ids')
    def _compute_counts(self):
        for rec in self:
            rec.achievement_count = len(rec.achievement_ids)
            rec.mentorship_count = len(rec.mentorship_ids)
            rec.active_mentee_count = len(rec.mentorship_ids.filtered(lambda m: m.state == 'active'))
            received = rec.donation_ids.filtered(lambda d: d.state == 'received')
            rec.donation_count = len(rec.donation_ids)
            rec.donation_total = sum(d.currency_id._convert(d.amount, rec.currency_id, rec.company_id,
                                                         d.date or fields.Date.context_today(rec))
                                     if d.currency_id and rec.currency_id and d.currency_id != rec.currency_id
                                     else d.amount for d in received)
            rec.guidance_count = len(rec.guidance_ids)
            rec.event_count = len(rec.event_attendee_ids)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code') or vals['code'] == '/':
                vals['code'] = self.env['ir.sequence'].next_by_code('school.alumni') or '/'
        return super().create(vals_list)

    @api.constrains('graduation_year')
    def _check_graduation_year(self):
        this_year = fields.Date.context_today(self).year
        for rec in self:
            if rec.graduation_year and not (1900 <= rec.graduation_year <= this_year + 1):
                raise ValidationError(_("Graduation year %s is not valid.", rec.graduation_year))

    @api.constrains('max_mentees')
    def _check_max_mentees(self):
        if any(rec.max_mentees < 0 for rec in self):
            raise ValidationError(_("Maximum active mentees cannot be negative (0 = no limit)."))

    # ------------------------------------------------------------------
    # life cycle: Graduate -> Alumni -> Mentor
    # ------------------------------------------------------------------
    def action_register_alumni(self):
        """Graduate -> Alumni: the profile is confirmed (needs a way to reach them)."""
        for rec in self:
            if rec.stage != 'graduate':
                raise UserError(_("Only a Graduate can be registered as Alumni."))
            if not (rec.email or rec.phone):
                raise UserError(_("Add an e-mail or phone number for %s before registering as alumni.",
                                  rec.name))
        self.write({'stage': 'alumni'})

    def action_make_mentor(self):
        """Alumni -> Mentor: needs at least one expertise area."""
        for rec in self:
            if rec.stage != 'alumni':
                raise UserError(_("Only a registered Alumni can become a Mentor."))
            if not rec.expertise_ids:
                raise UserError(_("Add at least one Expertise Area for %s before making them a mentor "
                                  "(Mentorship tab).", rec.name))
        self.write({'stage': 'mentor', 'mentor_available': True})

    def action_stop_mentoring(self):
        """Mentor -> Alumni (allowed only without active mentorships)."""
        for rec in self:
            if rec.active_mentee_count:
                raise UserError(_("%s still has active mentorships. Complete or cancel them first.",
                                  rec.name))
        self.write({'stage': 'alumni'})

    def action_back_to_graduate(self):
        self.filtered(lambda r: r.stage == 'alumni').write({'stage': 'graduate'})

    # ------------------------------------------------------------------
    # smart buttons
    # ------------------------------------------------------------------
    def _open(self, model, name, domain, context=None, views='list,form'):
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'view_mode': views,
            'domain': domain,
            'context': context or {},
        }

    def action_view_student(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'school.student',
            'res_id': self.student_id.id,
            'view_mode': 'form',
        }

    def action_view_mentorships(self):
        self.ensure_one()
        return self._open('school.alumni.mentorship', _('Mentorships'), [('mentor_id', '=', self.id)],
                          {'default_mentor_id': self.id})

    def action_view_donations(self):
        self.ensure_one()
        return self._open('school.alumni.donation', _('Donations'), [('alumni_id', '=', self.id)],
                          {'default_alumni_id': self.id})

    def action_view_guidance(self):
        self.ensure_one()
        return self._open('school.alumni.guidance', _('Career Guidance'), [('alumni_ids', 'in', self.id)],
                          {'default_alumni_ids': [self.id]})

    def action_view_events(self):
        self.ensure_one()
        return self._open('school.alumni.event', _('Alumni Events'),
                          [('attendee_ids.alumni_id', '=', self.id)])


class SchoolAlumniEducation(models.Model):
    """Higher education of an alumni (after leaving school)."""
    _name = 'school.alumni.education'
    _description = 'Alumni Higher Education'
    _order = 'sequence, start_year desc, id'

    alumni_id = fields.Many2one('school.alumni', string='Alumni', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    level = fields.Selection([
        ('diploma', 'Diploma'),
        ('ug', 'Undergraduate'),
        ('pg', 'Postgraduate'),
        ('doctorate', 'Doctorate'),
        ('certification', 'Certification'),
        ('other', 'Other'),
    ], string='Level', required=True, default='ug')
    degree = fields.Char(string='Degree / Course', required=True, help='e.g. B.E. Computer Science')
    institution = fields.Char(string='Institution', required=True)
    field_of_study = fields.Char(string='Field of Study')
    start_year = fields.Integer(string='From')
    end_year = fields.Integer(string='To', help='Leave empty while studying.')
    status = fields.Selection([('pursuing', 'Pursuing'), ('completed', 'Completed'), ('discontinued', 'Discontinued')],
                              string='Status', default='completed', required=True)
    score = fields.Char(string='Grade / Score')

    @api.constrains('start_year', 'end_year')
    def _check_years(self):
        for rec in self:
            if rec.start_year and rec.end_year and rec.end_year < rec.start_year:
                raise ValidationError(_("'To' year cannot be before 'From' year (%s).", rec.degree))


class SchoolAlumniCareer(models.Model):
    """Profession / employment history of an alumni."""
    _name = 'school.alumni.career'
    _description = 'Alumni Career History'
    _order = 'is_current desc, date_start desc, id desc'

    alumni_id = fields.Many2one('school.alumni', string='Alumni', required=True, ondelete='cascade', index=True)
    designation = fields.Char(string='Designation', required=True)
    organization = fields.Char(string='Organization', required=True)
    industry_id = fields.Many2one('school.alumni.industry', string='Industry')
    location = fields.Char(string='Location')
    date_start = fields.Date(string='From')
    date_end = fields.Date(string='To')
    is_current = fields.Boolean(string='Current Job')

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError(_("'To' date cannot be before 'From' date (%s).", rec.organization))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_current_job()
        return records

    def write(self, vals):
        res = super().write(vals)
        if {'is_current', 'designation', 'organization', 'industry_id'} & set(vals):
            self._sync_current_job()
        return res

    def _sync_current_job(self):
        """The current job also fills Profession / Organization / Industry on the alumni."""
        for rec in self.filtered('is_current'):
            rec.alumni_id.write({
                'profession': rec.designation,
                'organization': rec.organization,
                'industry_id': rec.industry_id.id or rec.alumni_id.industry_id.id,
                'employment_status': rec.alumni_id.employment_status or 'employed',
            })


class SchoolAlumniAchievement(models.Model):
    """Achievements of an alumni (awards, publications, recognitions...)."""
    _name = 'school.alumni.achievement'
    _description = 'Alumni Achievement'
    _order = 'date desc, id desc'

    alumni_id = fields.Many2one('school.alumni', string='Alumni', required=True, ondelete='cascade', index=True)
    name = fields.Char(string='Achievement', required=True)
    category = fields.Selection([
        ('academic', 'Academic'),
        ('professional', 'Professional'),
        ('sports', 'Sports'),
        ('arts', 'Arts & Culture'),
        ('social', 'Social Service'),
        ('research', 'Research / Publication'),
        ('entrepreneurship', 'Entrepreneurship'),
        ('other', 'Other'),
    ], string='Category', required=True, default='professional')
    level = fields.Selection([
        ('local', 'Local'), ('state', 'State'), ('national', 'National'), ('international', 'International'),
    ], string='Level')
    date = fields.Date(string='Date')
    description = fields.Text(string='Description')
    featured = fields.Boolean(string='Featured', help='Show as a highlight of the alumni network.')