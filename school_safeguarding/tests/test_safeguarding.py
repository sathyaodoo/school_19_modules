# -*- coding: utf-8 -*-
import re
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import HttpCase, TransactionCase, tagged


def _user(env, login, *group_xmlids):
    groups = [env.ref('base.group_user')] + [env.ref(x) for x in group_xmlids]
    return env['res.users'].create({'name': login, 'login': login, 'group_ids': [(6, 0, [g.id for g in groups])]})


@tagged('post_install', '-at_install', 'school_safeguarding')
class TestSafeguarding(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        sg = 'school_safeguarding.'
        cls.reporter = _user(env, 'sg_reporter', 'ad_school_management.group_school_teacher', sg + 'group_sg_reporter')
        cls.officer = _user(env, 'sg_officer', sg + 'group_sg_reporter', sg + 'group_sg_officer', 'base.group_allow_export')
        cls.officer2 = _user(env, 'sg_officer2', sg + 'group_sg_reporter', sg + 'group_sg_officer')
        cls.lead = _user(env, 'sg_lead', sg + 'group_sg_reporter', sg + 'group_sg_officer', sg + 'group_sg_lead',
                         'base.group_allow_export')
        cls.principal = _user(env, 'sg_principal', 'ad_school_management.group_school_principal')
        cls.sysadmin = _user(env, 'sg_sysadmin', 'base.group_system')
        cls.Case = env['school.safeguarding.case']
        klass = env['school.class'].create({'name': 'SG Class', 'code': 'SGC1'})
        sec = env['school.section'].create({'name': 'A', 'class_id': klass.id, 'capacity': 30})
        year = env['school.academic.year'].create(
            {'name': 'SG Year', 'code': 'SGY', 'date_start': '2026-01-01', 'date_end': '2026-12-31'})
        cls.kid = env['school.student'].create(
            {'name': 'SG Kid', 'class_id': klass.id, 'section_id': sec.id, 'academic_year_id': year.id})

    # ---------------------------------------------------------------- helpers
    def _case(self, user=None, **kw):
        vals = {'category': 'bullying', 'description': 'SECRET DETAILS: he was pushed around repeatedly',
                'severity': 'medium'}
        vals.update(kw)
        return self.Case.with_user(user or self.officer).create(vals)

    def _messages_to(self, case, user):
        return case.message_ids.filtered(lambda m: user.partner_id in m.partner_ids)

    def _report(self, user, **kw):
        wizard = self.env['school.safeguarding.report.wizard'].with_user(user).create(dict(
            {'category': 'harassment', 'description': 'A teacher saw this in the corridor'}, **kw))
        wizard.action_submit()
        return wizard, self.Case.sudo().search([('name', '=', wizard.result_reference)])

    # ---------------------------------------------------------------- who can do what
    def test_groups_and_default_members(self):
        env = self.env
        teacher = env.ref('ad_school_management.group_school_teacher')
        reporter = env.ref('school_safeguarding.group_sg_reporter')
        officer = env.ref('school_safeguarding.group_sg_officer')
        lead = env.ref('school_safeguarding.group_sg_lead')
        self.assertIn(reporter, teacher.implied_ids)                     # every teacher can REPORT
        self.assertIn(reporter, officer.implied_ids)
        self.assertIn(officer, lead.implied_ids)
        self.assertNotIn(officer, env.ref('ad_school_management.group_school_principal').implied_ids)  # principal: not automatic
        self.assertIn(env.ref('base.user_admin'), lead.user_ids)         # so the first administrator can set things up

    def test_only_the_safeguarding_team_can_open_cases(self):
        case = self._case()
        for user in (self.principal, self.sysadmin, self.reporter):       # not even the administrator or the principal
            with self.assertRaises(AccessError, msg=user.login):
                self.Case.with_user(user).search([])
            with self.assertRaises(AccessError, msg=user.login):
                case.with_user(user).read(['name'])
            with self.assertRaises(AccessError, msg=user.login):
                self.Case.with_user(user).create({'category': 'bullying', 'description': 'x'})
        self.assertIn(case, self.Case.with_user(self.officer).search([]))
        self.assertIn(case, self.Case.with_user(self.officer2).search([]))
        self.assertIn(case, self.Case.with_user(self.lead).search([]))

    def test_menus_are_visible_only_to_the_right_people(self):
        """Also for a user that was given only the Lead group (the implied groups are not expanded by the ORM)."""
        only_lead = _user(self.env, 'sg_only_lead', 'school_safeguarding.group_sg_lead')
        only_officer = _user(self.env, 'sg_only_officer', 'school_safeguarding.group_sg_officer')
        teacher_only = _user(self.env, 'sg_teacher_only', 'school_safeguarding.group_sg_reporter')
        names = ('menu_sg_report', 'menu_sg_cases', 'menu_sg_actions', 'menu_sg_analysis')
        ids = {n: self.env.ref('school_safeguarding.' + n).id for n in names}
        visible = lambda user: {n for n, i in ids.items() if i in self.env['ir.ui.menu'].with_user(user)._visible_menu_ids()}  # noqa
        self.assertEqual(visible(teacher_only), {'menu_sg_report'})                       # a reporter only reports
        self.assertEqual(visible(only_officer), set(names))
        self.assertEqual(visible(only_lead), set(names))
        self.assertEqual(visible(self.principal), set())                                   # not even the principal
        self.assertEqual(visible(self.sysadmin), set())                                    # nor the Odoo administrator
        # and the report form works for a user that has only the officer or only the lead group
        for user in (only_officer, only_lead):
            wizard = self.env['school.safeguarding.report.wizard'].with_user(user).create(
                {'category': 'bullying', 'description': 'Seen at the gate'})
            wizard.action_submit()
            self.assertEqual(wizard.state, 'done')

    def test_a_lead_counts_as_an_officer_for_alerts_and_dropdowns(self):
        only_lead = _user(self.env, 'sg_lead_only', 'school_safeguarding.group_sg_lead')
        teacher_only = _user(self.env, 'sg_teacher_only2', 'ad_school_management.group_school_teacher')
        wizard, case = self._report(self.reporter)
        self.assertEqual(len(self._messages_to(case, only_lead)), 1)                   # alerted although it holds only the Lead group
        self.assertFalse(self._messages_to(case, teacher_only))                        # a teacher is never alerted
        domain = self.Case._fields['assigned_officer_id'].domain(self.Case)
        choices = self.env['res.users'].search(domain)
        self.assertIn(only_lead, choices)                                              # can be chosen as case officer
        self.assertIn(self.officer, choices)
        self.assertNotIn(teacher_only, choices)
        self.assertNotIn(self.principal, choices)
        # an effective report right for every teacher, without any extra step for the existing ones
        self.assertTrue(teacher_only.has_group('school_safeguarding.group_sg_reporter'))
        self.assertFalse(teacher_only.has_group('school_safeguarding.group_sg_officer'))

    def test_menus_are_restricted(self):
        def groups(xmlid):
            menu = self.env.ref(xmlid)
            return menu.group_ids if 'group_ids' in menu._fields else menu.groups_id
        officer = self.env.ref('school_safeguarding.group_sg_officer')
        self.assertIn(officer, groups('school_safeguarding.menu_sg_cases'))
        self.assertIn(officer, groups('school_safeguarding.menu_sg_actions'))
        self.assertIn(officer, groups('school_safeguarding.menu_sg_analysis'))
        self.assertIn(self.env.ref('school_safeguarding.group_sg_reporter'), groups('school_safeguarding.menu_sg_report'))

    def test_nothing_can_be_deleted(self):
        case = self._case()
        escalation = self.env['school.safeguarding.escalation'].with_user(self.officer).create(
            {'case_id': case.id, 'level': 'lead', 'reason': 'x'})
        for user in (self.officer, self.lead):
            for rec in (case, escalation):
                with self.assertRaises(AccessError, msg='%s %s' % (user.login, rec._name)):
                    rec.with_user(user).unlink()

    # ---------------------------------------------------------------- reporting
    def test_staff_report_reaches_the_team_but_the_reporter_cannot_read_it(self):
        wizard, case = self._report(self.reporter)
        self.assertTrue(case)
        self.assertEqual((wizard.state, wizard.result_reference, wizard.result_code), ('done', case.name, case.access_code))
        self.assertRegex(case.name, r'^SG/\d{4}/\d{4}$')
        self.assertEqual((case.source, case.reporter_partner_id, case.state), ('staff', self.reporter.partner_id, 'new'))
        self.assertEqual(case.create_uid.id, 1)                                       # not the reporter
        self.assertNotIn(self.reporter.partner_id, case.message_follower_ids.partner_id)   # not even a follower
        with self.assertRaises(AccessError):
            case.with_user(self.reporter).read(['description'])
        with self.assertRaises(AccessError):
            self.Case.with_user(self.reporter).search([])

    def test_anonymous_report_keeps_no_trace_of_the_reporter(self):
        wizard, case = self._report(self.reporter, is_anonymous=True)
        self.assertEqual((case.is_anonymous, case.source, case.reporter_partner_id.id, case.reporter_label),
                         (True, 'anonymous', False, 'Anonymous'))
        self.assertEqual(case.create_uid.id, 1)
        self.assertNotIn(self.reporter.partner_id, case.message_follower_ids.partner_id)
        self.assertNotIn(self.reporter.partner_id, case.message_ids.mapped('author_id'))
        self.assertTrue(wizard.result_code)                                           # the code is the only way back
        with self.assertRaises(ValidationError):                                      # and it can not be linked afterwards
            case.sudo().reporter_partner_id = self.reporter.partner_id

    def test_wizard_needs_a_description_and_a_reporter_group(self):
        wizard = self.env['school.safeguarding.report.wizard'].with_user(self.reporter).create(
            {'category': 'bullying', 'description': '   '})
        with self.assertRaises(UserError):
            wizard.action_submit()
        with self.assertRaises(AccessError):                                          # a user outside the groups
            self.env['school.safeguarding.report.wizard'].with_user(self.sysadmin).create({'category': 'bullying'})

    def test_new_case_alerts_the_team_without_any_details(self):
        wizard, case = self._report(self.reporter, immediate_risk=True, category='cyberbullying')
        for user in (self.officer, self.officer2, self.lead):
            told = self._messages_to(case, user)
            self.assertEqual(len(told), 1, user.login)
            self.assertIn(case.name, told.body)
            self.assertIn('Cyberbullying', told.body)
            self.assertIn('URGENT', told.body)
            self.assertNotIn('corridor', told.body)                                   # the description is never sent
            self.assertNotIn('&lt;', told.body)
        self.assertFalse(self._messages_to(case, self.reporter))                      # the reporter is not alerted
        self.assertFalse(self._messages_to(case, self.principal))                     # nor is anybody outside the team

    def test_severity_and_online_defaults(self):
        danger = self._case(immediate_risk=True, severity='low')
        self.assertEqual(danger.severity, 'high')                                     # danger now is never "low"
        self.assertEqual(self._case(immediate_risk=True, severity='critical').severity, 'critical')
        cyber = self._case(category='cyberbullying')
        self.assertTrue(cyber.is_online)
        self.assertFalse(self._case(category='harassment').is_online)

    # ---------------------------------------------------------------- workflow
    def test_workflow_and_its_rules(self):
        case = self._case()
        officer = case.with_user(self.officer)
        with self.assertRaises(UserError):
            officer.action_close()                                                    # must be assessed first
        officer.action_start_triage()
        self.assertEqual((case.state, case.assigned_officer_id, case.triage_by), ('triage', self.officer, self.officer))
        with self.assertRaises(UserError):
            officer.action_start_investigation()                                      # assessment missing
        case.triage_notes = 'No immediate risk. Parents to be informed.'
        officer.action_start_investigation()
        self.assertEqual((case.state, case.investigator_id), ('investigation', self.officer))
        self.assertTrue(case.investigation_start)
        with self.assertRaises(UserError):
            officer.action_to_follow_up()                                             # findings + outcome missing
        case.write({'findings': 'Statements agree', 'outcome': 'substantiated'})
        officer.action_to_follow_up()
        self.assertEqual(case.state, 'follow_up')
        with self.assertRaises(UserError):
            officer.action_close()                                                    # closure notes missing
        case.closure_notes = 'Counselling arranged; monitored for a term.'
        officer.action_close()
        self.assertEqual((case.state, case.closed_by), ('closed', self.officer))
        self.assertTrue(case.closed_datetime)
        self.assertTrue(case.log_ids.filtered(lambda l: l.log_type == 'system'))      # every step is in the log

    def test_cannot_close_with_open_actions_or_without_an_outcome(self):
        case = self._case()
        case.with_user(self.officer).action_start_triage()
        case.write({'closure_notes': 'done'})
        with self.assertRaises(UserError):
            case.with_user(self.officer).action_close()                               # no outcome
        case.outcome = 'no_concern'
        action = self.env['school.safeguarding.action'].with_user(self.officer).create(
            {'case_id': case.id, 'description': 'Check in with the child'})
        with self.assertRaises(UserError):
            case.with_user(self.officer).action_close()                               # open follow-up action
        action.with_user(self.officer).action_done()
        case.with_user(self.officer).action_close()
        self.assertEqual(case.state, 'closed')

    def test_closed_case_is_locked_and_only_the_lead_reopens_it(self):
        case = self._case(outcome='unsubstantiated', closure_notes='Nothing found')
        case.with_user(self.officer).action_start_triage()
        case.with_user(self.officer).action_close()
        with self.assertRaises(AccessError):
            case.with_user(self.officer).write({'description': 'rewritten history'})
        with self.assertRaises(AccessError):
            self.env['school.safeguarding.log'].with_user(self.officer).create({'case_id': case.id, 'text': 'late note'})
        with self.assertRaises(AccessError):
            case.with_user(self.officer).action_reopen()
        case.with_user(self.lead).write({'closure_notes': 'The Lead may correct it'})
        case.with_user(self.lead).action_reopen()
        self.assertEqual((case.state, bool(case.closed_datetime)), ('follow_up', False))
        case.with_user(self.officer).write({'description': 'open again, so it can be edited'})

    # ---------------------------------------------------------------- follow-up actions
    def test_follow_up_actions_reminders_and_overdue(self):
        case = self._case()
        Action = self.env['school.safeguarding.action']
        action = Action.with_user(self.officer).create({
            'case_id': case.id, 'action_type': 'parent_meeting', 'description': 'Meet the parents',
            'responsible_id': self.officer2.id, 'due_date': fields.Date.context_today(case) - timedelta(days=2)})
        self.assertTrue(action.activity_id)                                           # a To-Do for the responsible
        self.assertEqual(action.activity_id.user_id, self.officer2)
        self.assertTrue(action.overdue)
        self.assertEqual((case.action_open_count, case.action_overdue_count), (1, 1))
        self.Case._cron_reminders()
        self.assertEqual(len(self._messages_to(case, self.officer2).filtered(lambda m: 'overdue' in m.body)), 1)
        self.Case._cron_reminders()                                                   # the same day: not again
        self.assertEqual(len(self._messages_to(case, self.officer2).filtered(lambda m: 'overdue' in m.body)), 1)
        action.with_user(self.officer2).action_done()
        self.assertEqual((action.state, action.done_by, action.overdue), ('done', self.officer2, False))
        self.assertFalse(case.activity_ids)                                           # the To-Do is closed
        self.assertEqual((case.action_open_count, case.action_overdue_count), (0, 0))

    def test_cancelled_action_removes_its_reminder(self):
        case = self._case()
        action = self.env['school.safeguarding.action'].with_user(self.officer).create(
            {'case_id': case.id, 'description': 'Referral letter'})
        self.assertEqual(len(case.activity_ids), 1)
        action.with_user(self.officer).action_cancel()
        self.assertEqual((action.state, len(case.activity_ids)), ('cancelled', 0))
        self.assertEqual(case.action_open_count, 0)

    def test_unreviewed_new_case_reminder_is_sent_once(self):
        case = self._case()
        case.sudo().reported_datetime = fields.Datetime.now() - timedelta(hours=30)
        self.Case._cron_reminders()
        self.assertEqual(len(self._messages_to(case, self.lead).filtered(lambda m: 'waiting' in m.body)), 1)
        self.Case._cron_reminders()
        self.assertEqual(len(self._messages_to(case, self.lead).filtered(lambda m: 'waiting' in m.body)), 1)
        fresh = self._case()
        self.Case._cron_reminders()
        self.assertFalse(self._messages_to(fresh, self.lead).filtered(lambda m: 'waiting' in m.body))

    # ---------------------------------------------------------------- escalation
    def test_escalation_flag_level_and_alert_to_the_lead_only(self):
        case = self._case()
        Esc = self.env['school.safeguarding.escalation']
        Esc.with_user(self.officer).create({'case_id': case.id, 'level': 'lead', 'reason': 'Serious pattern'})
        self.assertEqual((case.escalated, case.escalation_level), (True, 'lead'))
        Esc.with_user(self.officer).create({
            'case_id': case.id, 'level': 'external', 'escalated_to': 'Child Welfare Committee',
            'reason': 'Possible abuse', 'external_reference': 'CWC-77'})
        self.assertEqual(case.escalation_level, 'external')                           # the highest level
        alerts = self._messages_to(case, self.lead).filtered(lambda m: 'escalated' in m.body)
        self.assertEqual(len(alerts), 2)
        self.assertFalse(self._messages_to(case, self.officer2).filtered(lambda m: 'escalated' in m.body))
        for alert in alerts:
            self.assertNotIn('Possible abuse', alert.body)                            # the reason stays in the case
        self.assertFalse(self._case().escalated)
        action = case.with_user(self.officer).action_escalate()
        self.assertEqual((action['res_model'], action['context']['default_case_id']),
                         ('school.safeguarding.escalation', case.id))

    # ---------------------------------------------------------------- audit, export, retention
    def test_opening_a_case_is_logged_and_only_the_lead_reads_the_log(self):
        case = self._case()
        case.with_user(self.officer).web_read({'name': {}})
        case.with_user(self.officer).web_read({'name': {}})                           # within 10 minutes: one entry
        case.with_user(self.officer2).web_read({'name': {}})
        logs = self.env['school.safeguarding.access.log'].sudo().search([('case_id', '=', case.id)])
        self.assertEqual(sorted(logs.mapped('user_id').ids), sorted((self.officer | self.officer2).ids))
        self.assertEqual(len(logs), 2)
        self.assertEqual(len(case.with_user(self.lead).access_log_ids), 2)             # the Lead can see who opened it
        with self.assertRaises(AccessError):
            case.with_user(self.officer).access_log_ids.mapped('user_id')              # officers can not
        with self.assertRaises(AccessError):
            self.env['school.safeguarding.access.log'].with_user(self.officer).search([])
        old = fields.Datetime.now() - timedelta(minutes=30)
        self.env.cr.execute("UPDATE school_safeguarding_access_log SET create_date = %s WHERE id = %s",
                            (old, logs.filtered(lambda l: l.user_id == self.officer).id))
        logs.invalidate_recordset()
        case.with_user(self.officer).web_read({'name': {}})                           # after 10 minutes: a new entry
        self.assertEqual(self.env['school.safeguarding.access.log'].sudo().search_count([('case_id', '=', case.id)]), 3)

    def test_a_new_unsaved_form_and_creating_by_hand_do_not_break_the_audit_log(self):
        """The "New" button: the form reads a record that has no id yet (this once raised a Validation Error)."""
        Log = self.env['school.safeguarding.access.log'].sudo()
        before = Log.search_count([])
        for user in (self.officer, self.lead, self.env.ref('base.user_admin')):
            virtual = self.Case.with_user(user).new({'category': 'bullying', 'description': 'typed by hand'})
            self.assertEqual(virtual.web_read({'name': {}, 'category': {}})[0]['category'], 'bullying')
            self.Case.with_user(user).onchange({}, [], {'category': {}, 'description': {}, 'name': {}, 'state': {}})
        self.assertEqual(Log.search_count([]), before)                                 # nothing logged for an unsaved form
        # a Safeguarding Officer writing a case by hand (New -> Save), as the form does
        result = self.Case.with_user(self.officer).web_save(
            {'category': 'bullying', 'description': 'Found a note in a locker', 'severity': 'low'}, {'name': {}, 'state': {}})
        case = self.Case.browse(result[0]['id'])
        self.assertEqual((case.source, case.state), ('officer', 'new'))
        self.assertEqual(Log.search_count([('case_id', '=', case.id)]), 1)             # the saved case is logged once

    def test_the_opener_sees_his_own_name_in_the_log_at_once(self):
        case = self._case()
        Log = self.env['school.safeguarding.access.log'].sudo()
        first = case.with_user(self.lead).web_read({'name': {}, 'access_log_ids': {}})[0]['access_log_ids']
        self.assertEqual(Log.browse(first).user_id, self.lead)                        # in the very first response
        again = case.with_user(self.lead).web_read({'name': {}, 'access_log_ids': {}})[0]['access_log_ids']
        self.assertEqual(sorted(again), sorted(first))                                # opening again within 10 minutes: no new row
        # somebody who may not open the case is refused and leaves no entry
        before = Log.search_count([])
        with self.assertRaises(AccessError):
            case.with_user(self.reporter).web_read({'name': {}})
        with self.assertRaises(AccessError):
            case.with_user(self.principal).web_read({'name': {}})
        self.assertEqual(Log.search_count([]), before)

    def test_export_is_for_the_lead_only(self):
        case = self._case()
        with self.assertRaises(AccessError):
            case.with_user(self.officer).export_data(['name'])
        self.assertTrue(case.with_user(self.lead).export_data(['name'])['datas'])      # officers have the export right too


    def test_retention_date(self):
        case = self._case(outcome='no_concern', closure_notes='ok')
        self.assertFalse(case.retention_until)                                         # open: no date
        case.with_user(self.officer).action_start_triage()
        case.with_user(self.officer).action_close()
        self.assertEqual(case.retention_until, case.closed_datetime.date() + relativedelta(years=7))
        self.env['ir.config_parameter'].sudo().set_param('school_safeguarding.retention_years', '3')
        other = self._case(outcome='no_concern', closure_notes='ok')
        other.with_user(self.officer).action_start_triage()
        other.with_user(self.officer).action_close()
        self.assertEqual(other.retention_until, other.closed_datetime.date() + relativedelta(years=3))
        due = self.Case.with_user(self.lead).search([('retention_until', '<=', fields.Date.today() + relativedelta(years=10))])
        self.assertIn(case, due)

    def test_a_known_reporter_hears_that_it_was_closed_but_never_the_details(self):
        wizard, case = self._report(self.reporter)
        case.write({'outcome': 'substantiated', 'closure_notes': 'Parents called, sanction given'})
        case.with_user(self.officer).action_start_triage()
        case.with_user(self.officer).action_close()
        notices = self.env['mail.message'].sudo().search([('partner_ids', 'in', self.reporter.partner_id.ids),
                                                          ('subject', 'ilike', case.name)])
        self.assertEqual(len(notices), 1)
        self.assertIn('closed', notices.body)
        for secret in ('substantiated', 'sanction', 'corridor'):
            self.assertNotIn(secret, notices.body)

    def test_an_anonymous_reporter_is_told_nothing_and_nobody_is_guessed(self):
        wizard, case = self._report(self.reporter, is_anonymous=True)
        case.write({'outcome': 'substantiated', 'closure_notes': 'x'})
        case.with_user(self.officer).action_start_triage()
        case.with_user(self.officer).action_close()
        self.assertFalse(self.env['mail.message'].sudo().search(
            [('partner_ids', 'in', self.reporter.partner_id.ids), ('subject', 'ilike', case.name)]))

    def test_status_texts_for_the_reporter(self):
        case = self._case()
        self.assertEqual(case.public_status, 'Received')
        case.with_user(self.officer).action_start_triage()
        self.assertEqual(case.public_status, 'Being reviewed')
        self.assertEqual(len(case.access_code), 8)
        self.assertNotRegex(case.access_code, r'[01OI]')                                # no look-alike characters
        self.assertNotEqual(self._case().access_code, case.access_code)


@tagged('post_install', '-at_install', 'school_safeguarding')
class TestSafeguardingPortal(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        klass = env['school.class'].create({'name': 'SGP Class', 'code': 'SGP1'})
        sec = env['school.section'].create({'name': 'A', 'class_id': klass.id, 'capacity': 30})
        year = env['school.academic.year'].create(
            {'name': 'SGP Year', 'code': 'SGPY', 'date_start': '2026-01-01', 'date_end': '2026-12-31'})
        cls.kid = env['school.student'].create(
            {'name': 'SGP Kid', 'class_id': klass.id, 'section_id': sec.id, 'academic_year_id': year.id})
        cls.kid_user = env['res.users'].create({
            'name': 'SGP Kid', 'login': 'sgpkid', 'password': 'sgpkid', 'partner_id': cls.kid.partner_id.id,
            'group_ids': [(6, 0, [env.ref('base.group_portal').id])]})
        cls.officer = _user(env, 'sgp_officer', 'school_safeguarding.group_sg_reporter',
                            'school_safeguarding.group_sg_officer')
        cls.Case = env['school.safeguarding.case']

    def _csrf(self, html):
        return re.search(r'name="csrf_token"\s+value="([^"]+)"', html).group(1)

    def _submit(self, **data):
        page = self.url_open('/my/safeguarding')
        payload = {'csrf_token': self._csrf(page.text), 'category': 'bullying',
                   'description': 'Some older children take my lunch every day'}
        payload.update(data)
        return self.url_open('/my/safeguarding/submit', data=payload)

    def _case_from(self, response):
        reference = re.search(r'Reference: <b>([^<]+)</b>', response.text).group(1)
        code = re.search(r'Code: <b[^>]*>([^<]+)</b>', response.text).group(1)
        return self.Case.sudo().search([('name', '=', reference)]), reference, code

    def test_card_and_form(self):
        self.authenticate('sgpkid', 'sgpkid')
        self.assertIn('/my/safeguarding', self.url_open('/my').text)
        page = self.url_open('/my/safeguarding')
        self.assertEqual(page.status_code, 200)
        for text in ('Report a Concern', 'CHILDLINE 1098', 'Send this report anonymously', 'Cyberbullying',
                     'Child-safety concern', 'This happened to me'):
            self.assertIn(text, page.text)

    def test_form_html_has_every_input_the_student_needs(self):
        """What the browser really gets: a visible description box (it once rendered as nothing)."""
        self.authenticate('sgpkid', 'sgpkid')
        html = self.url_open('/my/safeguarding').text
        self.assertRegex(html, r'<textarea[^>]*name="description"[^>]*>')
        self.assertIn('</textarea>', html)
        for name in ('category', 'incident_date', 'location', 'involved', 'urgent', 'anonymous'):
            self.assertRegex(html, r'name="%s"' % name)
        # after a refused submit the text the student typed is kept in the box
        page = self.url_open('/my/safeguarding')
        refused = self.url_open('/my/safeguarding/submit', data={
            'csrf_token': self._csrf(page.text), 'category': '', 'description': 'My text must not be lost'})
        self.assertEqual(refused.status_code, 400)
        self.assertRegex(refused.text, r'<textarea[^>]*name="description"[^>]*>\s*My text must not be lost\s*</textarea>')

    def test_named_report(self):
        self.authenticate('sgpkid', 'sgpkid')
        response = self._submit(location='Playground', about_me='on', urgent='on', incident_date='2026-08-02')
        self.assertEqual(response.status_code, 200)
        case, reference, code = self._case_from(response)
        self.assertEqual((case.source, case.reporter_partner_id, case.is_anonymous), ('student', self.kid.partner_id, False))
        self.assertEqual((case.category, case.location, str(case.incident_date)), ('bullying', 'Playground', '2026-08-02'))
        self.assertEqual(case.affected_student_ids, self.kid)                            # "this happened to me"
        self.assertTrue(case.immediate_risk)
        self.assertEqual(case.severity, 'high')
        self.assertEqual(case.create_uid.id, 1)
        self.assertIn('CHILDLINE 1098', response.text)                                   # urgent: the helpline is repeated
        self.assertEqual(code, case.access_code)

    def test_anonymous_report_is_not_linked_to_the_student(self):
        self.authenticate('sgpkid', 'sgpkid')
        response = self._submit(anonymous='on', about_me='on')
        case, reference, code = self._case_from(response)
        self.assertEqual((case.is_anonymous, case.source), (True, 'anonymous'))
        self.assertFalse(case.reporter_partner_id)
        self.assertFalse(case.affected_student_ids)                                      # "about me" is ignored when anonymous
        self.assertEqual(case.create_uid.id, 1)
        self.assertNotIn(self.kid.partner_id, case.message_ids.mapped('author_id'))
        self.assertNotIn(self.kid_user.partner_id, case.message_follower_ids.partner_id)
        self.assertIn('only</b> way', response.text)

    def test_bad_input_creates_nothing(self):
        self.authenticate('sgpkid', 'sgpkid')
        before = self.Case.sudo().search_count([])
        self.assertEqual(self._submit(category='hacking').status_code, 400)
        self.assertEqual(self._submit(category='').status_code, 400)
        self.assertEqual(self._submit(description='short').status_code, 400)
        self.assertEqual(self._submit(description='x' * 5001).status_code, 400)
        self.assertEqual(self.Case.sudo().search_count([]), before)
        # markup is kept as plain text, never executed
        response = self._submit(description='<script>alert(1)</script> they hurt me', location='<b>x</b>')
        case, _ref, _code = self._case_from(response)
        self.assertIn('<script>', case.description)
        self.assertNotIn('<script>', response.text)

    def test_csrf_is_required(self):
        self.authenticate('sgpkid', 'sgpkid')
        response = self.url_open('/my/safeguarding/submit', data={'category': 'bullying', 'description': 'no token here at all'})
        self.assertIn(response.status_code, (400, 403))

    def test_status_page_shows_only_the_status(self):
        self.authenticate('sgpkid', 'sgpkid')
        case, reference, code = self._case_from(self._submit(anonymous='on'))
        case.sudo().write({'public_update': 'We are looking into it. Thank you.', 'assigned_officer_id': self.officer.id})
        page = self.url_open('/my/safeguarding/status')
        csrf = self._csrf(page.text)
        found = self.url_open('/my/safeguarding/status', data={'csrf_token': csrf, 'reference': reference, 'code': code.lower()})
        for text in (reference, 'Received', 'We are looking into it'):
            self.assertIn(text, found.text)
        for secret in ('older children', 'lunch', 'sgp_officer', 'bullying'):
            self.assertNotIn(secret, found.text)                                         # nothing of the case
        wrong = self.url_open('/my/safeguarding/status', data={'csrf_token': csrf, 'reference': reference, 'code': 'WRONG123'})
        self.assertIn('could not find', wrong.text)
        self.assertNotIn('Received', wrong.text)
        unknown = self.url_open('/my/safeguarding/status', data={'csrf_token': csrf, 'reference': 'SG/2026/9999', 'code': code})
        self.assertIn('could not find', unknown.text)                                    # same message: no hint

    def test_guessing_codes_is_stopped(self):
        self.authenticate('sgpkid', 'sgpkid')
        case, reference, code = self._case_from(self._submit(anonymous='on'))
        csrf = self._csrf(self.url_open('/my/safeguarding/status').text)
        for _i in range(10):
            self.url_open('/my/safeguarding/status', data={'csrf_token': csrf, 'reference': reference, 'code': 'AAAAAAAA'})
        blocked = self.url_open('/my/safeguarding/status', data={'csrf_token': csrf, 'reference': reference, 'code': code})
        self.assertIn('Too many tries', blocked.text)
        self.assertNotIn('Received', blocked.text)

    def test_too_many_reports_in_an_hour_are_stopped(self):
        self.authenticate('sgpkid', 'sgpkid')
        for i in range(5):
            self.assertEqual(self._submit(description='Report number %s about my class' % i).status_code, 200)
        sixth = self._submit(description='Report number six about my class')
        self.assertEqual(sixth.status_code, 400)
        self.assertIn('several reports', sixth.text)

    def test_a_student_login_can_never_read_cases(self):
        case = self.Case.with_user(self.officer).create({'category': 'bullying', 'description': 'x'})
        with self.assertRaises(AccessError):
            self.Case.with_user(self.kid_user).search([])
        with self.assertRaises(AccessError):
            case.with_user(self.kid_user).read(['name'])
