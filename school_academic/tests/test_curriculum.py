# -*- coding: utf-8 -*-
from lxml import etree

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import HttpCase, TransactionCase, tagged


def _base(cls):
    env = cls.env
    cls.klass = env['school.class'].create({'name': 'CU Class 1', 'code': 'CU1'})
    cls.klass2 = env['school.class'].create({'name': 'CU Class 2', 'code': 'CU2'})
    cls.year = env['school.academic.year'].create(
        {'name': '2026-27', 'code': 'CY26', 'date_start': '2026-06-01', 'date_end': '2027-03-31'})
    cls.year2 = env['school.academic.year'].create(
        {'name': '2027-28', 'code': 'CY27', 'date_start': '2027-06-01', 'date_end': '2028-03-31'})
    cls.maths = env['school.subject'].create(
        {'name': 'CU Maths', 'code': 'CUM', 'class_ids': [(6, 0, cls.klass.ids)]})
    cls.english = env['school.subject'].create(
        {'name': 'CU English', 'code': 'CUE', 'class_ids': [(6, 0, cls.klass.ids)]})
    cls.only_class2 = env['school.subject'].create(
        {'name': 'CU Science', 'code': 'CUS', 'class_ids': [(6, 0, cls.klass2.ids)]})
    cls.free_subject = env['school.subject'].create({'name': 'CU Art', 'code': 'CUA'})   # no class restriction


def _make(cls, **kw):
    vals = {'name': 'Class 1 Curriculum', 'academic_year_id': cls.year.id, 'class_id': cls.klass.id,
            'line_ids': [(0, 0, {'subject_id': cls.maths.id, 'periods_per_week': 6}),
                         (0, 0, {'subject_id': cls.english.id, 'periods_per_week': 5, 'subject_type': 'core'}),
                         (0, 0, {'subject_id': cls.free_subject.id, 'periods_per_week': 1,
                                 'subject_type': 'co_scholastic'})]}
    vals.update(kw)
    return cls.env['school.curriculum'].create(vals)


