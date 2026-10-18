# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .wellbeing_base import counsellor_users

_logger = logging.getLogger(__name__)

LEVELS = [('low', 'Low'), ('medium', 'Medium'), ('high', 'High')]
STATES = [('new', 'New'), ('assessment', 'Assessment'), ('support', 'Support'), ('monitoring', 'Monitoring'), ('closed', 'Closed')]
SOURCES = [('self', 'Student asked'), ('teacher', 'Teacher'), ('parent', 'Parent'), ('counsellor', 'Counsellor'),
           ('checkin', 'Check-in alert')]
OUTCOMES = [('improved', 'Improved'), ('ongoing', 'Ongoing support elsewhere'), ('referred', 'Referred out'),
            ('no_concern', 'No concern found'), ('withdrawn', 'Student / parent withdrew')]
CLOSED_LOCKED = {'concern_text', 'assessment_notes', 'plan', 'outcome', 'closure_notes', 'level', 'area_ids',
                 'counsellor_id', 'student_id', 'is_restricted'}


class WellbeingCase(models.Model):
    _name = 'school.wellbeing.case'
    _description = 'Well-being case (confidential)'
    _inherit = ['school.wellbeing.confidential', 'mail.thread', 'mail.activity.mixin']
    _order = 'opened_datetime desc, id desc'
    _rec_names_search = ['name', 'student_id']

    name = fields.Char(string='Reference', readonly=True, copy=False, default=lambda self: _('New'), index=True)
    company_id = fields.Many2one('res.company', string='School / Board', required=True, default=lambda self: self.env.company)
    student_id = fields.Many2one('school.student', string='Student', required=True, index=True, ondelete='restrict')
    class_id = fields.Many2one('school.class', related='student_id.class_id', store=True, string='Class')
    state = fields.Selection(STATES, string='Status', default='new', required=True, index=True, tracking=True, copy=False)
    level = fields.Selection(LEVELS, string='Priority', default='medium', required=True, tracking=True)
    source = fields.Selection(SOURCES, string='Raised By', default='counsellor', required=True)
    reporter_partner_id = fields.Many2one('res.partner', string='Raised By (person)', readonly=True, copy=False)
    reporter_label = fields.Char(compute='_compute_reporter_label', string='Raised By (name)')
    area_ids = fields.Many2many('school.wellbeing.area', 'wb_case_area_rel', 'case_id', 'area_id', string='Areas')
    wants_to_talk = fields.Boolean(string='Student wants to talk', tracking=True)
    is_restricted = fields.Boolean(
        string='Restricted case', tracking=True,
        help="Only the case counsellor and the Well-being Lead can open a restricted case.")
    counsellor_id = fields.Many2one(
        'res.users', string='Case Counsellor', tracking=True,
        domain=lambda self: [('all_group_ids', 'in', self.env.ref('school_safeguarding.group_wb_counsellor').ids)])
    opened_datetime = fields.Datetime(string='Opened On', default=fields.Datetime.now, readonly=True, copy=False)
    concern_text = fields.Text(string='What was noticed / shared')
    assessment_notes = fields.Text(string='Assessment')
    plan = fields.Text(string='Support plan')
    outcome = fields.Selection(OUTCOMES, string='Outcome', tracking=True)
    closure_notes = fields.Text(string='Closure notes')
    closed_datetime = fields.Datetime(string='Closed On', readonly=True, copy=False)
    closed_by = fields.Many2one('res.users', string='Closed By', readonly=True, copy=False)
    retention_until = fields.Date(compute='_compute_retention', store=True, string='Keep Until')
    reminder_sent = fields.Boolean(copy=False)
    safeguarding_ref = fields.Char(string='Shared with Safeguarding', readonly=True, copy=False)

    session_ids = fields.One2many('school.wellbeing.session', 'case_id', string='Sessions')
    intervention_ids = fields.One2many('school.wellbeing.intervention', 'case_id', string='Interventions')
    referral_ids = fields.One2many('school.wellbeing.referral', 'case_id', string='Referrals')
    log_ids = fields.One2many('school.wellbeing.log', 'case_id', string='Case Log')
    access_log_ids = fields.One2many('school.wellbeing.access.log', 'case_id', string='Who Opened This Case',
                                     groups='school_safeguarding.group_wb_lead')
    session_count = fields.Integer(compute='_compute_counts', string='Sessions')
    open_intervention_count = fields.Integer(compute='_compute_counts', string='Open Interventions')
    overdue_intervention_count = fields.Integer(compute='_compute_counts', string='Overdue Interventions')
    checkin_count = fields.Integer(compute='_compute_checkin_count', string='Check-ins')
    assessment_count = fields.Integer(compute='_compute_assessment_count', string='Screenings')

    # ------------------------------------------------------------------ computes
    @api.depends('source', 'reporter_partner_id')
    def _compute_reporter_label(self):
        labels = dict(self._fields['source'].selection)
        for case in self:
            case.reporter_label = case.reporter_partner_id.display_name or labels.get(case.source, '')

    @api.depends('closed_datetime', 'company_id')
    def _compute_retention(self):
        for case in self:
            years = self.env['school.wellbeing.config']._get(case.company_id).retention_years or 7
            case.retention_until = case.closed_datetime.date() + relativedelta(years=years) if case.closed_datetime else False

    @api.depends('session_ids', 'intervention_ids.state', 'intervention_ids.due_date')
    def _compute_counts(self):
        today = fields.Date.context_today(self)
        for case in self:
            open_items = case.intervention_ids.filtered(lambda i: i.state == 'todo')
            case.session_count = len(case.session_ids)
            case.open_intervention_count = len(open_items)
            case.overdue_intervention_count = len(open_items.filtered(lambda i: i.due_date and i.due_date < today))

    def _compute_checkin_count(self):
        Checkin = self.env['school.wellbeing.checkin']
        for case in self:
            case.checkin_count = Checkin.search_count([('student_id', '=', case.student_id.id)]) if case.id else 0

    def _compute_assessment_count(self):
        Assessment = self.env['school.wellbeing.assessment']
        for case in self:
            case.assessment_count = Assessment.search_count([('student_id', '=', case.student_id.id)]) if case.id else 0

    @api.depends('name')
    def _compute_display_name(self):
        for case in self:                                   # the reference only: this name travels in e-mails
            case.display_name = case.name or ''

    # ------------------------------------------------------------------ create / write / read
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('New'):
                vals['name'] = self._next_reference()
        cases = super().create(vals_list)
        cases._notify_new()
        return cases

    def write(self, vals):
        if any(c.state == 'closed' for c in self) and CLOSED_LOCKED & set(vals) and not self._is_lead():
            raise AccessError(_("This case is closed. Only the Well-being Lead can change it."))
        if 'is_restricted' in vals and not self._is_lead() and any(c.counsellor_id != self.env.user for c in self):
            raise AccessError(_("Only the case counsellor or the Well-being Lead can restrict a case."))
        return super().write(vals)

    def web_read(self, specification):
        if len(self) == 1 and not self.env.su and isinstance(self.id, int):
            self.check_access('read')            # not allowed to open it: nothing is logged and the error is raised
            self._log_access()                   # logged BEFORE reading: the opener sees his own entry at once
        return super().web_read(specification)

    def _log_access(self):
        """Audit trail: who opened this confidential case (once per 10 minutes)."""
        Log = self.env['school.wellbeing.access.log'].sudo()
        since = fields.Datetime.now() - timedelta(minutes=10)
        for case in self.filtered(lambda c: isinstance(c.id, int)):
            if not Log.search_count([('case_id', '=', case.id), ('user_id', '=', self.env.uid), ('create_date', '>=', since)]):
                Log.create({'case_id': case.id, 'user_id': self.env.uid})

    @api.model
    def _next_reference(self):
        """The next WB/year/number, whatever company the student (or the portal user) belongs to."""
        seq = self.env['ir.sequence'].sudo().search([('code', '=', 'school.wellbeing.case')], limit=1)
        return seq.next_by_id() if seq else _('New')

    @api.model
    def _raise_for_student(self, student, level, text, source, talk=False, company=None, reporter=None, areas=None, alert=False):
        """One open case per student: new information (a check-in, a request to talk) goes into the student's open case;
        a case is opened only when there is none. With alert=True the counsellors are told when the case was waiting."""
        Case = self.sudo()
        case = Case.search([('student_id', '=', student.id), ('state', '!=', 'closed')], order='opened_datetime desc, id desc', limit=1)
        if case:
            vals = {}
            if level == 'high' and case.level != 'high':
                vals['level'] = 'high'
            elif level == 'medium' and case.level == 'low':
                vals['level'] = 'medium'
            already_waiting = case.wants_to_talk and case.state == 'new'
            if talk and not case.wants_to_talk:
                vals['wants_to_talk'] = True
            if vals:
                case.write(vals)
            case._log(text)                                         # the student's words always reach the counsellor...
            if alert and not already_waiting:                       # ...but the alert is not repeated while the case is waiting
                case.message_post(
                    body=Markup(_("<p>A student asked to talk to a counsellor (case <b>%s</b>).</p>")) % case.name,
                    subject=_("Well-being: a student asked to talk (%s)", case.name),
                    partner_ids=counsellor_users(self.env).mapped('partner_id').ids,
                    message_type='notification', subtype_xmlid='mail.mt_comment')
            return case
        return Case.create({
            'student_id': student.id, 'company_id': (company or student.company_id or self.env.company).id, 'source': source,
            'level': level, 'wants_to_talk': talk, 'concern_text': text, 'area_ids': [(6, 0, (areas or self.env['school.wellbeing.area']).ids)],
            'reporter_partner_id': reporter.id if reporter else False})

    # ------------------------------------------------------------------ messages: never the name, never the details
    def _notify_new(self):
        for case in self:
            urgent = case.level == 'high' or case.wants_to_talk
            case.sudo().message_post(
                body=Markup(_("<p>A new well-being case <b>%(name)s</b> was opened (%(source)s).%(urgent)s</p>"
                              "<p>Open it in Well-being &gt; Cases. Names and details are never sent by message.</p>")) % {
                    'name': case.name, 'source': dict(case._fields['source'].selection)[case.source],
                    'urgent': _(" Priority: please look at it today.") if urgent else ''},
                subject=_("Well-being: new case %s", case.name),
                partner_ids=counsellor_users(self.env).mapped('partner_id').ids,
                message_type='notification', subtype_xmlid='mail.mt_comment')

    def _log(self, text):
        for case in self:
            self.env['school.wellbeing.log'].sudo().create({'case_id': case.id, 'text': text, 'author_id': self.env.uid})

    # ------------------------------------------------------------------ workflow
    def action_start_assessment(self):
        for case in self:
            if case.state != 'new':
                raise UserError(_("Only a new case can be taken for assessment."))
            case.write({'state': 'assessment', 'counsellor_id': case.counsellor_id.id or self.env.uid})
            case._log(_("Assessment started"))

    def action_start_support(self):
        for case in self:
            if case.state != 'assessment':
                raise UserError(_("Support starts after the assessment."))
            if not (case.assessment_notes or '').strip():
                raise UserError(_("Write the assessment before starting the support."))
            case.write({'state': 'support'})
            case._log(_("Support started"))

    def action_monitor(self):
        for case in self:
            if case.state != 'support':
                raise UserError(_("Only a case in support can move to monitoring."))
            case.write({'state': 'monitoring'})
            case._log(_("Moved to monitoring"))

    def action_close(self):
        for case in self:
            if case.state not in ('assessment', 'support', 'monitoring'):
                raise UserError(_("Assess the case before closing it."))
            if not case.outcome:
                raise UserError(_("Choose the outcome before closing the case."))
            if not (case.closure_notes or '').strip():
                raise UserError(_("Write the closure notes before closing the case."))
            if case.open_intervention_count:
                raise UserError(_("%s intervention(s) are still open. Complete or cancel them first.", case.open_intervention_count))
            case.write({'state': 'closed', 'closed_datetime': fields.Datetime.now(), 'closed_by': self.env.uid})
            case._log(_("Case closed"))

    def action_reopen(self):
        if not self._is_lead():
            raise AccessError(_("Only the Well-being Lead can reopen a closed case."))
        for case in self.filtered(lambda c: c.state == 'closed'):
            case.sudo().write({'state': 'monitoring', 'closed_datetime': False, 'closed_by': False})
            case._log(_("Case reopened by the Well-being Lead"))

    def action_share_with_safeguarding(self):
        """Open the form where the counsellor writes what the Safeguarding team needs to know (the notes are not copied)."""
        self.ensure_one()
        if self.safeguarding_ref:
            raise UserError(_("This case was already shared with Safeguarding (%s).", self.safeguarding_ref))
        bullying = self.env.ref('school_safeguarding.area_bullying', raise_if_not_found=False)
        return {'type': 'ir.actions.act_window', 'name': _('Share with Safeguarding'), 'res_model': 'school.wellbeing.share.wizard',
                'view_mode': 'form', 'target': 'new',
                'context': {'default_case_id': self.id, 'default_category': 'bullying' if bullying and bullying in self.area_ids else 'child_safety'}}

    def action_view_checkins(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Check-ins'), 'res_model': 'school.wellbeing.checkin',
                'view_mode': 'list,form', 'domain': [('student_id', '=', self.student_id.id)]}

    def action_view_assessments(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Screenings'), 'res_model': 'school.wellbeing.assessment',
                'view_mode': 'list,form,graph', 'domain': [('student_id', '=', self.student_id.id)],
                'context': {'default_student_id': self.student_id.id, 'default_case_id': self.id}}

    # ------------------------------------------------------------------ reminders (cron)
    @api.model
    def _cron_reminders(self):
        today = fields.Date.context_today(self)
        for item in self.env['school.wellbeing.intervention'].sudo().search([
                ('state', '=', 'todo'), ('due_date', '<', today), '|', ('reminded_date', '=', False), ('reminded_date', '<', today)]):
            item.case_id.message_post(
                body=Markup(_("<p>An intervention of case <b>%s</b> is overdue.</p>")) % item.case_id.name,
                subject=_("Overdue well-being intervention: %s", item.case_id.name),
                partner_ids=item.responsible_id.partner_id.ids, message_type='notification', subtype_xmlid='mail.mt_comment')
            item.reminded_date = today
        cutoff = fields.Datetime.now() - timedelta(hours=24)
        for case in self.sudo().search([('state', '=', 'new'), ('reminder_sent', '=', False), ('opened_datetime', '<', cutoff)]):
            case.message_post(
                body=Markup(_("<p>Case <b>%s</b> has been waiting for assessment for more than 24 hours.</p>")) % case.name,
                subject=_("Well-being: case %s is waiting", case.name),
                partner_ids=counsellor_users(self.env).mapped('partner_id').ids, message_type='notification',
                subtype_xmlid='mail.mt_comment')
            case.reminder_sent = True


