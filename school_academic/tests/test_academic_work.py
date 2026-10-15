# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import HttpCase, TransactionCase, tagged

from .test_curriculum import _base, _make

PDF = b'%PDF-1.4\n%homework\n'
DAY = date(2026, 8, 10)                                  # inside the 2026-27 academic year of _base()


def _topic(name, periods=10):
    return (0, 0, {'name': name, 'planned_periods': periods})


def _build_syllabus(cls, subject=None, publish=True):
    """Maths syllabus with 2 units, 3 topics and 2 outcomes."""
    syl = cls.env['school.syllabus'].create({
        'name': 'AW Syllabus', 'academic_year_id': cls.year.id, 'class_id': cls.klass.id,
        'subject_id': (subject or cls.maths).id,
        'unit_ids': [(0, 0, {'name': 'Numbers', 'planned_periods': 60,
                             'topic_ids': [_topic('Counting', 30), _topic('Ordering', 30)]}),
                     (0, 0, {'name': 'Addition', 'planned_periods': 20, 'topic_ids': [_topic('Add small', 20)]})]})
    numbers = syl.unit_ids.filtered(lambda u: u.name == 'Numbers')
    cls.env['school.learning.outcome'].create([
        {'syllabus_id': syl.id, 'code': 'LO1', 'name': 'Counts objects up to 100', 'unit_id': numbers.id,
         'topic_id': numbers.topic_ids.filtered(lambda t: t.name == 'Counting').id},
        {'syllabus_id': syl.id, 'code': 'LO2', 'name': 'Adds two small numbers',
         'unit_id': syl.unit_ids.filtered(lambda u: u.name == 'Addition').id}])
    if publish:
        syl.action_publish()
    return syl


class _Common:
    @classmethod
    def _setup_people(cls):
        env = cls.env
        base_user = env.ref('base.group_user')
        teacher_group = env.ref('ad_school_management.group_school_teacher')
        cls.dhirisha_user = env['res.users'].create({
            'name': 'AW Dhirisha', 'login': 'aw_dhirisha', 'group_ids': [(6, 0, [base_user.id, teacher_group.id])]})
        cls.other_user = env['res.users'].create({
            'name': 'AW Other', 'login': 'aw_other', 'group_ids': [(6, 0, [base_user.id, teacher_group.id])]})
        cls.principal = env['res.users'].create({
            'name': 'AW Principal', 'login': 'aw_principal',
            'group_ids': [(6, 0, [base_user.id, env.ref('ad_school_management.group_school_principal').id])]})
        cls.dhirisha = env['school.teacher'].create({'name': 'Dhirisha', 'user_id': cls.dhirisha_user.id})
        cls.other_teacher = env['school.teacher'].create({'name': 'Other Teacher', 'user_id': cls.other_user.id})
        _make(cls, line_ids=[(0, 0, {'subject_id': cls.maths.id, 'periods_per_week': 6, 'teacher_id': cls.dhirisha.id}),
                             (0, 0, {'subject_id': cls.english.id, 'periods_per_week': 5})])