@tagged('post_install', '-at_install', 'school_academic')
class TestCurriculum(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _base(cls)
        base_user = cls.env.ref('base.group_user')
        cls.teacher = cls.env['res.users'].create({
            'name': 'CU Teacher', 'login': 'cu_teacher',
            'group_ids': [(6, 0, [base_user.id, cls.env.ref('ad_school_management.group_school_teacher').id])]})
        cls.principal = cls.env['res.users'].create({
            'name': 'CU Principal', 'login': 'cu_principal',
            'group_ids': [(6, 0, [base_user.id, cls.env.ref('ad_school_management.group_school_principal').id])]})

    # ---- totals -------------------------------------------------------------
    def test_totals_and_annual_periods(self):
        cur = _make(self)
        self.assertEqual(cur.subject_count, 3)
        self.assertEqual(cur.line_ids[0].display_name, 'CU Maths (Class 1 Curriculum)')   # not "school.curriculum.line,1"
        self.assertEqual(cur.periods_per_week, 12)
        by_subject = {l.subject_id: l.total_periods for l in cur.line_ids}
        self.assertEqual(by_subject[self.maths], 6 * 36)
        self.assertEqual(cur.total_periods, 12 * 36)
        cur.teaching_weeks = 40                               # recomputes the annual periods
        self.assertEqual(cur.total_periods, 12 * 40)

    def test_annual_periods_can_be_overridden(self):
        cur = _make(self)
        line = cur.line_ids.filtered(lambda l: l.subject_id == self.maths)
        line.total_periods = 200
        self.assertEqual(line.total_periods, 200)
        self.assertEqual(cur.total_periods, 200 + 5 * 36 + 1 * 36)

    # ---- validation --------------------------------------------------------
    def test_one_line_per_subject(self):
        cur = _make(self)
        with self.assertRaises(Exception):
            cur.write({'line_ids': [(0, 0, {'subject_id': self.maths.id})]})

    def test_subject_must_belong_to_the_class(self):
        with self.assertRaises(ValidationError):
            _make(self, line_ids=[(0, 0, {'subject_id': self.only_class2.id})])

    def test_negative_periods_and_weeks_are_refused(self):
        cur = _make(self)
        with self.assertRaises(ValidationError):
            cur.line_ids[0].periods_per_week = -1
        with self.assertRaises(ValidationError):
            cur.teaching_weeks = 0

    # ---- publishing ----------------------------------------------------------
    def test_publish_needs_subjects(self):
        empty = self.env['school.curriculum'].create({
            'name': 'Empty', 'academic_year_id': self.year.id, 'class_id': self.klass.id})
        with self.assertRaises(UserError):
            empty.action_publish()

    def test_only_principal_or_admin_can_publish(self):
        cur = _make(self)
        with self.assertRaises(AccessError):
            cur.with_user(self.teacher).action_publish()
        self.assertEqual(cur.state, 'draft')
        cur.with_user(self.principal).action_publish()
        self.assertEqual(cur.state, 'published')
        self.assertEqual(cur.approved_by, self.principal)
        self.assertTrue(cur.approved_datetime)

    def test_one_published_curriculum_per_class_and_year(self):
        first = _make(self)
        first.action_publish()
        second = _make(self, name='Another')
        with self.assertRaises(UserError):
            second.action_publish()
        first.action_archive_curriculum()
        self.assertEqual(first.state, 'archived')
        second.action_publish()                                # allowed once the first is archived
        self.assertEqual(second.state, 'published')
        other_year = _make(self, academic_year_id=self.year2.id)
        other_year.action_publish()                            # different year is fine

    def test_back_to_draft(self):
        cur = _make(self)
        cur.action_publish()
        cur.action_set_draft()
        self.assertEqual((cur.state, bool(cur.approved_by)), ('draft', False))

    # ---- teacher rights ---------------------------------------------------------
    def test_teacher_edits_draft_but_not_published(self):
        cur = _make(self)
        as_teacher = cur.with_user(self.teacher)
        as_teacher.write({'description': 'Draft text'})               # draft: fine
        as_teacher.line_ids[0].write({'periods_per_week': 7})
        cur.action_publish()
        with self.assertRaises(AccessError):
            as_teacher.write({'description': 'changed'})
        with self.assertRaises(AccessError):
            as_teacher.line_ids[0].write({'periods_per_week': 3})
        with self.assertRaises(AccessError):
            self.env['school.curriculum.line'].with_user(self.teacher).create(
                {'curriculum_id': cur.id, 'subject_id': self.only_class2.id})
        with self.assertRaises(AccessError):
            as_teacher.unlink()
        cur.with_user(self.principal).write({'description': 'principal may edit'})   # approvers can

    def test_teacher_cannot_publish_by_writing_state(self):
        cur = _make(self)
        with self.assertRaises(Exception):
            cur.with_user(self.teacher).write({'state': 'published'})
            cur.with_user(self.teacher).action_publish()
        self.assertEqual(cur.state, 'draft')

    # ---- copy to next year --------------------------------------------------------
    def test_copy_to_another_year(self):
        cur = _make(self, description='Overview text')
        cur.action_publish()
        wizard = self.env['school.curriculum.copy.wizard'].create(
            {'curriculum_id': cur.id, 'target_year_id': self.year2.id})
        action = wizard.action_copy()
        new = self.env['school.curriculum'].browse(action['res_id'])
        self.assertEqual(new.state, 'draft')                    # copies always start as draft
        self.assertEqual(new.academic_year_id, self.year2)
        self.assertEqual(new.class_id, self.klass)
        self.assertEqual(new.description, 'Overview text')
        self.assertEqual(sorted(new.line_ids.mapped('subject_id').ids), sorted(cur.line_ids.mapped('subject_id').ids))
        self.assertEqual(new.total_periods, cur.total_periods)
        self.assertNotEqual(new, cur)

    def test_copy_to_same_year_is_refused(self):
        cur = _make(self)
        with self.assertRaises(UserError):
            self.env['school.curriculum.copy.wizard'].create(
                {'curriculum_id': cur.id, 'target_year_id': self.year.id}).action_copy()

    def test_periods_overview_report(self):
        cur = _make(self)
        cur.action_publish()
        rows = self.env['school.curriculum.line']._read_group(
            [('curriculum_state', '=', 'published'), ('class_id', '=', self.klass.id)],
            ['subject_id'], ['periods_per_week:sum', 'total_periods:sum'])
        self.assertEqual({s.id: (p, t) for s, p, t in rows}[self.maths.id], (6, 216))


    # ---- subject teacher is told -------------------------------------------------
    def _teacher_record(self, name, user):
        return self.env['school.teacher'].create({'name': name, 'user_id': user.id})

    def _messages_for(self, cur, user):
        return cur.message_ids.filtered(lambda m: user.partner_id in m.partner_ids)

    def test_assigned_teacher_is_notified_when_published(self):
        dhirisha = self._teacher_record('Dhirisha', self.teacher)
        no_user = self.env['school.teacher'].create({'name': 'No Login Teacher'})     # has no Odoo user
        cur = _make(self, line_ids=[
            (0, 0, {'subject_id': self.maths.id, 'periods_per_week': 5, 'teacher_id': dhirisha.id}),
            (0, 0, {'subject_id': self.english.id, 'periods_per_week': 4, 'teacher_id': no_user.id}),
            (0, 0, {'subject_id': self.free_subject.id, 'periods_per_week': 1})])
        self.assertFalse(self._messages_for(cur, self.teacher))        # draft: nothing sent yet
        cur.action_publish()
        msgs = self._messages_for(cur, self.teacher)
        self.assertEqual(len(msgs), 1)
        self.assertIn('CU Maths', msgs.body)
        self.assertIn('5', msgs.body)
        self.assertIn('<b>CU Maths</b>', msgs.body)            # real HTML ...
        self.assertNotIn('&lt;', msgs.body)                      # ... not escaped tags shown as text
        self.assertNotIn('CU English', msgs.body)                       # that teacher is someone else
        self.assertNotIn('CU Art', msgs.body)

    def test_my_subjects_shows_only_my_published_lines(self):
        dhirisha = self._teacher_record('Dhirisha', self.teacher)
        cur = _make(self, line_ids=[
            (0, 0, {'subject_id': self.maths.id, 'teacher_id': dhirisha.id}),
            (0, 0, {'subject_id': self.english.id})])
        Line = self.env['school.curriculum.line']
        domain = [('teacher_user_id', '=', self.teacher.id), ('curriculum_state', '=', 'published')]
        self.assertFalse(Line.search(domain))                           # draft is not shown yet
        cur.action_publish()
        self.assertEqual(Line.search(domain).mapped('subject_id'), self.maths)
        # the same search the menu does, run AS the teacher (no HR access needed)
        as_teacher = Line.with_user(self.teacher).search(
            [('teacher_user_id', '=', self.teacher.id), ('curriculum_state', '=', 'published')])
        self.assertEqual(as_teacher.mapped('subject_id'), self.maths)
        self.assertFalse(Line.search([('teacher_user_id', '=', self.principal.id)]))   # someone else sees none

    def test_new_teacher_is_notified_when_changed_after_publish(self):
        first = self._teacher_record('Dhirisha', self.teacher)
        second = self._teacher_record('Second Teacher', self.principal)
        cur = _make(self, line_ids=[(0, 0, {'subject_id': self.maths.id, 'teacher_id': first.id})])
        cur.action_publish()
        self.assertFalse(self._messages_for(cur, self.principal))
        line = cur.line_ids
        line.with_user(self.principal).write({'periods_per_week': 7})          # other change: no message
        self.assertFalse(self._messages_for(cur, self.principal))
        line.with_user(self.principal).write({'teacher_id': second.id})        # teacher changed
        self.assertEqual(len(self._messages_for(cur, self.principal)), 1)


    # ---- companies: "own branch + shared main school" ---------------------------
    def test_branch_user_sees_main_school_curriculum_but_not_other_schools(self):
        Company = self.env['res.company']
        main = Company.create({'name': 'CU Main School'})
        branch = Company.create({'name': 'CU Branch', 'parent_id': main.id})
        other = Company.create({'name': 'CU Other Board'})
        teacher_group = self.env.ref('ad_school_management.group_school_teacher')
        branch_user = self.env['res.users'].create({
            'name': 'CU Branch Teacher', 'login': 'cu_branch', 'company_id': branch.id,
            'company_ids': [(6, 0, [branch.id])],
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id, teacher_group.id])]})
        dhirisha = self.env['school.teacher'].create({'name': 'Dhirisha', 'user_id': branch_user.id})
        in_main = _make(self, name='Main school curriculum', company_id=main.id, line_ids=[
            (0, 0, {'subject_id': self.maths.id, 'teacher_id': dhirisha.id})])
        in_other = _make(self, name='Other board curriculum', company_id=other.id,
                         line_ids=[(0, 0, {'subject_id': self.english.id, 'teacher_id': dhirisha.id})])
        in_main.action_publish()
        in_other.action_publish()
        ctx = {'allowed_company_ids': [branch.id]}
        Cur = self.env['school.curriculum'].with_user(branch_user).with_context(**ctx)
        Line = self.env['school.curriculum.line'].with_user(branch_user).with_context(**ctx)
        self.assertEqual(Cur.search([('id', 'in', (in_main | in_other).ids)]), in_main)
        mine = Line.search([('teacher_user_id', '=', branch_user.id), ('curriculum_state', '=', 'published')])
        self.assertEqual(mine.mapped('subject_id'), self.maths)       # only the main-school line


    # ---- teacher is filled in, year dates, topic plan ------------------------------------
    def _teacher_user_with_record(self, login):
        user = self.env['res.users'].create({
            'name': login, 'login': login,
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('ad_school_management.group_school_teacher').id])]})
        return user, self.env['school.teacher'].create({'name': 'Teacher ' + login, 'user_id': user.id})

    def test_logged_in_teacher_is_filled_in(self):
        user, teacher = self._teacher_user_with_record('cu_dhirisha')
        cur = self.env['school.curriculum'].with_user(user).create({
            'name': 'Mine', 'academic_year_id': self.year.id, 'class_id': self.klass.id})
        self.assertEqual((cur.teacher_id, cur.teacher_user_id), (teacher, user))
        self.assertEqual(cur.with_user(self.principal).teacher_id.display_name, 'Teacher cu_dhirisha')
        # a login without a teacher record (admin) leaves it empty; it can be chosen by hand
        by_admin = _make(self)
        self.assertFalse(by_admin.teacher_id)
        by_admin.teacher_id = teacher
        self.assertEqual(by_admin.teacher_user_id, user)

    def test_academic_year_dates_are_shown(self):
        cur = _make(self)
        self.assertEqual((str(cur.year_start), str(cur.year_end)), ('2026-06-01', '2027-03-31'))

    def _plan_vals(self, cur, **kw):
        vals = {'curriculum_id': cur.id, 'subject_id': self.maths.id, 'topic': 'Numbers to 100',
                'description': 'Counting and ordering', 'date_start': '2026-07-01', 'date_end': '2026-07-31'}
        vals.update(kw)
        return vals

    def test_topic_plan_rows(self):
        cur = _make(self)
        sec = self.env['school.section'].create({'name': 'A', 'class_id': self.klass.id, 'capacity': 30})
        plan = self.env['school.curriculum.plan'].create(self._plan_vals(cur, section_id=sec.id))
        self.assertEqual((plan.class_id, plan.academic_year_id, plan.section_id), (self.klass, self.year, sec))
        self.assertEqual(plan.display_name, 'Numbers to 100 (CU Maths)')
        self.assertEqual(cur.plan_count, 1)

    def test_topic_plan_dates_and_links_are_checked(self):
        cur = _make(self)
        Plan = self.env['school.curriculum.plan']
        with self.assertRaises(ValidationError):                                         # end before start
            Plan.create(self._plan_vals(cur, date_start='2026-08-10', date_end='2026-08-01'))
        with self.assertRaises(ValidationError):                                         # before the year starts
            Plan.create(self._plan_vals(cur, date_start='2026-05-01'))
        with self.assertRaises(ValidationError):                                         # after the year ends
            Plan.create(self._plan_vals(cur, date_end='2027-04-15'))
        with self.assertRaises(ValidationError):                                         # subject not taught in this class
            Plan.create(self._plan_vals(cur, subject_id=self.only_class2.id))
        other_sec = self.env['school.section'].create({'name': 'Z', 'class_id': self.klass2.id, 'capacity': 30})
        with self.assertRaises(ValidationError):                                         # section of another class
            Plan.create(self._plan_vals(cur, section_id=other_sec.id))
        Plan.create(self._plan_vals(cur, date_start=False, date_end=False))              # dates are optional

    def test_a_topic_of_a_new_subject_adds_the_subject_to_the_periods_tab(self):
        extra = self.env['school.subject'].create(
            {'name': 'CU Drawing', 'code': 'CUD', 'class_ids': [(6, 0, self.klass.ids)]})
        cur = _make(self)
        self.assertNotIn(extra, cur.line_ids.mapped('subject_id'))
        count_before = cur.subject_count
        plan = self.env['school.curriculum.plan'].create(self._plan_vals(cur, subject_id=extra.id, topic='Lines'))
        line = cur.line_ids.filtered(lambda l: l.subject_id == extra)
        self.assertEqual((len(line), line.periods_per_week, line.total_periods), (1, 0.0, 0))
        self.assertEqual(cur.subject_count, count_before + 1)
        self.env['school.curriculum.plan'].create(self._plan_vals(cur, subject_id=extra.id, topic='Shapes'))
        self.assertEqual(len(cur.line_ids.filtered(lambda l: l.subject_id == extra)), 1)      # not added twice
        self.assertEqual(len(cur.plan_ids.filtered(lambda p: p.subject_id == extra)), 2)      # many topics, one subject
        plan.subject_id = self.free_subject                                                    # changing the subject too
        self.assertIn(self.free_subject, cur.line_ids.mapped('subject_id'))

    def test_topic_plan_follows_the_curriculum_lock(self):
        cur = _make(self)
        Plan = self.env['school.curriculum.plan']
        plan = Plan.with_user(self.teacher).create(self._plan_vals(cur))                 # draft: teacher may
        plan.with_user(self.teacher).write({'topic': 'Numbers to 200'})
        cur.action_publish()
        with self.assertRaises(AccessError):
            plan.with_user(self.teacher).write({'topic': 'changed'})
        with self.assertRaises(AccessError):
            Plan.with_user(self.teacher).create(self._plan_vals(cur, topic='Late topic'))
        with self.assertRaises(AccessError):
            plan.with_user(self.teacher).unlink()
        Plan.with_user(self.principal).create(self._plan_vals(cur, topic='Principal adds'))

    def test_copy_to_next_year_keeps_the_topics_but_not_the_dates(self):
        user, teacher = self._teacher_user_with_record('cu_copier')
        cur = _make(self, teacher_id=teacher.id)
        self.env['school.curriculum.plan'].create(self._plan_vals(cur))
        new = cur._copy_to_year(self.year2)
        self.assertEqual(new.teacher_id, teacher)
        self.assertEqual(new.plan_ids.mapped('topic'), ['Numbers to 100'])
        self.assertEqual((new.plan_ids.date_start, new.plan_ids.date_end), (False, False))
        self.assertEqual(new.plan_ids.description, 'Counting and ordering')


    # ---- status of every topic -> the curriculum becomes Done -------------------------------
    def _published_with_two_topics(self):
        """Curriculum prepared by A, maths taught by B, english has no teacher; C is unrelated."""
        user_a, teacher_a = self._teacher_user_with_record('cu_st_a')
        user_b, teacher_b = self._teacher_user_with_record('cu_st_b')
        user_c, _teacher_c = self._teacher_user_with_record('cu_st_c')
        cur = _make(self, teacher_id=teacher_a.id, line_ids=[
            (0, 0, {'subject_id': self.maths.id, 'periods_per_week': 6, 'teacher_id': teacher_b.id}),
            (0, 0, {'subject_id': self.english.id, 'periods_per_week': 5})])
        Plan = self.env['school.curriculum.plan']
        maths = Plan.create(self._plan_vals(cur, topic='Numbers'))
        english = Plan.create(self._plan_vals(cur, subject_id=self.english.id, topic='Reading'))
        cur.action_publish()
        return cur, maths, english, user_a, user_b, user_c

    def test_status_dropdown_default_and_values(self):
        cur = _make(self)
        plan = self.env['school.curriculum.plan'].create(self._plan_vals(cur))
        self.assertEqual(plan.status, 'pending')
        self.assertEqual([k for k, _v in plan._fields['status'].selection], ['pending', 'in_progress', 'completed'])

    def test_all_topics_completed_makes_the_curriculum_done(self):
        cur, maths, english, user_a, user_b, _user_c = self._published_with_two_topics()
        self.assertEqual((cur.state, cur.plan_count, cur.plan_done_count, cur.plan_progress), ('published', 2, 0, 0.0))
        maths.with_user(user_b).write({'status': 'in_progress'})
        maths.with_user(user_b).write({'status': 'completed'})
        self.assertEqual((cur.state, cur.plan_done_count, cur.plan_progress), ('published', 1, 50.0))
        english.with_user(user_a).write({'status': 'completed'})
        self.assertEqual((cur.state, cur.plan_progress), ('done', 100.0))
        english.with_user(user_a).write({'status': 'in_progress'})                     # one topic is not finished again
        self.assertEqual(cur.state, 'published')
        english.with_user(user_a).write({'status': 'completed'})
        self.assertEqual(cur.state, 'done')

    def test_new_topic_in_a_done_curriculum_reopens_it_and_empty_plan_never_finishes(self):
        cur, maths, english, user_a, user_b, _user_c = self._published_with_two_topics()
        (maths | english).write({'status': 'completed'})
        self.assertEqual(cur.state, 'done')
        self.env['school.curriculum.plan'].with_user(self.principal).create(self._plan_vals(cur, topic='Extra'))
        self.assertEqual(cur.state, 'published')                                       # a pending topic is back
        empty = _make(self, academic_year_id=self.year2.id)
        empty.action_publish()
        self.assertEqual((empty.state, empty.plan_progress), ('published', 0.0))      # no topics: never "done"

    def test_done_notifies_the_principal_and_the_curriculum_teacher(self):
        cur, maths, english, user_a, user_b, _user_c = self._published_with_two_topics()
        (maths | english).write({'status': 'completed'})
        for user in (self.principal, user_a):
            told = cur.message_ids.filtered(lambda m, u=user: u.partner_id in m.partner_ids and 'Done' in (m.body or ''))
            self.assertEqual(len(told), 1)
            self.assertNotIn('&lt;', told.body)

    def test_who_may_change_the_status_after_publishing(self):
        cur, maths, english, user_a, user_b, user_c = self._published_with_two_topics()
        maths.with_user(user_b).write({'status': 'in_progress'})                       # teacher of maths
        english.with_user(user_a).write({'status': 'in_progress'})                     # prepared the curriculum
        maths.with_user(self.principal).write({'status': 'completed'})                 # principal
        with self.assertRaises(AccessError):                                           # unrelated teacher
            maths.with_user(user_c).write({'status': 'completed'})
        with self.assertRaises(AccessError):                                           # teacher of maths, but this is english
            english.with_user(user_b).write({'status': 'completed'})
        with self.assertRaises(AccessError):                                           # the structure stays locked
            maths.with_user(user_b).write({'topic': 'Renamed'})
        with self.assertRaises(AccessError):
            maths.with_user(user_b).write({'topic': 'Renamed', 'status': 'completed'})
        with self.assertRaises(AccessError):
            maths.with_user(user_b).write({'date_end': '2026-12-01'})
        cur.action_archive_curriculum()
        with self.assertRaises(AccessError):
            english.with_user(user_a).write({'status': 'completed'})

    def test_curriculum_rows_are_editable_for_the_principal_after_publishing(self):
        cur = _make(self)
        plan = self.env['school.curriculum.plan'].create(self._plan_vals(cur))
        self.assertTrue(cur.with_user(self.teacher).can_edit_structure)
        cur.action_publish()
        self.assertFalse(cur.with_user(self.teacher).can_edit_structure)
        self.assertTrue(cur.with_user(self.principal).can_edit_structure)
        plan.with_user(self.principal).write({'topic': 'Typed by the principal'})
        self.assertEqual(plan.topic, 'Typed by the principal')
        arch = self.env['school.curriculum'].get_view(view_type='form')['arch']
        node = etree.fromstring(arch.encode()).xpath("//field[@name='plan_ids']/list/field[@name='topic']")[0]
        self.assertEqual(node.get('readonly'), 'not parent.can_edit_structure')

    def test_status_can_be_set_while_the_curriculum_is_a_draft(self):
        user_a, teacher_a = self._teacher_user_with_record('cu_dr_a')
        cur = _make(self, teacher_id=teacher_a.id)
        plan = self.env['school.curriculum.plan'].create(self._plan_vals(cur))
        plan.with_user(user_a).write({'status': 'in_progress'})
        self.assertEqual((plan.status, cur.state), ('in_progress', 'draft'))           # draft stays draft

    def test_a_done_curriculum_is_still_the_published_one(self):
        cur, maths, english, user_a, user_b, _user_c = self._published_with_two_topics()
        (maths | english).write({'status': 'completed'})
        other = _make(self, name='Another for the same class and year')
        with self.assertRaises(UserError):                                              # only one active per class / year
            other.action_publish()
        cur.action_create_syllabus_drafts()                                             # still allowed when done
        self.assertTrue(self.env['school.syllabus'].search([('class_id', '=', self.klass.id)]))
        syllabus = self.env['school.syllabus'].search([('subject_id', '=', self.maths.id)], limit=1)
        self.assertEqual(syllabus.curriculum_line_id.curriculum_id, cur)                # periods link to the done curriculum
        cur.action_set_draft()                                                          # principal can reopen it
        self.assertEqual(cur.state, 'draft')


    # ---- the class is chosen in the first topic row (not in the header) -------------------------
    def test_first_topic_row_decides_the_class_of_the_curriculum(self):
        cur = self.env['school.curriculum'].create({'name': 'No class yet', 'academic_year_id': self.year.id})
        self.assertFalse(cur.class_id)
        row = self.env['school.curriculum.plan'].create({
            'curriculum_id': cur.id, 'class_id': self.klass.id, 'subject_id': self.maths.id, 'topic': 'First topic'})
        self.assertEqual((cur.class_id, row.class_id), (self.klass, self.klass))
        self.assertEqual(cur.line_ids.subject_id, self.maths)                           # its subject was added too
        again = self.env['school.curriculum.plan'].create({                             # no class given: takes the curriculum's
            'curriculum_id': cur.id, 'subject_id': self.maths.id, 'topic': 'Second topic'})
        self.assertEqual(again.class_id, self.klass)

    def test_all_rows_of_a_curriculum_are_for_the_same_class(self):
        cur = _make(self)
        with self.assertRaises(ValidationError) as ctx:
            self.env['school.curriculum.plan'].create({
                'curriculum_id': cur.id, 'class_id': self.klass2.id, 'subject_id': self.only_class2.id, 'topic': 'Wrong class'})
        self.assertIn(self.klass.name, str(ctx.exception.args[0]))
        with self.assertRaises(ValidationError):                                         # the section must match the row class
            other_sec = self.env['school.section'].create({'name': 'Q', 'class_id': self.klass2.id, 'capacity': 30})
            self.env['school.curriculum.plan'].create(self._plan_vals(cur, section_id=other_sec.id))

    def test_publish_needs_a_class_and_the_old_data_keeps_its_class(self):
        empty = self.env['school.curriculum'].create({'name': 'Empty', 'academic_year_id': self.year.id})
        with self.assertRaises(UserError):
            empty.action_publish()
        old = _make(self)                                                               # created the old way, with a class
        self.assertEqual(old.class_id, self.klass)
        old.action_publish()
        self.assertEqual(old.state, 'published')

    def test_form_no_longer_shows_those_header_fields(self):
        arch = self.env['school.curriculum'].get_view(view_type='form')['arch']
        for name in ('plan_count', 'plan_done_count', 'plan_progress'):
            self.assertNotIn('name="%s"' % name, arch)
        self.assertEqual(arch.count('name="periods_per_week"'), 1)                       # only the subject rows of Periods & Teachers
        tree = etree.fromstring(arch.encode())
        self.assertFalse(tree.xpath("//sheet/group//field[@name='class_id']"))           # no Class in the header ...
        self.assertTrue(tree.xpath("//list//field[@name='class_id']"))                   # ... it is the Class column of the rows
        for name in ('academic_year_id', 'teacher_id', 'teaching_weeks', 'subject_count', 'total_periods'):
            self.assertIn('name="%s"' % name, arch)                                      # these stay

    def test_copy_to_next_year_keeps_the_class_of_every_row(self):
        cur = _make(self)
        self.env['school.curriculum.plan'].create(self._plan_vals(cur))
        new = cur._copy_to_year(self.year2)
        self.assertEqual((new.class_id, new.plan_ids.class_id), (self.klass, self.klass))


