# -*- coding: utf-8 -*-
import re
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import HttpCase, TransactionCase, tagged


def _user(env, login, *xmlids, portal=False, partner=None, name=None):
    groups = [env.ref('base.group_portal' if portal else 'base.group_user')] + [env.ref(x) for x in xmlids]
    vals = {'name': name or login, 'login': login, 'password': login, 'group_ids': [(6, 0, [g.id for g in groups])]}
    if partner:
        vals['partner_id'] = partner.id
    return env['res.users'].create(vals)


class _World:
    @classmethod
    def _build(cls):
        env = cls.env
        klass = env['school.class'].create({'name': 'WB Class', 'code': 'WBC1'})
        sec = env['school.section'].create({'name': 'A', 'class_id': klass.id, 'capacity': 40})
        year = env['school.academic.year'].create({'name': 'WB Year', 'code': 'WBY', 'date_start': '2026-01-01', 'date_end': '2026-12-31'})
        mk = lambda name: env['school.student'].create({                                                # noqa: E731
            'name': name, 'class_id': klass.id, 'section_id': sec.id, 'academic_year_id': year.id})
        cls.s1, cls.s2, cls.s3 = mk('Asha Secret'), mk('Bala Hidden'), mk('Charu Private')
        cls.parent = env['school.parent'].create({'name': 'Parent One', 'relation': 'father', 'phone': '9000000010',
                                                  'email': 'p1@test.example', 'student_ids': [(6, 0, cls.s1.ids)]})
        cls.parent2 = env['school.parent'].create({'name': 'Parent Two', 'relation': 'mother', 'phone': '9000000011',
                                                   'email': 'p2@test.example', 'student_ids': [(6, 0, cls.s2.ids)]})
        cls.cfg = env['school.wellbeing.config']._get()
        wb = lambda g: 'school_safeguarding.group_wb_' + g                                                  # noqa: E731
        cls.teacher = _user(env, 'wb_teacher', 'ad_school_management.group_school_teacher')
        cls.principal = _user(env, 'wb_principal', 'ad_school_management.group_school_principal')
        cls.sysadmin = _user(env, 'wb_sysadmin', 'base.group_system', 'ad_school_management.group_school_admin')
        cls.c1 = _user(env, 'wb_c1', wb('counsellor'))
        cls.c2 = _user(env, 'wb_c2', wb('counsellor'))
        cls.lead = _user(env, 'wb_lead', wb('lead'))
        cls.Case = env['school.wellbeing.case']
        cls.area_bully = env.ref('school_safeguarding.area_bullying')
        cls.area_stress = env.ref('school_safeguarding.area_academic_stress')