@tagged('post_install', '-at_install', 'school_academic')
class TestLearningOutcomes(_Common, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _base(cls)
        cls._setup_people()

    def test_outcome_links_must_match_the_syllabus(self):
        syl = _build_syllabus(self, publish=False)
        other = _build_syllabus(self, subject=self.english, publish=False)
        with self.assertRaises(ValidationError):                                      # unit of another syllabus
            self.env['school.learning.outcome'].create(
                {'syllabus_id': syl.id, 'name': 'x', 'unit_id': other.unit_ids[0].id})
        numbers = syl.unit_ids.filtered(lambda u: u.name == 'Numbers')
        addition = syl.unit_ids.filtered(lambda u: u.name == 'Addition')
        with self.assertRaises(ValidationError):                                      # topic not in that unit
            self.env['school.learning.outcome'].create(
                {'syllabus_id': syl.id, 'name': 'y', 'unit_id': addition.id, 'topic_id': numbers.topic_ids[0].id})

    def test_outcomes_follow_the_syllabus_lock(self):
        syl = _build_syllabus(self, publish=False)
        Outcome = self.env['school.learning.outcome']
        Outcome.with_user(self.dhirisha_user).create({'syllabus_id': syl.id, 'name': 'Draft outcome'})   # draft: ok
        syl.action_publish()
        with self.assertRaises(AccessError):
            Outcome.with_user(self.dhirisha_user).create({'syllabus_id': syl.id, 'name': 'Late outcome'})
        with self.assertRaises(AccessError):
            syl.outcome_ids[0].with_user(self.dhirisha_user).write({'name': 'changed'})
        Outcome.with_user(self.principal).create({'syllabus_id': syl.id, 'name': 'Principal adds'})

    def test_outcome_is_covered_only_by_a_published_diary(self):
        syl = _build_syllabus(self)
        lo1, lo2 = syl.outcome_ids.sorted('code')
        self.assertEqual((lo1.covered, lo1.taught_count), (False, 0))
        diary = self.env['school.class.diary'].with_user(self.dhirisha_user).create({
            'date': DAY, 'class_id': self.klass.id, 'subject_id': self.maths.id, 'summary': 'Counted',
            'outcome_ids': [(6, 0, lo1.ids)]})
        self.assertFalse(lo1.covered)                                                  # draft diary does not count
        diary.with_user(self.dhirisha_user).action_publish()
        self.assertEqual((lo1.covered, lo1.taught_count, lo2.covered), (True, 1, False))
        second = diary.copy({'date': DAY + timedelta(days=1)})
        second.with_user(self.dhirisha_user).action_publish()
        self.assertEqual(lo1.taught_count, 2)
        diary.with_user(self.dhirisha_user).action_unpublish()
        self.assertEqual(lo1.taught_count, 1)

    def test_outcomes_are_copied_to_the_next_year(self):
        syl = _build_syllabus(self)
        new = self.env['school.syllabus'].browse(self.env['school.syllabus.copy.wizard'].create(
            {'syllabus_id': syl.id, 'target_year_id': self.year2.id}).action_copy()['res_id'])
        self.assertEqual(sorted(new.outcome_ids.mapped('name')), sorted(syl.outcome_ids.mapped('name')))
        lo1 = new.outcome_ids.filtered(lambda o: o.code == 'LO1')
        self.assertEqual((lo1.unit_id.syllabus_id, lo1.unit_id.name, lo1.topic_id.name), (new, 'Numbers', 'Counting'))
        self.assertFalse(lo1.covered)                                                  # coverage starts again


@tagged('post_install', '-at_install', 'school_academic')
class TestLessonPlan(_Common, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _base(cls)
        cls._setup_people()
        cls.syl = _build_syllabus(cls)
        cls.Plan = cls.env['school.lesson.plan']

    def _plan(self, user=None, **kw):
        vals = {'name': 'Counting lesson', 'syllabus_id': self.syl.id, 'planned_date': DAY,
                'objectives': 'Count to 100', 'activities': 'Counting game'}
        vals.update(kw)
        return (self.Plan.with_user(user) if user else self.Plan).create(vals)

    def _messages(self, plan, user):
        return plan.message_ids.filtered(lambda m: user.partner_id in m.partner_ids)

    def test_plan_takes_class_subject_and_teacher_from_the_syllabus_and_user(self):
        plan = self._plan(user=self.dhirisha_user)
        self.assertEqual((plan.class_id, plan.subject_id, plan.teacher_id), (self.klass, self.maths, self.dhirisha))
        self.assertEqual((plan.state, plan.teacher_user_id), ('draft', self.dhirisha_user))

    def test_a_teacher_login_can_see_a_colleagues_name(self):
        """Teacher logins have no HR rights; the school module's private HR fields must not block names."""
        line = self.syl.curriculum_line_id.with_user(self.other_user)
        self.assertEqual(line.teacher_id.display_name, 'Dhirisha')                  # what a form / list shows
        plan = self._plan(user=self.dhirisha_user)
        self.assertEqual(plan.with_user(self.other_user).teacher_id.display_name, 'Dhirisha')
        self.assertEqual(plan.with_user(self.other_user).read(['teacher_id'])[0]['teacher_id'][1], 'Dhirisha')

    def test_submit_approve_flow_and_notifications(self):
        plan = self._plan(user=self.dhirisha_user)
        plan.with_user(self.dhirisha_user).action_submit()
        self.assertEqual(plan.state, 'submitted')
        told = self._messages(plan, self.principal)
        self.assertEqual(len(told), 1)                                              # principal is told
        self.assertIn('Counting lesson', told.body)
        self.assertNotIn('&lt;', told.body)
        plan.with_user(self.principal).action_approve()
        self.assertEqual((plan.state, plan.approved_by), ('approved', self.principal))
        self.assertEqual(len(self._messages(plan, self.dhirisha_user)), 1)          # teacher is told

    def test_submit_needs_content(self):
        plan = self._plan(user=self.dhirisha_user, objectives=False, activities=False)
        with self.assertRaises(UserError):
            plan.with_user(self.dhirisha_user).action_submit()

    def test_reject_needs_reason_then_teacher_resubmits(self):
        plan = self._plan(user=self.dhirisha_user)
        plan.with_user(self.dhirisha_user).action_submit()
        with self.assertRaises(UserError):
            plan.with_user(self.principal).action_reject()
        plan.with_user(self.principal).write({'reject_reason': 'Add an activity'})
        plan.with_user(self.principal).action_reject()
        self.assertEqual(plan.state, 'rejected')
        self.assertIn('Add an activity', self._messages(plan, self.dhirisha_user)[-1].body)
        plan.with_user(self.dhirisha_user).write({'activities': 'Counting game and worksheet'})   # can edit again
        plan.with_user(self.dhirisha_user).action_submit()
        self.assertEqual((plan.state, bool(plan.reject_reason)), ('submitted', False))

    def test_rights(self):
        plan = self._plan(user=self.dhirisha_user)
        with self.assertRaises(AccessError):                                        # another teacher
            plan.with_user(self.other_user).write({'name': 'hijack'})
        with self.assertRaises(AccessError):
            plan.with_user(self.other_user).action_submit()
        plan.with_user(self.dhirisha_user).action_submit()
        with self.assertRaises(AccessError):                                        # teacher cannot approve
            plan.with_user(self.dhirisha_user).action_approve()
        with self.assertRaises(AccessError):                                        # submitted plan is locked
            plan.with_user(self.dhirisha_user).write({'name': 'late change'})
        with self.assertRaises(AccessError):
            plan.with_user(self.dhirisha_user).unlink()
        plan.with_user(self.dhirisha_user).action_set_draft()                       # withdraw, then edit
        plan.with_user(self.dhirisha_user).write({'name': 'Counting lesson v2'})
        plan.with_user(self.dhirisha_user).action_submit()
        plan.with_user(self.principal).action_approve()
        with self.assertRaises(AccessError):                                        # only principal reopens approved
            plan.with_user(self.dhirisha_user).action_set_draft()
        plan.with_user(self.principal).action_set_draft()
        self.assertEqual(plan.state, 'draft')

    def test_topics_and_outcomes_must_belong_to_the_syllabus(self):
        other = _build_syllabus(self, subject=self.english, publish=False)
        with self.assertRaises(ValidationError):
            self._plan(topic_ids=[(6, 0, other.topic_ids.ids)])
        with self.assertRaises(ValidationError):
            self._plan(outcome_ids=[(6, 0, other.outcome_ids.ids)])
        with self.assertRaises(ValidationError):
            self._plan(periods=0)
        ok = self._plan(topic_ids=[(6, 0, self.syl.topic_ids[:2].ids)], outcome_ids=[(6, 0, self.syl.outcome_ids.ids)])
        self.assertEqual(len(ok.topic_ids), 2)

    def test_duplicate_starts_as_a_draft(self):
        plan = self._plan(user=self.dhirisha_user)
        plan.with_user(self.dhirisha_user).action_submit()
        plan.with_user(self.principal).action_approve()
        again = plan.with_user(self.principal).copy({'planned_date': DAY + timedelta(days=7)})
        self.assertEqual((again.state, again.approved_by, again.reject_reason), ('draft', self.env['res.users'], False))

    def test_i_taught_this_prefills_the_diary(self):
        topics = self.syl.topic_ids[:2]
        plan = self._plan(user=self.dhirisha_user, topic_ids=[(6, 0, topics.ids)],
                          outcome_ids=[(6, 0, self.syl.outcome_ids[:1].ids)], homework_plan='Count 20 things at home')
        ctx = plan.action_create_diary()['context']
        self.assertEqual((ctx['default_lesson_plan_id'], ctx['default_subject_id'], ctx['default_class_id']),
                         (plan.id, self.maths.id, self.klass.id))
        self.assertEqual(ctx['default_topic_ids'], [(6, 0, topics.ids)])
        self.assertEqual(ctx['default_homework_text'], 'Count 20 things at home')


@tagged('post_install', '-at_install', 'school_academic')
class TestClassDiary(_Common, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _base(cls)
        cls._setup_people()
        cls.syl = _build_syllabus(cls)
        cls.Diary = cls.env['school.class.diary']

    def _diary(self, user=None, **kw):
        vals = {'date': DAY, 'class_id': self.klass.id, 'subject_id': self.maths.id, 'summary': 'Counting to 100'}
        vals.update(kw)
        return (self.Diary.with_user(user) if user else self.Diary).create(vals)

    def _topic(self, name):
        return self.syl.topic_ids.filtered(lambda t: t.name == name)

    def test_year_syllabus_and_teacher_are_filled_in(self):
        diary = self._diary(user=self.dhirisha_user)
        self.assertEqual(diary.academic_year_id, self.year)
        self.assertEqual(diary.syllabus_id, self.syl)
        self.assertEqual((diary.teacher_id, diary.state), (self.dhirisha, 'draft'))
        self.assertEqual(diary.display_name, 'CU Maths - CU Class 1 - 2026-08-10')

    def test_diary_follows_the_syllabus_of_the_lesson_plan_even_when_there_are_two_syllabi(self):
        """Two syllabi for the same class / subject / year (a duplicate was saved by mistake)."""
        mine = _build_syllabus(self, subject=self.english, publish=False)               # the real one (has topics)
        duplicate = self.env['school.syllabus'].create({                                # newer, empty duplicate
            'name': 'Duplicate', 'academic_year_id': self.year2.id, 'class_id': self.klass.id,
            'subject_id': self.english.id})
        self.env.cr.execute("UPDATE school_syllabus SET academic_year_id = %s WHERE id = %s",
                            (self.year.id, duplicate.id))                                   # legacy data (a new one is refused)
        duplicate.invalidate_recordset()
        self.assertGreater(duplicate.id, mine.id)
        plan = self.env['school.lesson.plan'].create({
            'name': 'English plan', 'syllabus_id': mine.id, 'objectives': 'Read',
            'topic_ids': [(6, 0, mine.topic_ids[:1].ids)]})
        ctx = plan.action_create_diary()['context']                                      # what "I Taught This" does
        diary = self.Diary.create({
            'date': DAY, 'class_id': ctx['default_class_id'], 'subject_id': ctx['default_subject_id'],
            'lesson_plan_id': ctx['default_lesson_plan_id'], 'topic_ids': ctx['default_topic_ids'],
            'summary': ctx['default_summary']})
        self.assertEqual(diary.syllabus_id, mine)                                        # not the duplicate
        self.assertEqual(diary.topic_ids, mine.topic_ids[:1])

    def test_diary_without_a_plan_follows_the_syllabus_of_its_topics(self):
        mine = _build_syllabus(self, subject=self.english, publish=False)
        dup = self.env['school.syllabus'].create({
            'name': 'Duplicate', 'academic_year_id': self.year2.id, 'class_id': self.klass.id,
            'subject_id': self.english.id})
        self.env.cr.execute("UPDATE school_syllabus SET academic_year_id = %s WHERE id = %s", (self.year.id, dup.id))
        dup.invalidate_recordset()
        diary = self.Diary.create({
            'date': date(2031, 1, 1), 'class_id': self.klass.id, 'subject_id': self.english.id,   # no academic year there
            'summary': 'Read', 'topic_ids': [(6, 0, mine.topic_ids[:1].ids)]})
        self.assertEqual(diary.syllabus_id, mine)

    def test_overlapping_academic_years_pick_the_one_that_started_last(self):
        later = self.env['school.academic.year'].create(
            {'name': 'Later year', 'code': 'LTR', 'date_start': '2026-08-01', 'date_end': '2031-01-01'})   # overlaps 2026-27
        self.assertEqual(self._diary().academic_year_id, later)                           # not a random one of the two

    def test_publish_needs_content(self):
        with self.assertRaises(UserError):
            self._diary(user=self.dhirisha_user, summary=False).with_user(self.dhirisha_user).action_publish()

    def test_publish_moves_the_syllabus_progress(self):
        counting, ordering = self._topic('Counting'), self._topic('Ordering')
        diary = self._diary(user=self.dhirisha_user, topic_ids=[(6, 0, (counting | ordering).ids)])
        self.assertEqual(counting.status, 'not_started')
        diary.with_user(self.dhirisha_user).action_publish()
        self.assertEqual((diary.state, counting.status, ordering.status), ('published', 'in_progress', 'in_progress'))
        finished = self._diary(user=self.dhirisha_user, topic_ids=[(6, 0, counting.ids)], mark_topics_done=True,
                               date=DAY + timedelta(days=1))
        finished.with_user(self.dhirisha_user).action_publish()
        self.assertEqual((counting.status, counting.completed_date), ('completed', fields.Date.context_today(counting)))
        self.assertGreater(self.syl.progress, 0.0)

    def test_only_the_subject_teacher_can_finish_topics(self):
        counting = self._topic('Counting')
        wrote = self._diary(user=self.other_user, topic_ids=[(6, 0, counting.ids)], mark_topics_done=True)
        with self.assertRaises(UserError):
            wrote.with_user(self.other_user).action_publish()
        self.assertEqual((wrote.state, counting.status), ('draft', 'not_started'))
        soft = self._diary(user=self.other_user, topic_ids=[(6, 0, counting.ids)])      # not "finished"
        soft.with_user(self.other_user).action_publish()                                # saved, progress untouched
        self.assertEqual((soft.state, counting.status), ('published', 'not_started'))

    def test_only_the_author_edits_a_diary_entry(self):
        diary = self._diary(user=self.dhirisha_user)
        with self.assertRaises(AccessError):
            diary.with_user(self.other_user).write({'summary': 'hijack'})
        with self.assertRaises(AccessError):
            diary.with_user(self.other_user).action_publish()
        with self.assertRaises(AccessError):
            diary.with_user(self.other_user).unlink()
        diary.with_user(self.dhirisha_user).action_publish()
        diary.with_user(self.dhirisha_user).write({'remarks': 'Bring a ruler'})         # author may fix a published entry
        diary.with_user(self.principal).write({'remarks': 'Bring a ruler and pencil'})   # principal too

    def test_links_must_match(self):
        other = _build_syllabus(self, subject=self.english, publish=False)
        with self.assertRaises(ValidationError):
            self._diary(topic_ids=[(6, 0, other.topic_ids.ids)])
        plan = self.env['school.lesson.plan'].create({
            'name': 'English plan', 'syllabus_id': other.id, 'objectives': 'x'})
        with self.assertRaises(ValidationError):
            self._diary(lesson_plan_id=plan.id)

    def test_give_homework_opens_a_prefilled_assignment(self):
        diary = self._diary(user=self.dhirisha_user, homework_text='Count your toys',
                            outcome_ids=[(6, 0, self.syl.outcome_ids[:1].ids)])
        ctx = diary.action_give_homework()['context']
        self.assertEqual((ctx['default_kind'], ctx['default_diary_id'], ctx['default_subject_id']),
                         ('homework', diary.id, self.maths.id))
        work = self.env['school.oe.assignment'].with_context().create({
            'name': 'HW', 'kind': ctx['default_kind'], 'diary_id': diary.id, 'class_id': self.klass.id,
            'subject_id': self.maths.id, 'max_marks': ctx['default_max_marks'],
            'due_datetime': ctx['default_due_datetime'], 'instructions': ctx['default_instructions']})
        self.assertEqual((work.kind, work.diary_id, diary.homework_count), ('homework', diary, 1))
        self.assertEqual(work.instructions, 'Count your toys')
        with self.assertRaises(ValidationError):                                         # diary is for maths, not english
            work.subject_id = self.english

    def test_homework_goes_through_the_existing_submit_and_feedback_flow(self):
        diary = self._diary(user=self.dhirisha_user)
        work = self.env['school.oe.assignment'].create({
            'name': 'Counting homework', 'kind': 'homework', 'diary_id': diary.id, 'class_id': self.klass.id,
            'subject_id': self.maths.id, 'max_marks': 10.0, 'due_datetime': fields.Datetime.now() + timedelta(days=1)})
        work.action_publish()
        sec = self.env['school.section'].create({'name': 'A', 'class_id': self.klass.id, 'capacity': 30})
        kid = self.env['school.student'].create({
            'name': 'AW Kid', 'class_id': self.klass.id, 'section_id': sec.id, 'academic_year_id': self.year.id})
        sub = work._submission_for(kid, create=True)
        sub.add_files([('answers.pdf', PDF)])
        sub.submit_work()
        sub.write({'marks': 8.0, 'feedback': 'Neat counting'})
        sub.action_evaluate()
        self.assertEqual((sub.state, sub.marks, sub.feedback), ('evaluated', 8.0, 'Neat counting'))
        self.assertIn(sub, self.env['school.oe.submission'].search([('assignment_id.kind', '=', 'homework')]))

    def test_diary_form_has_no_give_homework_button_and_no_linked_to_section(self):
        from lxml import etree
        arch = self.env['school.class.diary'].get_view(view_type='form')['arch']
        tree = etree.fromstring(arch.encode())
        self.assertFalse(tree.xpath("//button[@name='action_give_homework']"))                 # button is gone
        self.assertTrue(tree.xpath("//field[@name='homework_text']"))                          # the homework note stays
        self.assertTrue(tree.xpath("//field[@name='homework_ids']"))                           # and the homework list
        for name in ('lesson_plan_id', 'syllabus_id', 'topic_ids', 'mark_topics_done', 'outcome_ids'):
            hidden = tree.xpath("//field[@name='%s']/ancestor::group[@invisible='1']" % name)
            self.assertTrue(hidden, name)             # still in the form (so "I Taught This" fills them) but not shown
        for node in tree.xpath("//field[@name='company_id']"):                                  # only in multi-company databases
            self.assertTrue(node.xpath("ancestor::group[@invisible='1']"))

    # ---- the Homework tab fills itself ---------------------------------------------------------------
    def _homework(self, **kw):
        vals = {'name': 'Auto homework', 'kind': 'homework', 'class_id': self.klass.id, 'subject_id': self.maths.id,
                'max_marks': 10.0, 'due_datetime': fields.Datetime.now() + timedelta(days=1)}
        vals.update(kw)
        return self.env['school.oe.assignment'].create(vals)

    def _today_diary(self, **kw):
        vals = {'date': fields.Date.context_today(self.env['res.users']), 'class_id': self.klass.id,
                'subject_id': self.maths.id, 'summary': 'Today'}
        vals.update(kw)
        return self.Diary.create(vals)

    def test_homework_made_after_the_diary_joins_it(self):
        diary = self._today_diary()
        work = self._homework()
        self.assertEqual(work.diary_id, diary)
        self.assertEqual((diary.homework_count, diary.homework_ids), (1, work))        # what the Homework tab shows

    def test_homework_made_before_the_diary_is_adopted_by_it(self):
        work = self._homework()
        self.assertFalse(work.diary_id)
        diary = self._today_diary()                                                     # the entry is written afterwards
        self.assertEqual(work.diary_id, diary)
        diary.with_user(self.dhirisha_user).action_publish()                            # publishing keeps the link
        self.assertEqual((work.diary_id, diary.homework_count), (diary, 1))

    def test_only_the_same_class_subject_section_and_day_match(self):
        sec_a = self.env['school.section'].create({'name': 'A', 'class_id': self.klass.id, 'capacity': 30})
        sec_b = self.env['school.section'].create({'name': 'B', 'class_id': self.klass.id, 'capacity': 30})
        diary_a = self._today_diary(section_id=sec_a.id)
        self.assertEqual(self._homework(section_id=sec_a.id).diary_id, diary_a)         # same section
        self.assertEqual(self._homework(name='whole').diary_id, diary_a)                # no section: every section
        self.assertFalse(self._homework(name='B', section_id=sec_b.id).diary_id)        # another section
        self.assertFalse(self._homework(name='English', subject_id=self.english.id).diary_id)   # another subject
        old = self.Diary.create({'date': fields.Date.context_today(self.env['res.users']) - timedelta(days=3),
                                 'class_id': self.klass.id, 'subject_id': self.english.id, 'summary': 'Old'})
        self.assertFalse(self._homework(name='Not today', subject_id=self.english.id).diary_id)  # the entry is of another day
        self.assertFalse(old.homework_ids)

    def test_explicit_link_and_other_kinds_are_left_alone(self):
        today = self._today_diary()
        yesterday = self.Diary.create({'date': fields.Date.context_today(self.env['res.users']) - timedelta(days=1),
                                       'class_id': self.klass.id, 'subject_id': self.maths.id, 'summary': 'Yesterday'})
        self.assertEqual(self._homework(diary_id=yesterday.id).diary_id, yesterday)     # chosen by hand
        self.assertFalse(self._homework(kind='assignment', name='A project').diary_id)  # only homework is linked
        self.assertEqual(today.homework_count, 0)

    def test_the_form_fills_the_diary_field_by_itself(self):
        diary = self._today_diary()
        work = self.env['school.oe.assignment'].new({'kind': 'homework', 'class_id': self.klass.id,
                                                     'subject_id': self.maths.id})
        work._onchange_homework_diary()
        self.assertEqual(work.diary_id._origin, diary)

    def test_menus_exist(self):
        for name in ('menu_school_class_diary', 'menu_school_lesson_plan', 'menu_school_learning_outcome',
                     'menu_school_homework', 'menu_school_homework_check'):
            self.assertTrue(self.env.ref('school_academic.%s' % name))


@tagged('post_install', '-at_install', 'school_academic')
class TestDiaryPortal(_Common, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _base(cls)
        cls._setup_people()
        env = cls.env
        cls.syl = _build_syllabus(cls)
        sec_a = env['school.section'].create({'name': 'A', 'class_id': cls.klass.id, 'capacity': 30})
        cls.sec_b = env['school.section'].create({'name': 'B', 'class_id': cls.klass.id, 'capacity': 30})
        sec2 = env['school.section'].create({'name': 'A', 'class_id': cls.klass2.id, 'capacity': 30})
        cls.kid = env['school.student'].create({
            'name': 'AW Portal Kid', 'class_id': cls.klass.id, 'section_id': sec_a.id, 'academic_year_id': cls.year.id})
        cls.kid2 = env['school.student'].create({
            'name': 'AW Other Class Kid', 'class_id': cls.klass2.id, 'section_id': sec2.id,
            'academic_year_id': cls.year.id})
        portal = env.ref('base.group_portal')
        for st, login in ((cls.kid, 'awkid'), (cls.kid2, 'awkid2')):
            env['res.users'].create({'name': st.name, 'login': login, 'password': login,
                                     'partner_id': st.partner_id.id, 'group_ids': [(6, 0, [portal.id])]})
        today = fields.Date.context_today(env['res.users'])
        lo1 = cls.syl.outcome_ids.filtered(lambda o: o.code == 'LO1')
        cls.entry = env['school.class.diary'].with_user(cls.dhirisha_user).create({
            'date': today, 'class_id': cls.klass.id, 'subject_id': cls.maths.id, 'period_no': 2,
            'summary': 'We counted objects up to 100', 'classwork': 'Worksheet 4', 'homework_text': 'Count 20 toys',
            'remarks': 'Bring a ruler tomorrow', 'topic_ids': [(6, 0, cls.syl.topic_ids[:1].ids)],
            'outcome_ids': [(6, 0, lo1.ids)]})
        cls.entry.with_user(cls.dhirisha_user).action_publish()
        cls.draft = env['school.class.diary'].create({
            'date': today, 'class_id': cls.klass.id, 'subject_id': cls.english.id, 'summary': 'DRAFT ONLY ENTRY'})
        cls.sec_b_entry = env['school.class.diary'].create({
            'date': today, 'class_id': cls.klass.id, 'section_id': cls.sec_b.id, 'subject_id': cls.free_subject.id,
            'summary': 'ONLY SECTION B', 'state': 'published'})
        cls.old = env['school.class.diary'].create({
            'date': today - timedelta(days=40), 'class_id': cls.klass.id, 'subject_id': cls.english.id,
            'summary': 'FORTY DAYS AGO', 'state': 'published'})
        cls.work = env['school.oe.assignment'].create({
            'name': 'Counting homework', 'kind': 'homework', 'diary_id': cls.entry.id, 'class_id': cls.klass.id,
            'subject_id': cls.maths.id, 'max_marks': 10.0,
            'due_datetime': fields.Datetime.now() + timedelta(days=1)})
        cls.work.action_publish()
        cls.hidden_work = env['school.oe.assignment'].create({
            'name': 'Unpublished homework', 'kind': 'homework', 'diary_id': cls.entry.id, 'class_id': cls.klass.id,
            'subject_id': cls.maths.id, 'due_datetime': fields.Datetime.now() + timedelta(days=1)})

    def test_student_sees_published_diary_of_own_class_and_section(self):
        self.authenticate('awkid', 'awkid')
        self.assertIn('/my/diary', self.url_open('/my').text)                           # home card
        page = self.url_open('/my/diary')
        self.assertEqual(page.status_code, 200)
        for text in ('CU Maths', 'We counted objects up to 100', 'Worksheet 4', 'Count 20 toys', 'Bring a ruler tomorrow',
                     'Period 2', 'Dhirisha', 'Counting', 'Counts objects up to 100', 'I can now', 'Counting homework'):
            self.assertIn(text, page.text)
        self.assertIn('/my/online-assignments/%s' % self.work.id, page.text)            # homework link
        for text in ('DRAFT ONLY ENTRY', 'ONLY SECTION B', 'FORTY DAYS AGO', 'Unpublished homework'):
            self.assertNotIn(text, page.text)

    def test_days_filter_shows_older_entries(self):
        self.authenticate('awkid', 'awkid')
        self.assertIn('FORTY DAYS AGO', self.url_open('/my/diary?days=90').text)
        self.assertNotIn('FORTY DAYS AGO', self.url_open('/my/diary?days=30').text)
        self.assertEqual(self.url_open('/my/diary?days=abc').status_code, 200)           # bad input falls back

    def test_other_class_student_sees_nothing_of_it(self):
        self.authenticate('awkid2', 'awkid2')
        page = self.url_open('/my/diary')
        self.assertIn('No class diary entries', page.text)
        self.assertNotIn('We counted objects', page.text)

    def test_homework_label_in_the_assignment_list(self):
        self.authenticate('awkid', 'awkid')
        page = self.url_open('/my/online-assignments')
        self.assertIn('Counting homework', page.text)
        self.assertIn('Homework', page.text)
