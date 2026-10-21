# -*- coding: utf-8 -*-
import logging

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .wellbeing_base import counsellor_users

_logger = logging.getLogger(__name__)

CHECKIN_STATES = [('good', 'Good'), ('okay', 'Okay'), ('struggling', 'Struggling'), ('need_help', 'Need help')]
RATING = [('1', '1 - No concern'), ('2', '2 - Slight'), ('3', '3 - Moderate'), ('4', '4 - High'), ('5', '5 - Serious')]


class WellbeingCheckin(models.Model):
    """How the student feels: Good / Okay / Struggling / Need help. One per student per day (a new one that day replaces it)."""
    _name = 'school.wellbeing.checkin'
    _description = 'Well-being check-in (confidential)'
    _inherit = ['school.wellbeing.confidential']
    _order = 'checkin_date desc, id desc'

    student_id = fields.Many2one('school.student', string='Student', required=True, index=True, ondelete='cascade')
    class_id = fields.Many2one('school.class', related='student_id.class_id', store=True, string='Class')
    company_id = fields.Many2one('res.company', string='School / Board', required=True, default=lambda self: self.env.company)
    checkin_date = fields.Date(string='Date', required=True, default=fields.Date.context_today, index=True)
    status = fields.Selection(CHECKIN_STATES, string='How I feel', required=True, index=True)
    note = fields.Text(string='What is on my mind')
    wants_to_talk = fields.Boolean(string='Wants to talk to the counsellor')
    source = fields.Selection([('student', 'Student (portal)'), ('counsellor', 'Counsellor'), ('teacher', 'Teacher')],
                              string='Recorded By', default='counsellor', required=True)
    case_id = fields.Many2one('school.wellbeing.case', string='Case', ondelete='set null', readonly=True)
    alerted_need_help = fields.Boolean(copy=False)
    alerted_streak = fields.Boolean(copy=False)
    alerted_talk = fields.Boolean(copy=False)

    _student_day_uniq = models.Constraint('unique(student_id, checkin_date)', 'This student already has a check-in for that day.')

    @api.constrains('note')
    def _check_note(self):
        for checkin in self:
            if checkin.note and len(checkin.note) > 1000:
                raise ValidationError(_("The note can be 1000 characters at most."))

    @api.depends('student_id.name', 'checkin_date', 'status')
    def _compute_display_name(self):
        states = dict(self._fields['status'].selection)
        for checkin in self:
            checkin.display_name = '%s - %s - %s' % (checkin.student_id.name or '', checkin.checkin_date or '', states.get(checkin.status, ''))

    # ------------------------------------------------------------------ reactions
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('company_id') and vals.get('student_id'):
                student = self.env['school.student'].sudo().browse(vals['student_id'])
                vals['company_id'] = student.company_id.id or self.env.company.id
        checkins = super().create(vals_list)
        for checkin in checkins:
            checkin._react(previous=None)
        return checkins

    def write(self, vals):
        previous = {c.id: (c.status, c.wants_to_talk) for c in self}
        res = super().write(vals)
        if 'status' in vals or 'wants_to_talk' in vals:
            for checkin in self:
                checkin._react(previous=previous.get(checkin.id))
        return res

    def _alert_counsellors(self, text, urgent=False):
        """Inbox message to the counsellors: the reference only, never the name and never the note."""
        partners = counsellor_users(self.env).mapped('partner_id').ids
        if not partners:
            return
        try:
            self.env['mail.thread'].sudo().message_notify(
                partner_ids=partners,
                subject=_("Well-being: %s", _("URGENT") if urgent else _("check-in alert")),
                body=Markup(_("<p>%(text)s</p><p>Open Well-being &gt; Check-ins. Names and notes are never sent by message.</p>")) % {'text': text})
        except Exception:
            _logger.exception("Well-being: the counsellors could not be alerted")

    def _react(self, previous):
        self.ensure_one()
        cfg = self.env['school.wellbeing.config']._get(self.company_id)
        prev_status, prev_talk = previous or (None, False)
        if self.status == 'need_help' and prev_status != 'need_help' and not self.alerted_need_help:
            self.sudo().alerted_need_help = True
            self._alert_counsellors(_("A student chose 'Need help' in a check-in (%s). Please look at it today.", self._ref()), urgent=True)
            if cfg.auto_case_need_help:
                self._ensure_case('high', _("The student chose 'Need help' in the check-in of %s.", self.checkin_date))
        elif self.status == 'struggling' and prev_status != 'struggling' and not self.alerted_streak:
            if self._streak() >= max(cfg.struggling_streak, 1):
                self.sudo().alerted_streak = True
                self._alert_counsellors(_("A student has been 'Struggling' in %(n)s check-ins in a row (%(ref)s).",
                                          n=cfg.struggling_streak, ref=self._ref()))
                self._ensure_case('medium', _("'Struggling' in %s check-ins in a row.", cfg.struggling_streak))
        if self.wants_to_talk and not prev_talk and not self.alerted_talk:
            self.sudo().alerted_talk = True
            self._alert_counsellors(_("A student asked to talk to a counsellor (%s).", self._ref()))
            self._ensure_case('medium', _("The student asked to talk to a counsellor in the check-in of %s.", self.checkin_date), talk=True)

    def _ref(self):
        return 'WBC/%05d' % self.id

    def _streak(self):
        """How many of the latest check-ins, ending with this one, are 'Struggling' or worse."""
        latest = self.sudo().search([('student_id', '=', self.student_id.id), ('checkin_date', '<=', self.checkin_date)],
                                    order='checkin_date desc, id desc', limit=10)
        count = 0
        for checkin in latest:
            if checkin.status in ('struggling', 'need_help'):
                count += 1
            else:
                break
        return count

    def _ensure_case(self, level, text, talk=False):
        """Open (or add to) the case of the student. The note of the check-in is NOT copied."""
        self.ensure_one()
        case = self.env['school.wellbeing.case']._raise_for_student(
            self.student_id, level, text, source='self' if talk else 'checkin', talk=talk, company=self.company_id)
        self.sudo().case_id = case