class WellbeingLog(models.Model):
    _name = 'school.wellbeing.log'
    _description = 'Well-being case log'
    _inherit = ['school.wellbeing.confidential']
    _order = 'log_datetime desc, id desc'

    case_id = fields.Many2one('school.wellbeing.case', required=True, ondelete='cascade', index=True)
    log_datetime = fields.Datetime(string='When', default=fields.Datetime.now, required=True)
    author_id = fields.Many2one('res.users', string='By', default=lambda self: self.env.uid, readonly=True)
    text = fields.Text(string='Entry', required=True)


class WellbeingCaseChild(models.AbstractModel):
    """Items of a case cannot be added to a closed case, except by the Well-being Lead."""
    _name = 'school.wellbeing.case.child'
    _description = 'Item of a well-being case'
    _inherit = ['school.wellbeing.confidential']

    @api.model_create_multi
    def create(self, vals_list):
        cases = self.env['school.wellbeing.case'].browse([v['case_id'] for v in vals_list if v.get('case_id')])
        if any(c.state == 'closed' for c in cases) and not cases._is_lead():
            raise AccessError(_("This case is closed. Only the Well-being Lead can add to it."))
        return super().create(vals_list)


class WellbeingSession(models.Model):
    """A counselling session. The notes are private to the counsellors."""
    _name = 'school.wellbeing.session'
    _description = 'Counselling session'
    _inherit = ['school.wellbeing.case.child']
    _order = 'session_date desc, id desc'

    case_id = fields.Many2one('school.wellbeing.case', required=True, ondelete='cascade', index=True, string='Case')
    student_id = fields.Many2one(related='case_id.student_id', store=True, string='Student')
    counsellor_id = fields.Many2one('res.users', string='Counsellor', required=True, default=lambda self: self.env.uid)
    session_date = fields.Datetime(string='When', required=True, default=fields.Datetime.now)
    duration_minutes = fields.Integer(string='Minutes', default=30)
    session_type = fields.Selection([('individual', 'Individual'), ('group', 'Group'), ('parent', 'With parent'),
                                     ('teacher', 'With teacher'), ('crisis', 'Crisis')], string='Type', default='individual', required=True)
    mode = fields.Selection([('in_person', 'In person'), ('phone', 'Phone'), ('online', 'Online')], string='Mode', default='in_person')
    state = fields.Selection([('scheduled', 'Scheduled'), ('done', 'Done'), ('no_show', 'Did not come'), ('cancelled', 'Cancelled')],
                             string='Status', default='scheduled', required=True, index=True)
    mood_start = fields.Selection([('good', 'Good'), ('okay', 'Okay'), ('struggling', 'Struggling'), ('need_help', 'Need help')],
                                  string='Mood at the start')
    mood_end = fields.Selection([('good', 'Good'), ('okay', 'Okay'), ('struggling', 'Struggling'), ('need_help', 'Need help')],
                                string='Mood at the end')
    risk_level = fields.Selection([('none', 'No risk seen'), ('low', 'Low'), ('medium', 'Medium'), ('high', 'High')],
                                  string='Risk seen', default='none')
    notes = fields.Text(string='Session notes (private)')
    next_steps = fields.Text(string='Next steps')
    next_session_date = fields.Date(string='Next session')

    @api.constrains('duration_minutes')
    def _check_duration(self):
        for session in self:
            if not 0 < session.duration_minutes <= 480:
                raise ValidationError(_("The duration must be between 1 and 480 minutes."))

    duration_hours = fields.Float(string='Hours', compute='_compute_duration_hours', inverse='_inverse_duration_hours',
                                  help="Technical: the calendar view counts the length of an event in hours.")

    @api.depends('duration_minutes')
    def _compute_duration_hours(self):
        for session in self:
            session.duration_hours = (session.duration_minutes or 0) / 60.0

    def _inverse_duration_hours(self):
        for session in self:
            session.duration_minutes = int(round((session.duration_hours or 0) * 60))

    @api.depends('student_id.name', 'session_date')
    @api.depends_context('tz')
    def _compute_display_name(self):
        for session in self:
            when = session.session_date and fields.Datetime.context_timestamp(session, session.session_date)
            session.display_name = '%s - %s' % (session.student_id.name or '', when.strftime('%d %b %Y %H:%M') if when else '')

    def action_done(self):
        for session in self.filtered(lambda s: s.state == 'scheduled'):
            session.write({'state': 'done'})
            session.case_id._log(_("Session held (%s min)", session.duration_minutes))
            if session.risk_level == 'high':                 # the Lead is told, with the reference only
                session.case_id.message_post(
                    body=Markup(_("<p>A counselling session of case <b>%s</b> recorded a <b>high risk</b>. Please review the case today.</p>")) % session.case_id.name,
                    subject=_("Well-being: high risk recorded on %s", session.case_id.name),
                    partner_ids=counsellor_users(self.env, lead_only=True).mapped('partner_id').ids,
                    message_type='notification', subtype_xmlid='mail.mt_comment')

    def action_no_show(self):
        self.filtered(lambda s: s.state == 'scheduled').write({'state': 'no_show'})

    def action_cancel(self):
        self.filtered(lambda s: s.state == 'scheduled').write({'state': 'cancelled'})


