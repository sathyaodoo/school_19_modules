# -*- coding: utf-8 -*-
import secrets
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

CATEGORIES = [
    ('bullying', 'Bullying'),
    ('cyberbullying', 'Cyberbullying'),
    ('harassment', 'Harassment'),
    ('child_safety', 'Child-safety concern'),
    ('other', 'Other safeguarding concern'),
]
SEVERITIES = [('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical')]
STATES = [
    ('new', 'Reported'), ('triage', 'Assessment'), ('investigation', 'Investigation'),
    ('follow_up', 'Follow-up'), ('closed', 'Closed'),
]
SOURCES = [('staff', 'Staff'), ('student', 'Student'), ('parent', 'Parent'),
           ('anonymous', 'Anonymous'), ('officer', 'Safeguarding team')]
OUTCOMES = [
    ('substantiated', 'Substantiated'), ('partially', 'Partly substantiated'),
    ('unsubstantiated', 'Not substantiated'), ('inconclusive', 'Inconclusive'),
    ('no_concern', 'Not a safeguarding matter'),
]
ESCALATION_LEVELS = [
    ('lead', 'Safeguarding Lead / Principal'),
    ('management', 'School management / governing body'),
    ('external', 'External authority (child protection agency / police)'),
]
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'          # no look-alike characters (0/O, 1/I)

# fields nobody but the Safeguarding Lead may change once the case is closed
CLOSED_LOCKED_FIELDS = {
    'category', 'severity', 'description', 'findings', 'outcome', 'closure_notes', 'triage_notes', 'investigator_id',
    'assigned_officer_id', 'affected_student_ids', 'involved_student_ids', 'involved_other', 'incident_date',
    'location', 'platform', 'is_online', 'public_update', 'attachment_ids', 'immediate_risk',
}


def new_access_code():
    return ''.join(secrets.choice(CODE_ALPHABET) for _i in range(8))


def safeguarding_users(env, lead_only=False):
    """Users of the Safeguarding Officer / Lead groups (the only authorised personnel)."""
    # all_group_ids: a Lead counts as an Officer (the Lead group implies it), a teacher never does
    group = env.ref('school_safeguarding.group_sg_lead' if lead_only else 'school_safeguarding.group_sg_officer')
    return env['res.users'].sudo().search([('all_group_ids', 'in', group.ids), ('share', '=', False)])