class WellbeingAssessment(models.Model):
    """A screening: the counsellor rates social adjustment, peer relationships, academic stress and emotional well-being
    (1 = no concern ... 5 = serious concern) to follow the trend."""
    _name = 'school.wellbeing.assessment'
    _description = 'Well-being screening (confidential)'
    _inherit = ['school.wellbeing.confidential']
    _order = 'assessment_date desc, id desc'

    student_id = fields.Many2one('school.student', string='Student', required=True, index=True, ondelete='cascade')
    class_id = fields.Many2one('school.class', related='student_id.class_id', store=True, string='Class')
    company_id = fields.Many2one('res.company', string='School / Board', required=True, default=lambda self: self.env.company)
    case_id = fields.Many2one('school.wellbeing.case', string='Case', ondelete='set null',
                              domain="[('student_id', '=', student_id)]")
    assessment_date = fields.Date(string='Date', required=True, default=fields.Date.context_today, index=True)
    counsellor_id = fields.Many2one('res.users', string='Counsellor', required=True, default=lambda self: self.env.uid)
    social_adjustment = fields.Selection(RATING, string='Social adjustment', required=True, default='1')
    peer_relationships = fields.Selection(RATING, string='Peer relationships', required=True, default='1')
    academic_stress = fields.Selection(RATING, string='Academic stress', required=True, default='1')
    emotional_wellbeing = fields.Selection(RATING, string='Emotional well-being', required=True, default='1')
    bullying_concern = fields.Boolean(string='Bullying concern')
    social_value = fields.Integer(compute='_compute_values', store=True, aggregator='avg', string='Social adjustment (1-5)')
    peer_value = fields.Integer(compute='_compute_values', store=True, aggregator='avg', string='Peer relationships (1-5)')
    stress_value = fields.Integer(compute='_compute_values', store=True, aggregator='avg', string='Academic stress (1-5)')
    emotional_value = fields.Integer(compute='_compute_values', store=True, aggregator='avg', string='Emotional well-being (1-5)')
    highest = fields.Integer(compute='_compute_values', store=True, aggregator='max', string='Highest concern')
    notes = fields.Text(string='Notes')

    @api.depends('social_adjustment', 'peer_relationships', 'academic_stress', 'emotional_wellbeing')
    def _compute_values(self):
        for rec in self:
            rec.social_value = int(rec.social_adjustment or 1)
            rec.peer_value = int(rec.peer_relationships or 1)
            rec.stress_value = int(rec.academic_stress or 1)
            rec.emotional_value = int(rec.emotional_wellbeing or 1)
            rec.highest = max(rec.social_value, rec.peer_value, rec.stress_value, rec.emotional_value)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('company_id') and vals.get('student_id'):
                vals['company_id'] = self.env['school.student'].sudo().browse(vals['student_id']).company_id.id or self.env.company.id
        return super().create(vals_list)

    @api.depends('student_id.name', 'assessment_date')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s - %s' % (rec.student_id.name or '', rec.assessment_date or '')