class WellbeingIntervention(models.Model):
    """Follow-up of the support plan."""
    _name = 'school.wellbeing.intervention'
    _description = 'Well-being intervention'
    _inherit = ['school.wellbeing.case.child']
    _order = 'due_date, id'

    case_id = fields.Many2one('school.wellbeing.case', required=True, ondelete='cascade', index=True, string='Case')
    student_id = fields.Many2one(related='case_id.student_id', store=True, string='Student')
    kind = fields.Selection([
        ('counselling_plan', 'Counselling plan'), ('parent_meeting', 'Meeting with parents'),
        ('teacher_accommodation', 'Teacher accommodation'), ('peer_support', 'Peer support'),
        ('study_support', 'Study / exam support'), ('monitoring', 'Monitoring / check-in'), ('other', 'Other')],
        string='Type', required=True, default='monitoring')
    description = fields.Char(string='What must be done', required=True)
    responsible_id = fields.Many2one('res.users', string='Responsible', required=True, default=lambda self: self.env.uid)
    due_date = fields.Date(string='Due Date', required=True, default=lambda self: fields.Date.context_today(self) + timedelta(days=7))
    review_date = fields.Date(string='Review On')
    state = fields.Selection([('todo', 'To do'), ('done', 'Done'), ('cancelled', 'Cancelled')], string='Status',
                             default='todo', required=True, index=True)
    done_date = fields.Date(string='Done On', readonly=True)
    outcome = fields.Text(string='Result')
    activity_id = fields.Many2one('mail.activity', ondelete='set null', copy=False)
    reminded_date = fields.Date(copy=False)
    overdue = fields.Boolean(compute='_compute_overdue')

    @api.depends('state', 'due_date')
    def _compute_overdue(self):
        today = fields.Date.context_today(self)
        for item in self:
            item.overdue = item.state == 'todo' and bool(item.due_date) and item.due_date < today

    @api.model_create_multi
    def create(self, vals_list):
        items = super().create(vals_list)
        for item in items:
            item.activity_id = item.case_id.sudo().activity_schedule(
                'mail.mail_activity_data_todo', date_deadline=item.due_date,
                summary=_("Well-being intervention due"), user_id=item.responsible_id.id)         # no details in the e-mail
        return items

    def action_done(self):
        for item in self.filtered(lambda i: i.state == 'todo'):
            item.write({'state': 'done', 'done_date': fields.Date.context_today(item)})
            if item.activity_id.exists():
                item.activity_id.sudo().action_feedback(feedback=_("Done"))
            item.case_id._log(_("Intervention done: %s", item.description))

    def action_cancel(self):
        for item in self.filtered(lambda i: i.state == 'todo'):
            item.write({'state': 'cancelled'})
            if item.activity_id.exists():
                item.activity_id.sudo().unlink()
            item.case_id._log(_("Intervention cancelled: %s", item.description))