class SafeguardingCase(models.Model):
    _name = 'school.safeguarding.case'
    _description = 'Safeguarding case (confidential)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'reported_datetime desc, id desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default=lambda self: _('New'), index=True)
    company_id = fields.Many2one('res.company', string='School / Board', required=True,
                                 default=lambda self: self.env.company)
    state = fields.Selection(STATES, string='Status', default='new', required=True, index=True, tracking=True, copy=False)
    category = fields.Selection(CATEGORIES, string='Type of Concern', required=True, default='bullying',
                                index=True, tracking=True)
    severity = fields.Selection(SEVERITIES, string='Severity', required=True, default='medium', index=True,
                                tracking=True)
    immediate_risk = fields.Boolean(string='Someone may be in danger right now', tracking=True)
    reported_datetime = fields.Datetime(string='Reported On', default=fields.Datetime.now, readonly=True, copy=False)

    # ---- who reported (never stored for an anonymous report) ----
    source = fields.Selection(SOURCES, string='Reported By', default='officer', required=True)
    is_anonymous = fields.Boolean(string='Anonymous Report', readonly=True, copy=False)
    reporter_partner_id = fields.Many2one('res.partner', string='Reporter', readonly=True, copy=False)
    reporter_label = fields.Char(compute='_compute_reporter_label', string='Reported By (name)')
    access_code = fields.Char(string='Reporter Code', readonly=True, copy=False, default=lambda self: new_access_code(),
                              help="The reporter uses this code and the reference to look at the status of the report.")
    public_update = fields.Text(string='Message for the Reporter',
                                help="Shown to the reporter on the status page. Never write details of the case here.")
    public_status = fields.Char(compute='_compute_public_status', string='Status Shown to Reporter')

    # ---- the concern ----
    incident_date = fields.Date(string='When did it happen')
    location = fields.Char(string='Where')
    is_online = fields.Boolean(string='Online / Digital')
    platform = fields.Char(string='App / Platform')
    description = fields.Text(string='What happened', required=True)
    affected_student_ids = fields.Many2many('school.student', 'sg_case_affected_rel', 'case_id', 'student_id',
                                            string='Affected Student(s)')
    involved_student_ids = fields.Many2many('school.student', 'sg_case_involved_rel', 'case_id', 'student_id',
                                            string='Student(s) Involved')
    involved_other = fields.Char(string='Others Involved (names / roles)')
    attachment_ids = fields.Many2many('ir.attachment', 'sg_case_attachment_rel', 'case_id', 'attachment_id',
                                      string='Evidence')

    # ---- assessment / investigation / closure ----
    assigned_officer_id = fields.Many2one(
        'res.users', string='Case Officer', tracking=True,
        domain=lambda self: [('all_group_ids', 'in', self.env.ref('school_safeguarding.group_sg_officer').ids)])
    triage_notes = fields.Text(string='Assessment (risk, immediate protection, who must know)')
    triage_datetime = fields.Datetime(string='Assessed On', readonly=True, copy=False)
    triage_by = fields.Many2one('res.users', string='Assessed By', readonly=True, copy=False)
    investigator_id = fields.Many2one(
        'res.users', string='Investigator', tracking=True,
        domain=lambda self: [('all_group_ids', 'in', self.env.ref('school_safeguarding.group_sg_officer').ids)])
    investigation_start = fields.Date(string='Investigation Started')
    findings = fields.Text(string='Findings')
    outcome = fields.Selection(OUTCOMES, string='Outcome', tracking=True)
    closure_notes = fields.Text(string='Closure Notes')
    closed_datetime = fields.Datetime(string='Closed On', readonly=True, copy=False)
    closed_by = fields.Many2one('res.users', string='Closed By', readonly=True, copy=False)
    retention_until = fields.Date(compute='_compute_retention', store=True, string='Keep Until',
                                  help="Review for archiving after this date. Safeguarding records are never deleted "
                                       "automatically.")
    reminder_sent = fields.Boolean(copy=False)

    log_ids = fields.One2many('school.safeguarding.log', 'case_id', string='Case Log')
    action_ids = fields.One2many('school.safeguarding.action', 'case_id', string='Follow-up Actions')
    escalation_ids = fields.One2many('school.safeguarding.escalation', 'case_id', string='Escalations')
    access_log_ids = fields.One2many('school.safeguarding.access.log', 'case_id', string='Who Opened This Case',
                                     groups='school_safeguarding.group_sg_lead')
    action_open_count = fields.Integer(compute='_compute_counts', string='Open Actions')
    action_overdue_count = fields.Integer(compute='_compute_counts', string='Overdue Actions')
    escalated = fields.Boolean(compute='_compute_escalated', store=True, string='Escalated')
    escalation_level = fields.Selection(ESCALATION_LEVELS, compute='_compute_escalated', store=True,
                                        string='Highest Escalation')
    days_open = fields.Integer(compute='_compute_days_open', string='Days Open')

    # ------------------------------------------------------------------ computes
    @api.depends('is_anonymous', 'reporter_partner_id')
    def _compute_reporter_label(self):
        for case in self:
            case.reporter_label = _('Anonymous') if case.is_anonymous else (
                case.reporter_partner_id.display_name or _('Not recorded'))

    @api.depends('state')
    def _compute_public_status(self):
        texts = {'new': _('Received'), 'triage': _('Being reviewed'), 'investigation': _('Being looked into'),
                 'follow_up': _('Action is being taken'), 'closed': _('Closed')}
        for case in self:
            case.public_status = texts.get(case.state, '')

    @api.depends('closed_datetime')
    def _compute_retention(self):
        years = int(self.env['ir.config_parameter'].sudo().get_param('school_safeguarding.retention_years', 7) or 7)
        for case in self:
            case.retention_until = (case.closed_datetime.date() + relativedelta(years=years)
                                    if case.closed_datetime else False)

    @api.depends('action_ids.state', 'action_ids.due_date')
    def _compute_counts(self):
        today = fields.Date.context_today(self)
        for case in self:
            open_actions = case.action_ids.filtered(lambda a: a.state == 'todo')
            case.action_open_count = len(open_actions)
            case.action_overdue_count = len(open_actions.filtered(lambda a: a.due_date and a.due_date < today))

    @api.depends('escalation_ids.level')
    def _compute_escalated(self):
        order = [lvl for lvl, _label in ESCALATION_LEVELS]
        for case in self:
            levels = case.escalation_ids.mapped('level')
            case.escalated = bool(levels)
            case.escalation_level = max(levels, key=order.index) if levels else False

    @api.depends('reported_datetime', 'closed_datetime')
    def _compute_days_open(self):
        now = fields.Datetime.now()
        for case in self:
            if case.reported_datetime:
                case.days_open = ((case.closed_datetime or now) - case.reported_datetime).days
            else:
                case.days_open = 0

    @api.constrains('is_anonymous', 'reporter_partner_id')
    def _check_anonymous(self):
        for case in self:
            if case.is_anonymous and case.reporter_partner_id:
                raise ValidationError(_("An anonymous report cannot have a reporter."))

    # ------------------------------------------------------------------ create / write
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('school.safeguarding.case') or _('New')
            if vals.get('is_anonymous'):
                vals['reporter_partner_id'] = False
                vals['source'] = 'anonymous'
            if vals.get('immediate_risk') and vals.get('severity', 'medium') in ('low', 'medium'):
                vals['severity'] = 'high'                                        # danger now is never "low"
            if vals.get('category') == 'cyberbullying':
                vals.setdefault('is_online', True)
        cases = super().create(vals_list)
        cases._notify_new_case()
        return cases

    def _is_lead(self):
        return self.env.su or self.env.user.has_group('school_safeguarding.group_sg_lead')

    def write(self, vals):
        if CLOSED_LOCKED_FIELDS & set(vals) and any(c.state == 'closed' for c in self) and not self._is_lead():
            raise AccessError(_("This case is closed. Only the Safeguarding Lead can change it."))
        return super().write(vals)

    def export_data(self, fields_to_export):
        if not self._is_lead():
            raise AccessError(_("Only the Safeguarding Lead can export safeguarding records."))
        return super().export_data(fields_to_export)

    def web_read(self, specification):
        if len(self) == 1 and not self.env.su and isinstance(self.id, int):
            self.check_access('read')            # not allowed to open it: nothing is logged and the error is raised
            self._log_access()                   # logged BEFORE reading, so the opener sees his own entry at once
        return super().web_read(specification)

    def _log_access(self):
        """Audit trail: who opened this confidential case and when (once per 10 minutes).
        A new form that is not saved yet has no id and nothing to log."""
        Log = self.env['school.safeguarding.access.log'].sudo()
        since = fields.Datetime.now() - timedelta(minutes=10)
        for case in self.filtered(lambda c: isinstance(c.id, int)):
            if not Log.search_count([('case_id', '=', case.id), ('user_id', '=', self.env.uid),
                                     ('create_date', '>=', since)]):
                Log.create({'case_id': case.id, 'user_id': self.env.uid})

    # ------------------------------------------------------------------ messages (never contain the details)
    def _notify_team(self, users, subject, body):
        partners = users.mapped('partner_id').ids
        if not partners:
            return
        for case in self:
            case.sudo().message_post(body=body, subject=subject, partner_ids=partners,
                                     message_type='notification', subtype_xmlid='mail.mt_comment')

    def _category_label(self):
        self.ensure_one()
        return dict(self._fields['category'].selection)[self.category]

    def _notify_new_case(self):
        team = safeguarding_users(self.env)
        for case in self:
            urgent = case.immediate_risk or case.severity in ('high', 'critical')
            case._notify_team(
                team, _("Safeguarding: new case %s", case.name),
                Markup(_("<p>A new safeguarding case <b>%(name)s</b> was reported: %(category)s, severity <b>%(severity)s</b>."
                         "%(urgent)s</p><p>Open it in Safeguarding &gt; Cases. The details are never sent by message.</p>")) % {
                    'name': case.name, 'category': case._category_label(),
                    'severity': dict(case._fields['severity'].selection)[case.severity],
                    'urgent': _(" URGENT: someone may be in danger.") if urgent and case.immediate_risk else ''})

    def _log(self, text, log_type='system'):
        for case in self:
            self.env['school.safeguarding.log'].sudo().create({
                'case_id': case.id, 'log_type': log_type, 'text': text, 'author_id': self.env.uid})

    # ------------------------------------------------------------------ workflow
    def action_start_triage(self):
        for case in self:
            if case.state != 'new':
                raise UserError(_("Only a newly reported case can be taken for assessment."))
            case.write({'state': 'triage', 'triage_datetime': fields.Datetime.now(), 'triage_by': self.env.uid,
                        'assigned_officer_id': case.assigned_officer_id.id or self.env.uid})
            case._log(_("Assessment started"))

    def action_start_investigation(self):
        for case in self:
            if case.state != 'triage':
                raise UserError(_("A case is investigated after its assessment."))
            if not (case.triage_notes or '').strip():
                raise UserError(_("Write the assessment (risk, immediate protection) before starting the investigation."))
            case.write({'state': 'investigation', 'investigator_id': case.investigator_id.id or self.env.uid,
                        'investigation_start': case.investigation_start or fields.Date.context_today(case)})
            case._log(_("Investigation started"))

    def action_to_follow_up(self):
        for case in self:
            if case.state != 'investigation':
                raise UserError(_("Only a case under investigation can move to follow-up."))
            if not (case.findings or '').strip() or not case.outcome:
                raise UserError(_("Write the findings and choose the outcome before moving to follow-up."))
            case.write({'state': 'follow_up'})
            case._log(_("Moved to follow-up"))

    def action_close(self):
        for case in self:
            if case.state not in ('triage', 'investigation', 'follow_up'):
                raise UserError(_("Assess the case before closing it."))
            if not case.outcome:
                raise UserError(_("Choose the outcome before closing the case."))
            if not (case.closure_notes or '').strip():
                raise UserError(_("Write the closure notes before closing the case."))
            if case.action_open_count:
                raise UserError(_("%s follow-up action(s) are still open. Complete or cancel them first.",
                                  case.action_open_count))
            case.write({'state': 'closed', 'closed_datetime': fields.Datetime.now(), 'closed_by': self.env.uid})
            case._log(_("Case closed"))
            case._notify_reporter_closed()

    def action_reopen(self):
        if not self._is_lead():
            raise AccessError(_("Only the Safeguarding Lead can reopen a closed case."))
        for case in self:
            if case.state != 'closed':
                continue
            case.sudo().write({'state': 'follow_up', 'closed_datetime': False, 'closed_by': False})
            case._log(_("Case reopened by the Safeguarding Lead"))

    def action_escalate(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Escalate'), 'res_model': 'school.safeguarding.escalation',
                'view_mode': 'form', 'target': 'new', 'context': {'default_case_id': self.id}}

    def _notify_reporter_closed(self):
        """A known reporter hears that the report was looked at and closed (no details, ever)."""
        for case in self:
            if case.reporter_partner_id and not case.is_anonymous:
                self.env['mail.thread'].sudo().message_notify(
                    partner_ids=case.reporter_partner_id.ids, subject=_("Your report %s", case.name),
                    body=Markup(_("<p>Thank you for speaking up. Your report <b>%s</b> has been looked at and is now "
                                  "closed. If you are worried again, please tell the Safeguarding Officer or report "
                                  "again.</p>")) % case.name)

    # ------------------------------------------------------------------ reminders (cron)
    @api.model
    def _cron_reminders(self):
        today = fields.Date.context_today(self)
        for action in self.env['school.safeguarding.action'].sudo().search([
                ('state', '=', 'todo'), ('due_date', '<', today),
                '|', ('reminded_date', '=', False), ('reminded_date', '<', today)]):
            action.case_id.message_post(
                body=Markup(_("<p>Follow-up action on case <b>%(case)s</b> is overdue: %(what)s</p>")) % {
                    'case': action.case_id.name, 'what': action.display_name},
                subject=_("Overdue safeguarding action: %s", action.case_id.name),
                partner_ids=action.responsible_id.partner_id.ids, message_type='notification',
                subtype_xmlid='mail.mt_comment')
            action.reminded_date = today
        team = safeguarding_users(self.env)
        cutoff = fields.Datetime.now() - timedelta(hours=24)
        for case in self.sudo().search([('state', '=', 'new'), ('reminder_sent', '=', False),
                                        ('reported_datetime', '<', cutoff)]):
            case._notify_team(team, _("Safeguarding: case %s is waiting for review", case.name),
                              Markup(_("<p>Case <b>%s</b> was reported more than 24 hours ago and is still waiting for "
                                       "assessment.</p>")) % case.name)
            case.reminder_sent = True


