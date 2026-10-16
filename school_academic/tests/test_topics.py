# -*- coding: utf-8 -*-
from datetime import date

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import HttpCase, TransactionCase, tagged

from .test_curriculum import _base, _make


def _topic(name, periods=1, **kw):
    return (0, 0, dict({'name': name, 'planned_periods': periods}, **kw))


@tagged('post_install', '-at_install', 'school_academic')
class TestTopics(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _base(cls)
        env = cls.env
        base_user = env.ref('base.group_user')
        teacher_group = env.ref('ad_school_management.group_school_teacher')
        cls.dhirisha_user = env['res.users'].create({
            'name': 'TP Dhirisha', 'login': 'tp_dhirisha', 'group_ids': [(6, 0, [base_user.id, teacher_group.id])]})
        cls.other_user = env['res.users'].create({
            'name': 'TP Other Teacher', 'login': 'tp_other', 'group_ids': [(6, 0, [base_user.id, teacher_group.id])]})
        cls.principal = env['res.users'].create({
            'name': 'TP Principal', 'login': 'tp_principal',
            'group_ids': [(6, 0, [base_user.id, env.ref('ad_school_management.group_school_principal').id])]})
        cls.dhirisha = env['school.teacher'].create({'name': 'Dhirisha', 'user_id': cls.dhirisha_user.id})
        _make(cls, line_ids=[(0, 0, {'subject_id': cls.maths.id, 'periods_per_week': 6, 'teacher_id': cls.dhirisha.id}),
                             (0, 0, {'subject_id': cls.english.id, 'periods_per_week': 5})])
        cls.Syllabus = env['school.syllabus']

    def _syllabus(self, subject=None, **kw):
        vals = {'name': 'TP Syllabus', 'academic_year_id': self.year.id, 'class_id': self.klass.id,
                'subject_id': (subject or self.maths).id,
                'unit_ids': [
                    (0, 0, {'name': 'Numbers', 'planned_periods': 100, 'topic_ids': [
                        _topic('Counting', 30), _topic('Ordering', 30), _topic('Place value', 20), _topic('Compare', 20)]}),
                    (0, 0, {'name': 'Addition', 'planned_periods': 50, 'topic_ids': [_topic('Add small', 25), _topic('Add big', 25)]})]}
        vals.update(kw)
        return self.Syllabus.create(vals)

    def _t(self, syl, name):
        return syl.unit_ids.topic_ids.filtered(lambda t: t.name == name)

    # ---- structure ---------------------------------------------------------------
    def test_topics_belong_to_units_and_are_counted(self):
        syl = self._syllabus()
        numbers = syl.unit_ids.filtered(lambda u: u.name == 'Numbers')
        self.assertEqual((numbers.topic_count, numbers.topic_periods), (4, 100))
        self.assertEqual(syl.topic_count, 6)
        self.assertEqual(self._t(syl, 'Counting').syllabus_id, syl)
        self.assertEqual(self._t(syl, 'Counting').subject_id, self.maths)
        self.assertEqual(self._t(syl, 'Counting').teacher_user_id, self.dhirisha_user)

    def test_negative_topic_periods_refused_and_unit_delete_removes_topics(self):
        syl = self._syllabus()
        with self.assertRaises(ValidationError):
            self._t(syl, 'Counting').planned_periods = -1
        unit = syl.unit_ids.filtered(lambda u: u.name == 'Addition')
        unit.unlink()
        self.assertEqual(syl.topic_count, 4)

    # ---- progress -------------------------------------------------------------------
    def test_unit_status_and_progress_follow_the_topics(self):
        syl = self._syllabus()
        numbers = syl.unit_ids.filtered(lambda u: u.name == 'Numbers')
        self.assertEqual((numbers.status, numbers.progress), ('not_started', 0.0))
        syl.action_publish()
        self._t(syl, 'Counting').action_mark_completed()
        self.assertEqual((numbers.status, numbers.progress), ('in_progress', 25.0))
        self._t(syl, 'Ordering').action_mark_in_progress()
        self.assertEqual((numbers.status, numbers.progress), ('in_progress', 25.0))   # started is not completed
        for name in ('Ordering', 'Place value', 'Compare'):
            self._t(syl, name).action_mark_completed()
        self.assertEqual((numbers.status, numbers.progress), ('completed', 100.0))

    def test_unit_created_together_with_topics_gets_the_right_status(self):
        syl = self._syllabus(unit_ids=[(0, 0, {'name': 'Mixed', 'planned_periods': 50, 'topic_ids': [
            _topic('Done one', 25, status='completed'), _topic('Not yet', 25)]}),
            (0, 0, {'name': 'All done', 'planned_periods': 10, 'topic_ids': [_topic('Only', 10, status='completed')]})])
        mixed, done = syl.unit_ids.sorted('id')
        self.assertEqual((mixed.status, mixed.progress), ('in_progress', 50.0))
        self.assertEqual((done.status, done.progress), ('completed', 100.0))
        self.assertEqual(self._t(syl, 'Done one').completed_date, fields.Date.context_today(syl))   # date filled automatically

    def test_syllabus_progress_is_weighted_by_unit_periods(self):
        syl = self._syllabus()
        syl.action_publish()
        self.assertEqual(syl.progress, 0.0)
        for t in syl.unit_ids.filtered(lambda u: u.name == 'Numbers').topic_ids:     # unit of 100 periods done
            t.action_mark_completed()
        self.assertAlmostEqual(syl.progress, 100.0 * 100 / 150, places=1)           # the unit of 50 periods is not
        for t in syl.unit_ids.topic_ids:
            t.action_mark_completed()
        self.assertEqual(syl.progress, 100.0)

    def test_unit_without_topics_can_be_set_by_hand(self):
        syl = self._syllabus(unit_ids=[(0, 0, {'name': 'Revision', 'planned_periods': 10})])
        unit = syl.unit_ids
        self.assertEqual((unit.status, unit.progress), ('not_started', 0.0))
        unit.status = 'completed'
        self.assertEqual(unit.progress, 100.0)
        self.assertEqual(syl.progress, 100.0)

    def test_completed_date_is_kept_and_cleared(self):
        syl = self._syllabus()
        syl.action_publish()
        topic = self._t(syl, 'Counting')
        topic.action_mark_completed()
        self.assertEqual((topic.status, topic.completed_date), ('completed', fields.Date.context_today(topic)))
        topic.action_reset_progress()
        self.assertEqual((topic.status, topic.completed_date, topic.completed_pct), ('not_started', False, 0.0))

    # ---- who may tick topics ------------------------------------------------------------
    def test_draft_syllabus_any_teacher_publish_only_subject_teacher(self):
        syl = self._syllabus()
        self._t(syl, 'Counting').with_user(self.other_user).action_mark_completed()      # draft: allowed
        syl.action_publish()
        topic = self._t(syl, 'Ordering')
        with self.assertRaises(AccessError):                                             # other teacher
            topic.with_user(self.other_user).action_mark_completed()
        with self.assertRaises(AccessError):
            topic.with_user(self.other_user).write({'remarks': 'sneaky'})
        topic.with_user(self.dhirisha_user).action_mark_completed()                      # subject teacher
        topic.with_user(self.dhirisha_user).write({'remarks': 'done in 2 periods'})
        self.assertEqual((topic.status, topic.remarks), ('completed', 'done in 2 periods'))
        self._t(syl, 'Compare').with_user(self.principal).action_mark_completed()        # principal

    def test_structure_is_locked_after_publish(self):
        syl = self._syllabus()
        syl.action_publish()
        topic = self._t(syl, 'Counting')
        as_teacher = topic.with_user(self.dhirisha_user)
        with self.assertRaises(AccessError):
            as_teacher.write({'name': 'Renamed'})
        with self.assertRaises(AccessError):
            as_teacher.write({'planned_periods': 99})
        with self.assertRaises(AccessError):
            as_teacher.unlink()
        with self.assertRaises(AccessError):
            self.env['school.syllabus.topic'].with_user(self.dhirisha_user).create(
                {'unit_id': syl.unit_ids[0].id, 'name': 'New topic'})
        topic.with_user(self.principal).write({'name': 'Counting to 100'})              # principal may

    def test_teacher_edits_topics_while_draft(self):
        syl = self._syllabus()
        as_teacher = self._t(syl, 'Counting').with_user(self.dhirisha_user)
        as_teacher.write({'name': 'Counting 1-100', 'planned_periods': 35})
        self.env['school.syllabus.topic'].with_user(self.dhirisha_user).create(
            {'unit_id': syl.unit_ids[0].id, 'name': 'Skip counting'})
        self.assertEqual(syl.topic_count, 7)

    def test_archived_syllabus_progress_is_locked_for_teachers(self):
        syl = self._syllabus()
        syl.action_publish()
        syl.action_archive_syllabus()
        with self.assertRaises(AccessError):
            self._t(syl, 'Counting').with_user(self.dhirisha_user).action_mark_completed()

    # ---- topic tracker / reports -------------------------------------------------------------
    def test_topic_tracker_shows_only_my_published_topics(self):
        mine = self._syllabus()
        theirs = self._syllabus(subject=self.english, name='English')
        mine.action_publish()
        theirs.action_publish()
        Topic = self.env['school.syllabus.topic'].with_user(self.dhirisha_user)
        found = Topic.search([('teacher_user_id', '=', self.dhirisha_user.id), ('syllabus_state', '=', 'published')])
        self.assertEqual(found.mapped('subject_id'), self.maths)
        self.assertEqual(len(found), 6)

    def test_coverage_report_numbers(self):
        syl = self._syllabus()
        syl.action_publish()
        for name in ('Counting', 'Ordering'):
            self._t(syl, name).action_mark_completed()
        rows = self.env['school.syllabus.topic']._read_group(
            [('syllabus_state', '=', 'published'), ('subject_id', '=', self.maths.id)],
            ['subject_id'], ['completed_pct:avg', '__count'])
        subject, pct, count = rows[0]
        self.assertEqual(count, 6)
        self.assertAlmostEqual(pct, 2 * 100.0 / 6, places=1)

    # ---- copy ------------------------------------------------------------------------------------
    def test_copy_to_next_year_keeps_topics_but_not_progress(self):
        syl = self._syllabus()
        syl.action_publish()
        self._t(syl, 'Counting').action_mark_completed()
        new = self.Syllabus.browse(self.env['school.syllabus.copy.wizard'].create(
            {'syllabus_id': syl.id, 'target_year_id': self.year2.id}).action_copy()['res_id'])
        self.assertEqual(sorted(new.unit_ids.topic_ids.mapped('name')), sorted(syl.unit_ids.topic_ids.mapped('name')))
        self.assertEqual(set(new.unit_ids.topic_ids.mapped('status')), {'not_started'})
        self.assertEqual(new.progress, 0.0)
