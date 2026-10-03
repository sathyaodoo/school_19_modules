from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

ADMISSION_STATES = [
    ('enquiry', 'New Enquiry'),
    ('submitted', 'Application Submitted'),
    ('documents', 'Documents Under Review'),
    ('verification', 'Background Verification'),
    ('approval', 'Approval Pending'),
    ('admitted', 'Admitted'),
    ('rejected', 'Rejected'),
]


class SchoolAdmissionStage(models.Model):
    _name = 'school.admission.stage'
    _description = 'Admission Pipeline Stage'
    _order = 'sequence, id'

    name = fields.Char(string='Stage Name', required=True, translate=True)
    sequence = fields.Integer(default=10)
    code = fields.Selection(ADMISSION_STATES, string='Workflow Step', required=True,
                            help="Internal step this stage stands for. Admitted creates the student.")
    fold = fields.Boolean(string='Folded in Pipeline')

    _code_uniq = models.Constraint('unique(code)', 'Only one stage per workflow step is allowed.')


class SchoolAdmission(models.Model):
    _name = 'school.admission'
    _description = 'Admission Application'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Application Number', required=True, readonly=True, default='/', copy=False)
    
    # --- Referral tracking (BRS 4.1) ---
    admission_source = fields.Selection([
        ('walk_in', 'Direct Walk-in'),
        ('referral', 'Referral'),
        ('anganwadi', 'Anganwadi Visit'),
        ('website', 'Website'),
        ('social_media', 'Social Media (Instagram / Facebook)'),
        ('other', 'Other'),
    ], string='Admission Source', default='walk_in', required=True, tracking=True)
    referral_type = fields.Selection([
        ('parent', 'Parent of Current Student'),
        ('staff', 'School Staff'),
        ('alumni', 'Alumni'),
        ('other', 'Other'),
    ], string='Referred By (Type)', tracking=True)
    referral_name = fields.Char(string='Referrer Name', tracking=True)
    referral_phone = fields.Char(string='Referrer Phone')
    referral_student_id = fields.Many2one('school.student', string='Referring Student',
                                          help="Existing student whose parent referred this admission.")
    anganwadi_name = fields.Char(string='Anganwadi Name / Place', tracking=True)
    anganwadi_visit_date = fields.Date(string='Anganwadi Visit Date', tracking=True)
    anganwadi_staff_ids = fields.Many2many('res.users', 'school_admission_anganwadi_staff_rel',
                                           'admission_id', 'user_id', string='Staff Assigned')
    source_note = fields.Char(string='Source Details', help="Campaign, website page, other source details.")

    first_name = fields.Char(string='First Name', required=True, tracking=True)
    last_name = fields.Char(string='Last Name', required=True, tracking=True)
    date_of_birth = fields.Date(string='Date of Birth', required=True, tracking=True)
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other')
    ], string='Gender', required=True, default='male', tracking=True)
    age = fields.Integer(string='Age', compute='_compute_age', store=True)
    admission_date = fields.Date(string='Admission Date', default=fields.Date.context_today, tracking=True)
    blood_group = fields.Selection([
        ('A+', 'A+'), ('A-', 'A-'),
        ('B+', 'B+'), ('B-', 'B-'),
        ('O+', 'O+'), ('O-', 'O-'),
        ('AB+', 'AB+'), ('AB-', 'AB-')
    ], string='Blood Group', tracking=True)
    nationality_id = fields.Many2one('res.country', string='Nationality')
    religion = fields.Char(string='Religion')
    caste = fields.Char(string='Caste')
    mother_tongue = fields.Selection([
        ('english', 'English'),
        ('malayalam', 'Malayalam'),
        ('tamil', 'Tamil'),
        ('hindi', 'Hindi'),
        ('other', 'Other'),
    ], string='Mother Tongue')
    previous_school_name = fields.Char(string='Previous School Name')
    reason_for_transfer = fields.Text(string='Reason for Transfer')

    sponsor_name = fields.Char(string='Sponsor Name')
    sponsor_type = fields.Selection([
        ('ngo', 'NGO'),
        ('individual', 'Individual'),
        ('corporate', 'Corporate'),
        ('other', 'Other'),
    ], string='Sponsor Type')
    sponsor_contact = fields.Char(string='Sponsor Contact')
    sponsorship_status = fields.Selection([
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ], string='Sponsorship Status')
    relationship_to_student = fields.Char(string='Relationship to Student')

    scholarship_amount = fields.Float(string='Scholarship Amount')
    scholarship_type = fields.Selection([
        ('merit', 'Merit'),
        ('need_based', 'Need-based'),
        ('sports', 'Sports'),
        ('other', 'Other'),
    ], string='Scholarship Type')
    scholarship_approved_date = fields.Date(string='Scholarship Approved Date')
    scholarship_expiry_date = fields.Date(string='Scholarship Expiry Date')
    merit_tag = fields.Selection([
        ('excellent', 'Excellent'),
        ('very_good', 'Very Good'),
        ('good', 'Good'),
    ], string='Merit Tag')

    email = fields.Char(string='Email', tracking=True)
    phone = fields.Char(string='Phone', tracking=True)
    
    street = fields.Char(string='Street')
    city = fields.Char(string='City')
    state_id = fields.Many2one('res.country.state', string='State')
    country_id = fields.Many2one('res.country', string='Country')
    zip = fields.Char(string='Zip')

    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', required=True, tracking=True)
    class_id = fields.Many2one('school.class', string='Class', required=True, tracking=True)
    section_id = fields.Many2one('school.section', string='Section', tracking=True)
    
    parent_name = fields.Char(string='Parent Name', tracking=True)
    parent_phone = fields.Char(string='Parent Phone', tracking=True)
    parent_email = fields.Char(string='Parent Email', tracking=True)
    parent_relation = fields.Selection([
        ('father', 'Father'),
        ('mother', 'Mother'),
        ('guardian', 'Guardian')
    ], string='Parent Relation', default='father', tracking=True)

    state = fields.Selection(ADMISSION_STATES, string='Status', default='enquiry', required=True,
                             tracking=True, index=True)
    stage_id = fields.Many2one('school.admission.stage', string='Stage', tracking=True, index=True,
                               copy=False, group_expand='_read_group_stage_ids',
                               default=lambda self: self._stage_for('enquiry'))
    kanban_state_color = fields.Integer(compute='_compute_kanban_color')

    student_id = fields.Many2one('school.student', string='Student Profile', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)

    def init(self):
        # Map the old 5-state workflow to the BRS admission pipeline (runs on module upgrade).
        self.env.cr.execute("""
            UPDATE school_admission SET state = CASE state
                WHEN 'draft' THEN 'enquiry'
                WHEN 'approved' THEN 'admitted'
                WHEN 'enrolled' THEN 'admitted'
                ELSE state END
            WHERE state IN ('draft', 'approved', 'enrolled')
        """)

    @api.constrains('admission_source', 'referral_name', 'anganwadi_visit_date')
    def _check_admission_source(self):
        for rec in self:
            if rec.admission_source == 'referral' and not rec.referral_name:
                raise ValidationError(_("Please enter the Referrer Name for a referral admission."))
            if rec.admission_source == 'anganwadi' and not rec.anganwadi_visit_date:
                raise ValidationError(_("Please enter the Anganwadi Visit Date."))

    @api.onchange('referral_student_id')
    def _onchange_referral_student(self):
        parent = self.referral_student_id.parent_ids[:1]
        if parent:
            self.referral_name = parent.name
            self.referral_phone = parent.phone

    @api.model
    def _read_group_stage_ids(self, stages, domain, *args, **kwargs):
        # show every pipeline column in kanban, even empty ones
        return stages.search([], order=stages._order)

    @api.model
    def _stage_for(self, code):
        return self.env['school.admission.stage'].search([('code', '=', code)], limit=1)

    @api.model
    def _ensure_default_stages(self):
        # create only the pipeline stages that do not exist yet (safe to run on every upgrade)
        Stage = self.env['school.admission.stage']
        existing = set(Stage.with_context(active_test=False).search([]).mapped('code'))
        for seq, (code, label) in enumerate(ADMISSION_STATES, start=1):
            if code not in existing:
                Stage.create({'name': label, 'sequence': seq, 'code': code, 'fold': code == 'rejected'})

    @api.model
    def _sync_stage_from_state(self):
        # called from data file on upgrade: give existing applications their pipeline stage
        # Status is the source of truth for old records; fix any stage that does not match it
        # (e.g. the default "New Enquiry" filled in when the stage column was added).
        for rec in self.search([]):
            if rec.stage_id.code != rec.state:
                stage = self._stage_for(rec.state)
                if stage:
                    rec.with_context(admission_admitting=True).write({'stage_id': stage.id})

    def _map_stage_state(self, vals):
        vals = dict(vals)
        if vals.get('stage_id') and 'state' not in vals:
            vals['state'] = self.env['school.admission.stage'].browse(vals['stage_id']).code
        elif vals.get('state') and 'stage_id' not in vals:
            stage = self._stage_for(vals['state'])
            if stage:
                vals['stage_id'] = stage.id
        return vals

    @api.depends('state')
    def _compute_kanban_color(self):
        colors = {'admitted': 10, 'rejected': 1, 'approval': 3}
        for rec in self:
            rec.kanban_state_color = colors.get(rec.state, 0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('school.admission.seq') or '/'
        vals_list = [self._map_stage_state(v) for v in vals_list]
        for vals in vals_list:
            if vals.get('state') == 'admitted':
                # admission must go through _admit()
                vals['state'] = 'approval'
                vals['stage_id'] = self._stage_for('approval').id
        return super(SchoolAdmission, self).create(vals_list)

    def write(self, vals):
        vals = self._map_stage_state(vals)
        if 'state' not in vals or self.env.context.get('admission_admitting'):
            return super().write(vals)
        new_state = vals['state']
        if new_state != 'admitted' and self.filtered(lambda r: r.state == 'admitted'):
            raise ValidationError(_(
                "An admitted application cannot be moved back: the student record is already created."))
        if new_state == 'admitted':
            to_admit = self.filtered(lambda r: r.state != 'admitted')
            other_vals = {k: v for k, v in vals.items() if k not in ('state', 'stage_id')}
            res = super().write(other_vals) if other_vals else True
            to_admit._admit()
            return res
        return super().write(vals)

    # --- stage buttons -------------------------------------------------
    def action_submit(self):
        self.write({'state': 'submitted'})

    def action_review_documents(self):
        self.write({'state': 'documents'})

    def action_background_verification(self):
        self.write({'state': 'verification'})

    def action_send_for_approval(self):
        self.write({'state': 'approval'})

    def action_admit(self):
        self.write({'state': 'admitted'})

    def action_reset_enquiry(self):
        self.write({'state': 'enquiry'})

    def action_approve(self):
        # kept for backward compatibility
        return self.action_admit()

    def _admit(self):
        for record in self:
            if not record.section_id:
                raise ValidationError(_("Please assign a Section before approving the admission."))
            
            student_partner_vals = {
                'name': f"{record.first_name} {record.last_name}",
                'email': record.email,
                'phone': record.phone,
                'street': record.street,
                'city': record.city,
                'state_id': record.state_id.id,
                'country_id': record.country_id.id,
                'zip': record.zip,
                'date_of_birth': record.date_of_birth,
                'gender': record.gender,
                'blood_group': record.blood_group,
                'nationality_id': record.nationality_id.id,
                'religion': record.religion,
                'caste': record.caste,
                'mother_tongue': record.mother_tongue,
                'is_student': True,
                'student_status': 'enrolled',
                'company_id': record.company_id.id,
            }
            student_partner = self.env['res.partner'].create(student_partner_vals)

            student_vals = {
                'partner_id': student_partner.id,
                'class_id': record.class_id.id,
                'section_id': record.section_id.id,
                'academic_year_id': record.academic_year_id.id,
                'sponsor_name': record.sponsor_name,
                'sponsor_type': record.sponsor_type,
                'sponsor_contact': record.sponsor_contact,
                'sponsorship_status': record.sponsorship_status,
                'relationship_to_student': record.relationship_to_student,
                'scholarship_amount': record.scholarship_amount,
                'scholarship_type': record.scholarship_type,
                'scholarship_approved_date': record.scholarship_approved_date,
                'scholarship_expiry_date': record.scholarship_expiry_date,
                'merit_tag': record.merit_tag,
            }
            student = self.env['school.student'].create(student_vals)

            if record.parent_name:
                parent_partner_vals = {
                    'name': record.parent_name,
                    'phone': record.parent_phone,
                    'email': record.parent_email,
                    'is_parent': True,
                    'company_id': record.company_id.id,
                }
                parent_partner = self.env['res.partner'].create(parent_partner_vals)
                
                parent_vals = {
                    'partner_id': parent_partner.id,
                    'relation': record.parent_relation,
                    'student_ids': [(4, student.id)],
                }
                parent = self.env['school.parent'].create(parent_vals)
                student.write({'parent_ids': [(4, parent.id)]})

            record.with_context(admission_admitting=True).write({
                'state': 'admitted',
                'student_id': student.id,
            })

    def action_enroll(self):
        # kept for backward compatibility: admission and enrolment are one step now
        return self.action_admit()

    def action_reject(self):
        self.write({'state': 'rejected'})
        
    @api.depends('date_of_birth')
    def _compute_age(self):
        today = fields.Date.today()
        for record in self:
            if record.date_of_birth:
                dob = record.date_of_birth
                record.age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            else:
                record.age = 0