class SafeguardingLog(models.Model):
    _name = 'school.safeguarding.log'
    _description = 'Safeguarding case log'
    _order = 'log_datetime desc, id desc'

    case_id = fields.Many2one('school.safeguarding.case', required=True, ondelete='cascade', index=True)
    log_type = fields.Selection(
        [('note', 'Note'), ('interview', 'Interview'), ('contact', 'Call / Contact'), ('meeting', 'Meeting'),
         ('evidence', 'Evidence'), ('system', 'System')], string='Type', default='note', required=True)
    log_datetime = fields.Datetime(string='When', default=fields.Datetime.now, required=True)
    author_id = fields.Many2one('res.users', string='By', default=lambda self: self.env.uid, readonly=True)
    text = fields.Text(string='Entry', required=True)

    @api.model_create_multi
    def create(self, vals_list):
        cases = self.env['school.safeguarding.case'].browse([v['case_id'] for v in vals_list if v.get('case_id')])
        if any(c.state == 'closed' for c in cases) and not cases._is_lead():
            raise AccessError(_("This case is closed. Only the Safeguarding Lead can add to it."))
        return super().create(vals_list)


class SafeguardingAction(models.Model):
    _name = 'school.safeguarding.action'
    _description = 'Safeguarding follow-up action'
    _order = 'due_date, id'

    case_id = fields.Many2one('school.safeguarding.case', required=True, ondelete='cascade', index=True)
    action_type = fields.Selection(
        [('counselling', 'Counselling / support'), ('parent_meeting', 'Meeting with parents'),
         ('safety_plan', 'Safety plan'), ('monitoring', 'Monitoring / check-in'), ('discipline', 'Disciplinary step'),
         ('referral', 'Referral to an external agency'), ('training', 'Awareness / training'),
         ('other', 'Other')], string='Type', required=True, default='monitoring')
    description = fields.Char(string='What must be done', required=True)
    responsible_id = fields.Many2one(
        'res.users', string='Responsible', required=True, default=lambda self: self.env.uid,
        domain=lambda self: [('all_group_ids', 'in', self.env.ref('school_safeguarding.group_sg_officer').ids)])
    due_date = fields.Date(string='Due Date', required=True,
                           default=lambda self: fields.Date.context_today(self) + timedelta(days=7))
    state = fields.Selection([('todo', 'To do'), ('done', 'Done'), ('cancelled', 'Cancelled')], string='Status',
                             default='todo', required=True, index=True)
    done_date = fields.Date(string='Done On', readonly=True)
    done_by = fields.Many2one('res.users', string='Done By', readonly=True)
    activity_id = fields.Many2one('mail.activity', string='Reminder', ondelete='set null', copy=False)
    reminded_date = fields.Date(copy=False)
    overdue = fields.Boolean(compute='_compute_overdue', string='Overdue')

    @api.depends('state', 'due_date')
    def _compute_overdue(self):
        today = fields.Date.context_today(self)
        for action in self:
            action.overdue = action.state == 'todo' and bool(action.due_date) and action.due_date < today

    @api.depends('action_type', 'description')
    def _compute_display_name(self):
        types = dict(self._fields['action_type'].selection)
        for action in self:
            action.display_name = '%s: %s' % (types.get(action.action_type, ''), action.description or '')

    @api.model_create_multi
    def create(self, vals_list):
        cases = self.env['school.safeguarding.case'].browse([v['case_id'] for v in vals_list if v.get('case_id')])
        if any(c.state == 'closed' for c in cases) and not cases._is_lead():
            raise AccessError(_("This case is closed. Only the Safeguarding Lead can add to it."))
        actions = super().create(vals_list)
        for action in actions:
            action.activity_id = action.case_id.sudo().activity_schedule(
                'mail.mail_activity_data_todo', date_deadline=action.due_date,
                summary=_("Safeguarding action: %s", action.description), user_id=action.responsible_id.id)
        return actions

    def action_done(self):
        for action in self.filtered(lambda a: a.state == 'todo'):
            action.write({'state': 'done', 'done_date': fields.Date.context_today(action), 'done_by': self.env.uid})
            if action.activity_id.exists():
                action.activity_id.sudo().action_feedback(feedback=_("Done"))
            action.case_id._log(_("Action done: %s", action.display_name))

    def action_cancel(self):
        for action in self.filtered(lambda a: a.state == 'todo'):
            action.write({'state': 'cancelled'})
            if action.activity_id.exists():
                action.activity_id.sudo().unlink()
            action.case_id._log(_("Action cancelled: %s", action.display_name))