@tagged('post_install', '-at_install', 'school_safeguarding', 'school_wellbeing')
class TestWellbeing(_World, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._build()

    # ---------------------------------------------------------------- helpers
    def _case(self, student=None, user=None, **kw):
        vals = {'student_id': (student or self.s1).id, 'concern_text': 'Sits alone at break', 'level': 'medium'}
        vals.update(kw)
        return self.Case.with_user(user or self.c1).create(vals)

    def _messages(self, user):
        return self.env['mail.message'].sudo().search([('partner_ids', 'in', user.partner_id.ids)])

    def _mail_text(self, user):
        return ' '.join('%s %s' % (m.subject or '', m.body or '') for m in self._messages(user))

    # ---------------------------------------------------------------- who can see anything
    def test_only_counsellors_and_the_lead_see_well_being_records(self):
        case = self._case()
        checkin = self.env['school.wellbeing.checkin'].create({'student_id': self.s1.id, 'status': 'okay'})
        for user in (self.teacher, self.principal, self.sysadmin):
            for model in ('school.wellbeing.case', 'school.wellbeing.session', 'school.wellbeing.intervention',
                          'school.wellbeing.referral', 'school.wellbeing.log', 'school.wellbeing.checkin',
                          'school.wellbeing.assessment', 'school.wellbeing.access.log'):
                with self.assertRaises(AccessError, msg='%s on %s' % (user.login, model)):
                    self.env[model].with_user(user).search([])
            with self.assertRaises(AccessError):
                case.with_user(user).read(['concern_text'])
            with self.assertRaises(AccessError):
                checkin.with_user(user).read(['note'])
        self.assertTrue(self.Case.with_user(self.c1).search([]))
        self.assertTrue(self.Case.with_user(self.lead).search([]))

    def test_menus_per_role(self):
        ids = {n: self.env.ref('school_safeguarding.menu_wb_' + n).id for n in ('raise', 'cases', 'checkins', 'settings', 'areas')}
        seen = lambda u: sorted(n for n, i in ids.items() if i in self.env['ir.ui.menu'].with_user(u)._visible_menu_ids())  # noqa: E731
        self.assertEqual(seen(self.teacher), ['raise'])                                                  # a teacher can only raise a concern
        self.assertEqual(seen(self.principal), ['raise'])                                                # the principal has no access either
        self.assertEqual(seen(self.sysadmin), ['raise'])                                                 # nor the Odoo administrator
        self.assertEqual(seen(self.c1), ['cases', 'checkins', 'raise'])
        self.assertEqual(seen(self.lead), ['areas', 'cases', 'checkins', 'raise', 'settings'])

    def test_nothing_can_be_deleted(self):
        case = self._case()
        session = self.env['school.wellbeing.session'].with_user(self.c1).create({'case_id': case.id})
        for user in (self.c1, self.lead):
            with self.assertRaises(AccessError):
                case.with_user(user).unlink()
            with self.assertRaises(AccessError):
                session.with_user(user).unlink()
        self.assertTrue(self.env['school.wellbeing.area'].with_user(self.lead).create({'name': 'Tmp'}).unlink())   # tags only

    def test_export_is_for_the_lead_only(self):
        case = self._case()
        checkin = self.env['school.wellbeing.checkin'].create({'student_id': self.s1.id, 'status': 'good'})
        with self.assertRaises(AccessError):
            case.with_user(self.c1).export_data(['name'])
        with self.assertRaises(AccessError):
            checkin.with_user(self.c1).export_data(['status'])
        self.assertTrue(case.with_user(self.lead).export_data(['name'])['datas'])
        self.assertTrue(checkin.with_user(self.lead).export_data(['status'])['datas'])

    # ---------------------------------------------------------------- restricted cases
    def test_a_restricted_case_is_only_for_its_counsellor_and_the_lead(self):
        case = self._case(counsellor_id=self.c1.id, is_restricted=True)
        session = self.env['school.wellbeing.session'].with_user(self.c1).create({'case_id': case.id, 'notes': 'private'})
        item = self.env['school.wellbeing.intervention'].with_user(self.c1).create({'case_id': case.id, 'description': 'Meet'})
        self.assertEqual(self.Case.with_user(self.c1).search([('id', '=', case.id)]), case)
        self.assertEqual(self.Case.with_user(self.lead).search([('id', '=', case.id)]), case)
        self.assertFalse(self.Case.with_user(self.c2).search([('id', '=', case.id)]))
        with self.assertRaises(AccessError):
            case.with_user(self.c2).read(['concern_text'])
        self.assertFalse(self.env['school.wellbeing.session'].with_user(self.c2).search([('id', '=', session.id)]))
        self.assertFalse(self.env['school.wellbeing.intervention'].with_user(self.c2).search([('id', '=', item.id)]))
        self.assertFalse(self.env['school.wellbeing.log'].with_user(self.c2).search([('case_id', '=', case.id)]))
        open_case = self._case(self.s2)                                                                  # not restricted: every counsellor
        self.assertEqual(self.Case.with_user(self.c2).search([('id', '=', open_case.id)]), open_case)

    def test_who_may_restrict_a_case(self):
        case = self._case(counsellor_id=self.c1.id)
        with self.assertRaises(AccessError):
            case.with_user(self.c2).write({'is_restricted': True})
        case.with_user(self.c1).write({'is_restricted': True})
        self.assertTrue(case.is_restricted)
        case.with_user(self.lead).write({'is_restricted': False})
        self.assertFalse(case.is_restricted)

    # ---------------------------------------------------------------- audit log
    def test_opening_a_case_is_logged_and_only_the_lead_reads_the_log(self):
        case = self._case()
        Log = self.env['school.wellbeing.access.log'].sudo()
        spec = {'name': {}, 'access_log_ids': {}}
        first = case.with_user(self.lead).web_read(spec)[0]['access_log_ids']
        self.assertEqual(Log.browse(first).user_id, self.lead)                                           # he sees himself at once
        self.assertEqual(sorted(case.with_user(self.lead).web_read(spec)[0]['access_log_ids']), sorted(first))   # 10 minutes: one row
        case.with_user(self.c1).web_read({'name': {}})
        self.assertEqual(Log.search([('case_id', '=', case.id)]).user_id, self.lead | self.c1)
        with self.assertRaises(AccessError):
            self.env['school.wellbeing.access.log'].with_user(self.c1).search([])
        before = Log.search_count([])
        with self.assertRaises(AccessError):
            case.with_user(self.teacher).web_read({'name': {}})                                          # refused: nothing is logged
        self.assertEqual(Log.search_count([]), before)
        new = self.Case.with_user(self.c1).new({'student_id': self.s1.id})                               # an unsaved form is not logged
        new.web_read({'name': {}})
        self.assertEqual(Log.search_count([]), before)

    # ---------------------------------------------------------------- the teacher raises a concern
    def test_a_teacher_raises_a_concern_and_cannot_read_it_back(self):
        wizard = self.env['school.wellbeing.concern.wizard'].with_user(self.teacher).create({
            'student_id': self.s1.id, 'area_ids': [(6, 0, (self.area_bully | self.area_stress).ids)], 'level': 'high',
            'description': 'Cried in class twice this week'})
        wizard.action_submit()
        self.assertEqual(wizard.state, 'done')
        case = self.Case.sudo().search([('student_id', '=', self.s1.id)])
        self.assertEqual((case.source, case.level, case.state, case.reporter_partner_id, wizard.reference),
                         ('teacher', 'high', 'new', self.teacher.partner_id, case.name))
        self.assertRegex(case.name, r'^WB/\d{4}/\d{4}$')
        self.assertEqual(case.area_ids, self.area_bully | self.area_stress)
        self.assertEqual(case.reporter_label, 'wb_teacher')
        with self.assertRaises(AccessError):
            self.Case.with_user(self.teacher).search([])
        with self.assertRaises(AccessError):
            case.with_user(self.teacher).read(['concern_text'])
        short = self.env['school.wellbeing.concern.wizard'].with_user(self.teacher).create({'student_id': self.s1.id, 'description': 'hmm'})
        with self.assertRaises(UserError):
            short.action_submit()

    def test_the_alert_never_carries_the_name_or_the_text(self):
        self._case(self.s2, level='high', concern_text='Bala is being teased about his father')
        text = self._mail_text(self.c2) + self._mail_text(self.lead)
        self.assertIn('WB/', text)                                                                       # the reference is there
        self.assertIn('Priority', text)                                                                  # high: look at it today
        for secret in ('Bala', 'Hidden', 'teased', 'father'):
            self.assertNotIn(secret, text)
        self.assertNotIn('WB/', self._mail_text(self.teacher))                                           # nobody else is told
        self.assertNotIn('WB/', self._mail_text(self.principal))

    # ---------------------------------------------------------------- the workflow
    def test_case_workflow_and_closing_rules(self):
        case = self._case(user=self.c2)
        self.assertEqual(case.state, 'new')
        with self.assertRaises(UserError):
            case.action_start_support()                                                                  # assess first
        case.with_user(self.c2).action_start_assessment()
        self.assertEqual((case.state, case.counsellor_id), ('assessment', self.c2))
        with self.assertRaises(UserError):
            case.with_user(self.c2).action_start_support()                                               # the assessment must be written
        case.assessment_notes = 'Withdrawn, eats alone.'
        case.with_user(self.c2).action_start_support()
        item = self.env['school.wellbeing.intervention'].with_user(self.c2).create({'case_id': case.id, 'description': 'Buddy plan'})
        case.with_user(self.c2).action_monitor()
        with self.assertRaises(UserError):
            case.with_user(self.c2).action_close()                                                       # no outcome
        case.outcome = 'improved'
        with self.assertRaises(UserError):
            case.with_user(self.c2).action_close()                                                       # no closure notes
        case.closure_notes = 'Making friends now.'
        with self.assertRaises(UserError):
            case.with_user(self.c2).action_close()                                                       # an intervention is still open
        item.with_user(self.c2).action_done()
        case.with_user(self.c2).action_close()
        self.assertEqual((case.state, case.closed_by), ('closed', self.c2))
        self.assertEqual(case.retention_until, case.closed_datetime.date() + relativedelta(years=7))
        self.assertGreaterEqual(len(case.log_ids), 5)
        self.cfg.retention_years = 3
        case.invalidate_recordset()
        case._compute_retention()
        self.assertEqual(case.retention_until, case.closed_datetime.date() + relativedelta(years=3))
        self.cfg.retention_years = 7

    def test_a_closed_case_is_locked_and_only_the_lead_reopens_it(self):
        case = self._case(user=self.c1)
        case.with_user(self.c1).action_start_assessment()
        case.write({'outcome': 'no_concern', 'closure_notes': 'Nothing found.'})
        case.with_user(self.c1).action_close()
        with self.assertRaises(AccessError):
            case.with_user(self.c1).write({'concern_text': 'changed'})
        with self.assertRaises(AccessError):
            self.env['school.wellbeing.session'].with_user(self.c1).create({'case_id': case.id})
        with self.assertRaises(AccessError):
            self.env['school.wellbeing.referral'].with_user(self.c1).create({'case_id': case.id, 'referred_to': 'x', 'reason': 'y'})
        with self.assertRaises(AccessError):
            case.with_user(self.c1).action_reopen()
        case.with_user(self.lead).action_reopen()
        self.assertEqual(case.state, 'monitoring')
        self.env['school.wellbeing.session'].with_user(self.c1).create({'case_id': case.id})            # open again: fine

    # ---------------------------------------------------------------- sessions
    def test_counselling_sessions(self):
        case = self._case()
        Session = self.env['school.wellbeing.session']
        session = Session.with_user(self.c1).create({'case_id': case.id, 'notes': 'Talked about exams', 'duration_minutes': 40,
                                                     'mood_start': 'struggling', 'mood_end': 'okay'})
        self.assertEqual((session.state, session.student_id, session.counsellor_id), ('scheduled', self.s1, self.c1))
        session.with_user(self.c1).action_done()
        self.assertEqual(session.state, 'done')
        self.assertIn('Session held (40 min)', ' '.join(case.log_ids.mapped('text')))
        absent = Session.with_user(self.c1).create({'case_id': case.id})
        absent.action_no_show()
        self.assertEqual(absent.state, 'no_show')
        absent.action_done()                                                                             # a finished one stays finished
        self.assertEqual(absent.state, 'no_show')
        cancelled = Session.with_user(self.c1).create({'case_id': case.id})
        cancelled.action_cancel()
        self.assertEqual(cancelled.state, 'cancelled')
        for minutes in (0, 481):
            with self.assertRaises(ValidationError):
                Session.with_user(self.c1).create({'case_id': case.id, 'duration_minutes': minutes})
        with self.assertRaises(AccessError):
            session.with_user(self.teacher).read(['notes'])

    def test_a_high_risk_session_tells_the_lead_only(self):
        case = self._case()
        session = self.env['school.wellbeing.session'].with_user(self.c1).create({'case_id': case.id, 'risk_level': 'high'})
        session.with_user(self.c1).action_done()
        self.assertIn('high risk', self._mail_text(self.lead))
        self.assertNotIn('high risk', self._mail_text(self.c2))
        self.assertNotIn('Secret', self._mail_text(self.lead))                                           # reference, not the name

    # ---------------------------------------------------------------- interventions
    def test_intervention_follow_up_and_reminders(self):
        case = self._case(user=self.c1)
        Item = self.env['school.wellbeing.intervention']
        item = Item.with_user(self.c1).create({'case_id': case.id, 'description': 'Meet the parents', 'kind': 'parent_meeting',
                                               'responsible_id': self.c2.id, 'due_date': fields.Date.today() - timedelta(days=2)})
        self.assertTrue(item.activity_id)
        self.assertEqual(item.activity_id.user_id, self.c2)
        self.assertTrue(item.overdue)
        self.assertEqual((case.open_intervention_count, case.overdue_intervention_count), (1, 1))
        self.Case._cron_reminders()
        self.assertIn(case.name, self._mail_text(self.c2))
        self.assertNotIn('Secret', self._mail_text(self.c2))
        count = len(self._messages(self.c2))
        self.Case._cron_reminders()                                                                      # once a day
        self.assertEqual(len(self._messages(self.c2)), count)
        item.with_user(self.c1).action_done()
        self.assertEqual((item.state, item.done_date), ('done', fields.Date.today()))
        self.assertFalse(self.env['mail.activity'].sudo().search([('res_model', '=', 'school.wellbeing.case'), ('res_id', '=', case.id),
                                                                  ('user_id', '=', self.c2.id)]))                 # the reminder is gone
        self.assertFalse(item.overdue)
        other = Item.with_user(self.c1).create({'case_id': case.id, 'description': 'Study plan'})
        other.action_cancel()
        self.assertEqual((other.state, case.open_intervention_count), ('cancelled', 0))

    # ---------------------------------------------------------------- referrals
    def test_referrals_need_consent_outside_the_school(self):
        case = self._case()
        Ref = self.env['school.wellbeing.referral'].with_user(self.c1)
        internal = Ref.create({'case_id': case.id, 'kind': 'doctor', 'referred_to': 'School nurse', 'reason': 'Headaches'})
        self.assertFalse(internal.is_external)
        internal.action_send()
        self.assertEqual(internal.state, 'sent')
        external = Ref.create({'case_id': case.id, 'kind': 'psychologist', 'referred_to': 'Dr Rao', 'reason': 'Anxiety', 'urgency': 'soon'})
        self.assertTrue(external.is_external)
        with self.assertRaises(UserError):
            external.action_send()                                                                       # no consent, no reason
        external.write({'consent_given': True, 'consent_by': 'Mother', 'consent_date': fields.Date.today()})
        external.action_send()
        external.action_accept()
        external.action_in_progress()
        external.action_complete()
        self.assertEqual(external.state, 'completed')
        waived = Ref.create({'case_id': case.id, 'kind': 'agency', 'referred_to': 'Child Welfare Committee', 'reason': 'Safety',
                             'consent_waived_reason': 'Child safety: the duty to report overrides consent.'})
        waived.action_send()
        self.assertEqual(waived.state, 'sent')
        with self.assertRaises(UserError):
            waived.action_send()                                                                         # already sent
        waived.action_decline()
        self.assertIn('Referral to Dr Rao: Completed', ' '.join(case.log_ids.mapped('text')))

    # ---------------------------------------------------------------- check-ins
    def test_need_help_alerts_the_counsellors_and_opens_a_case(self):
        Checkin = self.env['school.wellbeing.checkin']
        checkin = Checkin.create({'student_id': self.s1.id, 'status': 'need_help', 'note': 'I cannot cope with my father anymore',
                                  'source': 'student'})
        for user in (self.c1, self.lead):
            text = self._mail_text(user)
            self.assertIn('URGENT', text)
            self.assertIn(checkin._ref(), text)
            for secret in ('Asha', 'Secret', 'cope', 'father'):
                self.assertNotIn(secret, text)                                                           # neither the name nor the note
        case = checkin.case_id
        self.assertEqual((case.student_id, case.level, case.source, case.state), (self.s1, 'high', 'checkin', 'new'))
        self.assertNotIn('cope', case.concern_text)                                                      # the note is not copied
        count = len(self._messages(self.c1))
        checkin.write({'note': 'still bad'})                                                             # nothing new: no second alert
        checkin.write({'status': 'need_help'})
        self.assertEqual(len(self._messages(self.c1)), count)
        self.assertEqual(self.Case.sudo().search_count([('student_id', '=', self.s1.id)]), 1)
        self.assertNotIn('URGENT', self._mail_text(self.teacher) + self._mail_text(self.principal) + self._mail_text(self.sysadmin))

    def test_need_help_without_an_automatic_case(self):
        self.cfg.auto_case_need_help = False
        checkin = self.env['school.wellbeing.checkin'].create({'student_id': self.s2.id, 'status': 'need_help'})
        self.assertIn('URGENT', self._mail_text(self.c1))                                                # the alert always goes
        self.assertFalse(checkin.case_id)
        self.cfg.auto_case_need_help = True

    def test_a_run_of_struggling_check_ins_raises_an_alert(self):
        Checkin = self.env['school.wellbeing.checkin']
        today = fields.Date.today()
        first = Checkin.create({'student_id': self.s1.id, 'status': 'struggling', 'checkin_date': today - timedelta(days=2)})
        self.assertFalse(first.case_id)                                                                  # one is not a pattern yet
        self.assertNotIn(first._ref(), self._mail_text(self.c1))
        Checkin.create({'student_id': self.s1.id, 'status': 'good', 'checkin_date': today - timedelta(days=1)})
        second = Checkin.create({'student_id': self.s1.id, 'status': 'struggling', 'checkin_date': today})
        self.assertFalse(second.case_id)                                                                 # a good day in between: not in a row
        third = Checkin.create({'student_id': self.s1.id, 'status': 'struggling', 'checkin_date': today + timedelta(days=1)})
        self.assertTrue(third.case_id)                                                                   # two in a row
        self.assertEqual((third.case_id.level, third.case_id.source), ('medium', 'checkin'))
        self.assertIn(third._ref(), self._mail_text(self.c1))
        self.assertIn('Struggling', self._mail_text(self.c1))
        self.assertNotIn('Asha', self._mail_text(self.c1))
        self.assertTrue(third.alerted_streak)
        # 'Need help' after 'Struggling' counts as a worse day in the same run
        fourth = Checkin.create({'student_id': self.s1.id, 'status': 'need_help', 'checkin_date': today + timedelta(days=2)})
        self.assertEqual(fourth.case_id, third.case_id)                                                  # the same open case
        self.assertEqual(third.case_id.level, 'high')

    def test_asking_to_talk_opens_or_updates_the_case(self):
        Checkin = self.env['school.wellbeing.checkin']
        existing = self._case(self.s1)
        checkin = Checkin.create({'student_id': self.s1.id, 'status': 'okay', 'wants_to_talk': True})
        self.assertEqual(checkin.case_id, existing)                                                      # no second case for the student
        self.assertTrue(existing.wants_to_talk)
        self.assertEqual(self.Case.sudo().search_count([('student_id', '=', self.s1.id)]), 1)
        self.assertIn('asked to talk', self._mail_text(self.c1))
        fresh = Checkin.create({'student_id': self.s2.id, 'status': 'good', 'wants_to_talk': True})
        self.assertEqual((fresh.case_id.source, fresh.case_id.wants_to_talk, fresh.case_id.level), ('self', True, 'medium'))

    def test_a_good_check_in_alerts_nobody(self):
        before = len(self._messages(self.c1))
        checkin = self.env['school.wellbeing.checkin'].create({'student_id': self.s3.id, 'status': 'good'})
        self.assertEqual(len(self._messages(self.c1)), before)
        self.assertFalse(checkin.case_id)

    def test_one_check_in_per_day_and_a_short_note(self):
        Checkin = self.env['school.wellbeing.checkin']
        Checkin.create({'student_id': self.s1.id, 'status': 'good'})
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                Checkin.create({'student_id': self.s1.id, 'status': 'okay'})
        with self.assertRaises(ValidationError):
            Checkin.create({'student_id': self.s2.id, 'status': 'okay', 'note': 'x' * 1001})

    # ---------------------------------------------------------------- screenings
    def test_screening_ratings(self):
        case = self._case()
        shot = self.env['school.wellbeing.assessment'].with_user(self.c1).create({
            'student_id': self.s1.id, 'case_id': case.id, 'social_adjustment': '3', 'peer_relationships': '4',
            'academic_stress': '5', 'emotional_wellbeing': '2', 'bullying_concern': True})
        self.assertEqual((shot.social_value, shot.peer_value, shot.stress_value, shot.emotional_value, shot.highest), (3, 4, 5, 2, 5))
        blank = self.env['school.wellbeing.assessment'].with_user(self.c1).create({'student_id': self.s2.id})
        self.assertEqual(blank.highest, 1)
        self.assertEqual(case.assessment_count, 1)
        self.assertEqual(case.action_view_assessments()['domain'], [('student_id', '=', self.s1.id)])
        self.assertEqual(case.action_view_checkins()['domain'], [('student_id', '=', self.s1.id)])
        with self.assertRaises(AccessError):
            shot.with_user(self.teacher).read(['academic_stress'])

    # ---------------------------------------------------------------- settings and reminders
    def test_settings(self):
        self.assertEqual(self.env['school.wellbeing.config']._get(), self.cfg)
        self.assertIn('1098', self.cfg.helpline_text)
        self.assertEqual(self.env['school.wellbeing.config'].with_user(self.lead).action_open_settings()['res_id'], self.cfg.id)
        self.assertTrue(self.cfg.with_user(self.c1).checkin_interval_days)                               # a counsellor reads...
        with self.assertRaises(AccessError):
            self.cfg.with_user(self.c1).write({'checkin_interval_days': 1})                              # ...only the Lead changes
        self.cfg.with_user(self.lead).write({'checkin_interval_days': 14})
        self.cfg.checkin_interval_days = 7
        with self.assertRaises(AccessError):
            self.env['school.wellbeing.config'].with_user(self.teacher).search([])
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.env['school.wellbeing.config'].create({'company_id': self.env.company.id})

    def test_a_case_waiting_for_a_day_is_reminded_once(self):
        case = self._case()
        case.sudo().opened_datetime = fields.Datetime.now() - timedelta(hours=30)
        self.Case._cron_reminders()
        self.assertTrue(case.reminder_sent)
        self.assertIn('waiting', self._mail_text(self.c2))
        count = len(self._messages(self.c2))
        self.Case._cron_reminders()
        self.assertEqual(len(self._messages(self.c2)), count)

    # ---------------------------------------------------------------- the bridge to Safeguarding
    def test_share_with_safeguarding_sends_only_the_summary(self):
        officer = _user(self.env, 'wb_officer', 'school_safeguarding.group_sg_officer')
        case = self._case(self.s1, counsellor_id=self.c1.id, concern_text='Counsellor-only private wording', plan='secret plan')
        self.env['school.wellbeing.session'].with_user(self.c1).create({'case_id': case.id, 'notes': 'secret session notes'})
        self.assertIn('Share with Safeguarding', case.action_share_with_safeguarding()['name'])
        summary = 'Seen being pushed by older children at lunch on Monday.'
        wizard = self.env['school.wellbeing.share.wizard'].with_user(self.c1).create({
            'case_id': case.id, 'category': 'bullying', 'severity': 'high', 'immediate_risk': True, 'description': summary})
        wizard.action_submit()
        sg = self.env['school.safeguarding.case'].sudo().search([('name', '=', wizard.reference)])
        self.assertEqual((sg.category, sg.severity, sg.source, sg.reporter_partner_id, sg.affected_student_ids, sg.description),
                         ('bullying', 'high', 'staff', self.c1.partner_id, self.s1, summary))
        for secret in ('private wording', 'secret plan', 'secret session notes'):
            self.assertNotIn(secret, '%s %s' % (sg.description, ' '.join(sg.log_ids.mapped('text'))))      # nothing of the counselling is copied
        self.assertEqual(case.safeguarding_ref, sg.name)
        self.assertIn('Counselling notes were not copied', ' '.join(case.log_ids.mapped('text')))
        self.assertIn(sg.name, self._mail_text(officer))                                                   # the Safeguarding officers are alerted
        self.assertEqual(self.env['school.safeguarding.case'].with_user(officer).search([('id', '=', sg.id)]), sg)
        with self.assertRaises(AccessError):
            sg.with_user(self.c1).read(['description'])                                                    # a counsellor is not in the team
        with self.assertRaises(AccessError):
            case.with_user(officer).read(['concern_text'])                                                 # and the team does not read the counselling
        with self.assertRaises(AccessError):
            self.env['school.wellbeing.session'].with_user(officer).search([])
        with self.assertRaises(UserError):
            case.action_share_with_safeguarding()                                                          # once only
        with self.assertRaises(UserError):
            wizard.action_submit()

    def test_share_with_safeguarding_needs_a_summary_and_a_counsellor(self):
        case = self._case(self.s2)
        Wizard = self.env['school.wellbeing.share.wizard']
        short = Wizard.with_user(self.c1).create({'case_id': case.id, 'description': 'hmm'})
        with self.assertRaises(UserError):
            short.action_submit()
        self.assertFalse(case.safeguarding_ref)
        with self.assertRaises(AccessError):
            Wizard.with_user(self.teacher).create({'case_id': case.id, 'description': 'A long enough summary of the matter'})
        bullying = self._case(self.s3, area_ids=[(6, 0, self.area_bully.ids)])
        self.assertEqual(bullying.action_share_with_safeguarding()['context']['default_category'], 'bullying')
        self.assertEqual(case.action_share_with_safeguarding()['context']['default_category'], 'child_safety')

    def test_the_default_lead_is_only_added_when_nobody_is_lead(self):
        group = self.env.ref('school_safeguarding.group_wb_lead')
        admin = self.env.ref('base.user_admin')
        group.sudo().user_ids = [(6, 0, [self.lead.id])]
        self.env['school.wellbeing.config']._ensure_default_lead()
        self.assertNotIn(admin, group.user_ids)                                                           # somebody is Lead: leave it
        group.sudo().user_ids = [(5, 0, 0)]
        self.env['school.wellbeing.config']._ensure_default_lead()
        self.assertIn(admin, group.user_ids)                                                              # nobody: the administrator is

    def test_the_default_settings_survive_a_row_left_by_an_older_install(self):
        Config = self.env['school.wellbeing.config']
        main = self.env.ref('base.main_company')
        before = Config.search([('company_id', '=', main.id)])
        Config._ensure_default_config()                                                                    # the row is there: no error
        Config._ensure_default_config()
        self.assertEqual(Config.search_count([('company_id', '=', main.id)]), 1)
        self.assertEqual(Config.search([('company_id', '=', main.id)]), before)                           # the same row

    def test_a_reference_is_given_in_any_company_and_old_ones_are_repaired(self):
        seq = self.env.ref('school_safeguarding.seq_wb_case')
        seq.sudo().company_id = self.env.company                                                          # as the first version had it
        board = self.env['res.company'].create({'name': 'WB Second Board'})
        case = self.Case.with_company(board).sudo().create({'student_id': self.s1.id, 'company_id': board.id})
        self.assertRegex(case.name, r'^WB/\d{4}/\d{4}$')                                                   # not "New"
        stale = self.Case.sudo().create({'student_id': self.s2.id, 'name': 'New'})
        stale.name = 'New'
        self.env['school.wellbeing.config']._repair_case_references()
        self.assertRegex(stale.name, r'^WB/\d{4}/\d{4}$')
        self.assertFalse(seq.company_id)

    def test_a_second_request_to_talk_goes_into_the_open_case(self):
        Checkin = self.env['school.wellbeing.checkin']
        checkin = Checkin.create({'student_id': self.s1.id, 'status': 'need_help', 'wants_to_talk': True})
        case = checkin.case_id
        self.assertEqual(self.Case.sudo().search_count([('student_id', '=', self.s1.id)]), 1)
        again = self.Case._raise_for_student(self.s1, 'medium', 'I would like to talk', source='self', talk=True, alert=True)
        self.assertEqual(again, case)                                                                      # no second case
        self.assertEqual(self.Case.sudo().search_count([('student_id', '=', self.s1.id)]), 1)
        self.assertEqual(case.level, 'high')                                                               # never lowered
        count = len(self._messages(self.c1))
        self.Case._raise_for_student(self.s1, 'medium', 'Please, soon', source='self', talk=True, alert=True)
        self.assertEqual(len(self._messages(self.c1)), count)                                              # still waiting: no second alert
        case.with_user(self.c1).action_start_assessment()                                                  # the counsellor took it
        self.Case._raise_for_student(self.s1, 'medium', 'Still need to talk', source='self', talk=True, alert=True)
        self.assertGreater(len(self._messages(self.c1)), count)                                            # a new request is told again
        self.assertIn(case.name, self._mail_text(self.c1))
        self.assertNotIn('Asha', self._mail_text(self.c1))

    def test_the_safeguarding_and_well_being_groups_are_separate(self):
        officer = _user(self.env, 'wb_officer2', 'school_safeguarding.group_sg_officer')
        self.assertFalse(officer.has_group('school_safeguarding.group_wb_counsellor'))
        self.assertFalse(self.c1.has_group('school_safeguarding.group_sg_officer'))
        self.assertTrue(self.c1.has_group('school_safeguarding.group_sg_reporter'))                      # a counsellor may report to Safeguarding too
        self.assertTrue(self.teacher.has_group('school_safeguarding.group_sg_reporter'))                  # a teacher can raise both kinds
        self.assertTrue(self.teacher.has_group('school_safeguarding.group_wb_reporter'))


@tagged('post_install', '-at_install', 'school_safeguarding', 'school_wellbeing')
class TestWellbeingPortal(_World, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._build()
        env = cls.env
        cls.student_user = _user(env, 'wb_student1', portal=True, partner=cls.s1.partner_id, name='Asha Secret')
        cls.student2_user = _user(env, 'wb_student2', portal=True, partner=cls.s2.partner_id, name='Bala Hidden')
        cls.parent_user = _user(env, 'wb_parent1', portal=True, partner=cls.parent.partner_id, name='Parent One')
        cls.parent2_user = _user(env, 'wb_parent2', portal=True, partner=cls.parent2.partner_id, name='Parent Two')
        cls.stranger = _user(env, 'wb_stranger', portal=True)
        cls.Checkin = env['school.wellbeing.checkin']

    def _csrf(self, html):
        return re.search(r'name="csrf_token"\s+value="([^"]+)"', html).group(1)

    def _post(self, url, **data):
        data['csrf_token'] = self._csrf(self.url_open('/my/wellbeing').text) if 'csrf_token' not in data else data['csrf_token']
        return self.url_open(url, data=data)

    def _text(self, html):
        return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))

    def test_the_card_is_on_the_portal_home(self):
        self.authenticate('wb_student1', 'wb_student1')
        self.assertIn('/my/wellbeing', self.url_open('/my').text)

    def test_student_checks_in(self):
        self.authenticate('wb_student1', 'wb_student1')
        page = self.url_open('/my/wellbeing')
        self.assertEqual(page.status_code, 200)
        for text in ('How are you feeling today?', 'Good', 'Okay', 'Struggling', 'Need help', 'I would like to talk to the counsellor',
                     'It is time for your check-in', 'CHILDLINE 1098'):
            self.assertIn(text, self._text(page.text))
        self.assertNotIn('Share a concern about your child', page.text)                                  # a student, not a parent
        done = self._post('/my/wellbeing/checkin', status='okay', note='A bit tired')
        self.assertIn('Thank you for checking in', self._text(done.text))
        rows = self.Checkin.sudo().search([('student_id', '=', self.s1.id)])
        self.assertEqual((len(rows), rows.status, rows.note, rows.source), (1, 'okay', 'A bit tired', 'student'))
        again = self._post('/my/wellbeing/checkin', status='good')                                       # the same day: replaced
        rows = self.Checkin.sudo().search([('student_id', '=', self.s1.id)])
        self.assertEqual((len(rows), rows.status), (1, 'good'))
        page = self.url_open('/my/wellbeing')
        self.assertIn('You already checked in today', self._text(page.text))
        self.assertNotIn('It is time for your check-in', self._text(page.text))
        bad = self._post('/my/wellbeing/checkin', status='hacked')
        self.assertIn('Please choose how you feel', self._text(bad.text))
        self.assertEqual(self.Checkin.sudo().search_count([('student_id', '=', self.s1.id)]), 1)

    def test_need_help_from_the_portal_reaches_the_counsellor(self):
        self.authenticate('wb_student1', 'wb_student1')
        done = self._post('/my/wellbeing/checkin', status='need_help', note='Please help', wants_to_talk='on')
        self.assertIn('A counsellor has been told', self._text(done.text))
        checkin = self.Checkin.sudo().search([('student_id', '=', self.s1.id)])
        self.assertTrue(checkin.wants_to_talk)
        self.assertEqual((checkin.case_id.level, checkin.case_id.wants_to_talk), ('high', True))
        mails = ' '.join('%s %s' % (m.subject, m.body) for m in self.env['mail.message'].sudo().search(
            [('partner_ids', 'in', self.c1.partner_id.ids)]))
        self.assertIn('URGENT', mails)
        self.assertNotIn('Please help', mails)

    def test_struggling_does_not_promise_that_a_counsellor_was_told(self):
        self.authenticate('wb_student1', 'wb_student1')
        done = self._text(self._post('/my/wellbeing/checkin', status='struggling').text)
        self.assertNotIn('A counsellor has been told', done)
        self.assertIn('I would like to talk', done)
        self.assertFalse(self.Checkin.sudo().search([('student_id', '=', self.s1.id)]).case_id)         # one day alone: no case

    def test_a_student_sees_only_his_own_history(self):
        self.Checkin.create({'student_id': self.s2.id, 'status': 'struggling', 'note': 'Bala private note'})
        self.Checkin.create({'student_id': self.s1.id, 'status': 'good', 'checkin_date': fields.Date.today() - timedelta(days=1)})
        self.authenticate('wb_student1', 'wb_student1')
        text = self._text(self.url_open('/my/wellbeing').text)
        self.assertIn('My last check-ins', text)
        self.assertIn('Good', text)
        self.assertNotIn('Bala', text)
        self.assertNotIn('private note', text)

    def test_the_student_asks_to_talk(self):
        self.authenticate('wb_student1', 'wb_student1')
        done = self._post('/my/wellbeing/talk', reason='I am worried about exams')
        self.assertIn('Your request was sent to the school counsellor', self._text(done.text))
        case = self.Case.sudo().search([('student_id', '=', self.s1.id)])
        self.assertEqual((len(case), case.source, case.wants_to_talk, case.state), (1, 'self', True, 'new'))
        self.assertIn('exams', case.concern_text)
        self.assertTrue(case.area_ids)
        self._post('/my/wellbeing/talk', reason='again')                                                 # still waiting: no duplicate
        self.assertEqual(self.Case.sudo().search_count([('student_id', '=', self.s1.id)]), 1)

    def test_a_case_from_a_student_of_another_company_has_a_reference_and_one_case(self):
        board = self.env['res.company'].create({'name': 'WB Portal Board'})
        self.s3.partner_id.company_id = board
        self.env['res.users'].create({'name': 'wb_student3', 'login': 'wb_student3', 'password': 'wb_student3',
                                      'partner_id': self.s3.partner_id.id, 'company_id': board.id, 'company_ids': [(6, 0, [board.id])],
                                      'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])]})
        self.authenticate('wb_student3', 'wb_student3')
        self._post('/my/wellbeing/checkin', status='need_help', wants_to_talk='on')
        self._post('/my/wellbeing/talk', reason='Please meet me')                                         # the button too
        cases = self.Case.sudo().search([('student_id', '=', self.s3.id)])
        self.assertEqual(len(cases), 1)                                                                    # one open case, not two
        self.assertRegex(cases.name, r'^WB/\d{4}/\d{4}$')                                                   # a real reference in any company
        self.assertEqual((cases.company_id, cases.level, cases.wants_to_talk), (board, 'high', True))
        self.assertIn('Please meet me', ' '.join(cases.log_ids.mapped('text')))

    def test_a_parent_shares_a_concern_but_sees_no_check_ins(self):
        self.Checkin.create({'student_id': self.s1.id, 'status': 'struggling', 'note': 'child secret note'})
        self.authenticate('wb_parent1', 'wb_parent1')
        page = self.url_open('/my/wellbeing')
        text = self._text(page.text)
        self.assertIn('Share a concern about your child', text)
        self.assertNotIn('How are you feeling today?', text)                                             # parents do not check in
        self.assertNotIn('My last check-ins', text)
        self.assertNotIn('child secret note', text)
        done = self._post('/my/wellbeing/concern', child_id=str(self.s1.id), area_id=str(self.area_bully.id), level='high',
                          description='He does not want to come to school and says he is teased')
        self.assertIn('Your message was sent to the school counsellor', self._text(done.text))
        case = self.Case.sudo().search([('student_id', '=', self.s1.id), ('source', '=', 'parent')])
        self.assertEqual((len(case), case.level, case.reporter_partner_id, case.area_ids), (1, 'high', self.parent_user.partner_id, self.area_bully))
        self.assertIn('teased', case.concern_text)

    def test_a_parent_cannot_write_about_another_childs_case(self):
        self.authenticate('wb_parent1', 'wb_parent1')
        wrong = self._post('/my/wellbeing/concern', child_id=str(self.s2.id), description='Something about a child that is not mine')
        self.assertIn('Please choose your child', self._text(wrong.text))
        short = self._post('/my/wellbeing/concern', child_id=str(self.s1.id), description='short')
        self.assertIn('Please choose your child', self._text(short.text))
        junk = self._post('/my/wellbeing/concern', child_id='abc', description='A long enough description here')
        self.assertIn('Please choose your child', self._text(junk.text))
        self.assertFalse(self.Case.sudo().search([('source', '=', 'parent')]))

    def test_a_parent_is_limited_to_five_messages_an_hour(self):
        self.authenticate('wb_parent1', 'wb_parent1')
        for n in range(6):
            self._post('/my/wellbeing/concern', child_id=str(self.s1.id), description='Concern number %s about my child' % n)
        self.assertEqual(self.Case.sudo().search_count([('source', '=', 'parent')]), 5)

    def test_a_parent_cannot_check_in_for_the_child(self):
        self.authenticate('wb_parent1', 'wb_parent1')
        self._post('/my/wellbeing/checkin', status='good')
        self.assertFalse(self.Checkin.sudo().search([('student_id', '=', self.s1.id)]))
        self._post('/my/wellbeing/talk', reason='x')
        self.assertFalse(self.Case.sudo().search([('source', '=', 'self')]))

    def test_somebody_not_linked_to_a_student_gets_a_clear_page(self):
        self.authenticate('wb_stranger', 'wb_stranger')
        page = self.url_open('/my/wellbeing')
        self.assertEqual(page.status_code, 200)
        self.assertIn('You are not linked to a student', self._text(page.text))
        self.assertNotIn('How are you feeling today?', page.text)

    def test_the_counsellors_notes_never_reach_the_portal(self):
        case = self.Case.with_user(self.c1).create({'student_id': self.s1.id, 'concern_text': 'Counsellor-only wording',
                                                    'plan': 'secret plan', 'assessment_notes': 'secret assessment'})
        self.env['school.wellbeing.session'].with_user(self.c1).create({'case_id': case.id, 'notes': 'secret session notes'})
        for login in ('wb_student1', 'wb_parent1'):
            self.authenticate(login, login)
            text = self._text(self.url_open('/my/wellbeing').text)
            for secret in ('Counsellor-only wording', 'secret plan', 'secret assessment', 'secret session notes'):
                self.assertNotIn(secret, text, login)

    def test_counsellor_without_teacher_group_can_open_a_checkin(self):
        """Bug 1.1.2: opening a check-in form gave 'not allowed to access school.student' for a plain counsellor."""
        checkin = self.env['school.wellbeing.checkin'].create({'student_id': self.s1.id, 'status': 'need_help'})
        self.assertFalse(self.c1.has_group('ad_school_management.group_school_teacher'))
        row = checkin.with_user(self.c1).read(['student_id', 'class_id', 'status'])[0]
        self.assertEqual(row['student_id'][0], self.s1.id)
        student = self.s1.with_user(self.c1)
        self.assertTrue(student.read(['name', 'class_id']))
        self.assertTrue(student.class_id.name)
        with self.assertRaises(AccessError):
            student.write({'name': 'Changed by counsellor'})
        with self.assertRaises(AccessError):
            student.unlink()

    def test_counsellor_who_is_also_a_teacher_of_other_classes_can_read_the_student(self):
        """The class-wise teacher rule must not hide a student from a counsellor who also has the Teacher group."""
        both = _user(self.env, 'wb_c_teacher', 'school_safeguarding.group_wb_counsellor', 'ad_school_management.group_school_teacher')
        self.assertTrue(self.s1.with_user(both).read(['name']))
        with self.assertRaises(AccessError):
            self.s1.with_user(both).write({'name': 'Changed'})

    def test_calendar_counts_the_session_length_in_hours(self):
        """Bug 1.1.3: the calendar read the minutes as hours (30 minutes was drawn as 30 hours)."""
        case = self.Case.with_user(self.c1).create({'student_id': self.s1.id, 'concern_text': 'x'})
        session = self.env['school.wellbeing.session'].with_user(self.c1).create(
            {'case_id': case.id, 'duration_minutes': 30, 'session_date': '2026-10-15 07:26:53'})
        self.assertAlmostEqual(session.duration_hours, 0.5)
        calendar_view = self.env.ref('school_safeguarding.view_wb_session_calendar')
        self.assertIn('date_delay="duration_hours"', calendar_view.arch_db)
        session.duration_hours = 0.25                                   # resized in the calendar
        self.assertEqual(session.duration_minutes, 15)

    def test_session_title_uses_the_user_time_without_seconds(self):
        case = self.Case.with_user(self.c1).create({'student_id': self.s1.id, 'concern_text': 'x'})
        session = self.env['school.wellbeing.session'].with_user(self.c1).create(
            {'case_id': case.id, 'session_date': '2026-10-15 07:26:53'})
        title = session.with_context(tz='Asia/Kolkata').display_name
        self.assertTrue(title.endswith('15 Oct 2026 12:56'), title)