@tagged('post_install', '-at_install', 'school_academic')
class TestCurriculumPortal(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _base(cls)
        env = cls.env
        sec = env['school.section'].create({'name': 'A', 'class_id': cls.klass.id, 'capacity': 30})
        sec2 = env['school.section'].create({'name': 'A', 'class_id': cls.klass2.id, 'capacity': 30})
        cls.student = env['school.student'].create({
            'name': 'CU Kid', 'class_id': cls.klass.id, 'section_id': sec.id, 'academic_year_id': cls.year.id})
        cls.other = env['school.student'].create({
            'name': 'CU Kid 2', 'class_id': cls.klass2.id, 'section_id': sec2.id, 'academic_year_id': cls.year.id})
        portal = env.ref('base.group_portal')
        for st, login in ((cls.student, 'cukid'), (cls.other, 'cukid2')):
            env['res.users'].create({'name': st.name, 'login': login, 'password': login,
                                     'partner_id': st.partner_id.id, 'group_ids': [(6, 0, [portal.id])]})

    def test_curriculum_and_syllabus_are_not_in_the_student_portal(self):
        cur = _make(self, name='Published Class 1')
        cur.action_publish()
        syllabus = self.env['school.syllabus'].create({
            'name': 'Maths', 'academic_year_id': self.year.id, 'class_id': self.klass.id, 'subject_id': self.maths.id,
            'unit_ids': [(0, 0, {'name': 'Unit one', 'planned_periods': 10})]})
        syllabus.action_publish()
        self.authenticate('cukid', 'cukid')
        home = self.url_open('/my')
        self.assertEqual(home.status_code, 200)
        self.assertNotIn('/my/curriculum', home.text)                                   # no Curriculum card
        self.assertNotIn('/my/syllabus', home.text)                                     # no Syllabus card
        self.assertIn('/my/diary', home.text)                                           # the class diary is still there
        for url in ('/my/curriculum', '/my/syllabus', '/my/syllabus/%s/file/1' % syllabus.id):
            self.assertEqual(self.url_open(url).status_code, 404, url)                   # not reachable by address either
        self.assertEqual(self.url_open('/my/diary').status_code, 200)