class SafeguardingEscalation(models.Model):
    _name = 'school.safeguarding.escalation'
    _description = 'Safeguarding escalation'
    _order = 'escalated_datetime desc, id desc'

    case_id = fields.Many2one('school.safeguarding.case', required=True, ondelete='cascade', index=True)
    level = fields.Selection(ESCALATION_LEVELS, string='Escalated To', required=True, default='lead')
    escalated_to = fields.Char(string='Person / Authority', help="Name of the person or authority informed.")
    reason = fields.Text(string='Why is this escalated', required=True)
    external_reference = fields.Char(string='Reference given by the authority')
    escalated_by = fields.Many2one('res.users', string='Escalated By', default=lambda self: self.env.uid, readonly=True)
    escalated_datetime = fields.Datetime(string='When', default=fields.Datetime.now, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        cases = self.env['school.safeguarding.case'].browse([v['case_id'] for v in vals_list if v.get('case_id')])
        if any(c.state == 'closed' for c in cases) and not cases._is_lead():
            raise AccessError(_("This case is closed. Only the Safeguarding Lead can add to it."))
        escalations = super().create(vals_list)
        leads = safeguarding_users(self.env, lead_only=True)
        for esc in escalations:
            level = dict(esc._fields['level'].selection)[esc.level]
            esc.case_id._log(_("Escalated to: %s", level))
            esc.case_id._notify_team(
                leads, _("Safeguarding: case %s escalated", esc.case_id.name),
                Markup(_("<p>Case <b>%(name)s</b> was escalated to <b>%(level)s</b>.</p>")) % {
                    'name': esc.case_id.name, 'level': level})
        return escalations


class SafeguardingAccessLog(models.Model):
    _name = 'school.safeguarding.access.log'
    _description = 'Safeguarding access log'
    _order = 'create_date desc, id desc'

    case_id = fields.Many2one('school.safeguarding.case', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', string='Opened By', required=True)
    viewed_datetime = fields.Datetime(string='Opened On', default=fields.Datetime.now, readonly=True)