class WellbeingReferral(models.Model):
    """A referral to somebody else (school doctor, special educator, psychologist, agency...)."""
    _name = 'school.wellbeing.referral'
    _description = 'Well-being referral'
    _inherit = ['school.wellbeing.case.child']
    _order = 'referral_date desc, id desc'

    case_id = fields.Many2one('school.wellbeing.case', required=True, ondelete='cascade', index=True, string='Case')
    student_id = fields.Many2one(related='case_id.student_id', store=True, string='Student')
    kind = fields.Selection([
        ('doctor', 'School doctor / nurse'), ('special_educator', 'Special educator'), ('psychologist', 'Psychologist (external)'),
        ('psychiatrist', 'Psychiatrist / doctor (external)'), ('agency', 'Child welfare / other agency'), ('other', 'Other')],
        string='Referred To (type)', required=True, default='psychologist')
    is_external = fields.Boolean(compute='_compute_external', store=True, string='External')
    referred_to = fields.Char(string='Name of person / organisation', required=True)
    reason = fields.Text(string='Why', required=True)
    urgency = fields.Selection([('routine', 'Routine'), ('soon', 'Soon'), ('urgent', 'Urgent')], default='routine', required=True)
    referral_date = fields.Date(string='Date', default=fields.Date.context_today, required=True)
    consent_given = fields.Boolean(string='Parent / guardian consent')
    consent_by = fields.Char(string='Consent given by')
    consent_date = fields.Date(string='Consent date')
    consent_waived_reason = fields.Text(string='Why no consent (e.g. child safety)',
                                        help="Only when the referral must go ahead without consent.")
    state = fields.Selection([('planned', 'Planned'), ('sent', 'Sent'), ('accepted', 'Accepted'), ('in_progress', 'In progress'),
                              ('completed', 'Completed'), ('declined', 'Declined')], string='Status', default='planned',
                             required=True, index=True)
    outcome = fields.Text(string='Outcome / feedback')
    follow_up_date = fields.Date(string='Follow up on')
    attachment_ids = fields.Many2many('ir.attachment', 'wb_referral_attachment_rel', 'referral_id', 'attachment_id', string='Documents')

    @api.depends('kind')
    def _compute_external(self):
        for referral in self:
            referral.is_external = referral.kind in ('psychologist', 'psychiatrist', 'agency', 'other')

    def action_send(self):
        for referral in self:
            if referral.state != 'planned':
                raise UserError(_("Only a planned referral can be sent."))
            if referral.is_external and not referral.consent_given:
                if not (referral.consent_waived_reason or '').strip():
                    raise UserError(_("An external referral needs the parent / guardian consent. If it must go ahead "
                                      "without it, write why in 'Why no consent'."))
            referral.write({'state': 'sent'})
            referral.case_id._log(_("Referral sent to %s", referral.referred_to))

    def action_set_state(self, state):
        for referral in self:
            referral.write({'state': state})
            referral.case_id._log(_("Referral to %(who)s: %(state)s", who=referral.referred_to,
                                    state=dict(referral._fields['state'].selection)[state]))

    def action_accept(self):
        self.action_set_state('accepted')

    def action_in_progress(self):
        self.action_set_state('in_progress')

    def action_complete(self):
        self.action_set_state('completed')

    def action_decline(self):
        self.action_set_state('declined')


class WellbeingAccessLog(models.Model):
    _name = 'school.wellbeing.access.log'
    _description = 'Well-being access log'
    _order = 'create_date desc, id desc'

    case_id = fields.Many2one('school.wellbeing.case', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', string='Opened By', required=True)
    viewed_datetime = fields.Datetime(string='Opened On', default=fields.Datetime.now, readonly=True)
