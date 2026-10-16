# -*- coding: utf-8 -*-
from lxml import etree

from datetime import date

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import HttpCase, TransactionCase, tagged

from .test_curriculum import _base, _make

PDF = b'%PDF-1.4\n%syllabus\n'


def _units(*periods):
    return [(0, 0, {'name': 'Unit %s' % (i + 1), 'planned_periods': p}) for i, p in enumerate(periods)]


@tagged('post_install', '-at_install', 'school_academic')
class TestSyllabus(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _base(cls)
        env = cls.env
        base_user = env.ref('base.group_user')
        cls.teacher_user = env['res.users'].create({
            'name': 'SY Teacher', 'login': 'sy_teacher',
            'group_ids': [(6, 0, [base_user.id, env.ref('ad_school_management.group_school_teacher').id])]})
        cls.principal = env['res.users'].create({
            'name': 'SY Principal', 'login': 'sy_principal',
            'group_ids': [(6, 0, [base_user.id, env.ref('ad_school_management.group_school_principal').id])]})
        cls.dhirisha = env['school.teacher'].create({'name': 'Dhirisha', 'user_id': cls.teacher_user.id})
        cls.curriculum = _make(cls, line_ids=[
            (0, 0, {'subject_id': cls.maths.id, 'periods_per_week': 6, 'teacher_id': cls.dhirisha.id}),
            (0, 0, {'subject_id': cls.english.id, 'periods_per_week': 5}),
            (0, 0, {'subject_id': cls.free_subject.id, 'periods_per_week': 1})])
        cls.Syllabus = env['school.syllabus']

    def _syl(self, subject=None, **kw):
        vals = {'name': 'Maths Syllabus', 'academic_year_id': self.year.id, 'class_id': self.klass.id,
                'subject_id': (subject or self.maths).id, 'unit_ids': _units(100, 80)}
        vals.update(kw)
        return self.Syllabus.create(vals)

    # ---- link with the curriculum -------------------------------------------------
    def test_periods_come_from_the_curriculum(self):
        syl = self._syl()
        line = self.curriculum.line_ids.filtered(lambda l: l.subject_id == self.maths)
        self.assertEqual(syl.curriculum_line_id, line)
        self.assertEqual(syl.allotted_periods, 6 * 36)                  # 216
        self.assertEqual((syl.unit_count, syl.planned_periods, syl.balance_periods), (2, 180, 36))
        self.assertFalse(syl.over_planned)
        self.assertEqual(syl.teacher_id, self.dhirisha)
        self.assertEqual(syl.teacher_user_id, self.teacher_user)
        syl.write({'unit_ids': _units(60)})                              # 240 planned > 216
        self.assertTrue(syl.over_planned)
        self.assertEqual(syl.balance_periods, -24)

    def test_no_curriculum_means_no_link_and_no_warning(self):
        syl = self._syl(academic_year_id=self.year2.id)
        self.assertFalse(syl.curriculum_line_id)
        self.assertEqual(syl.allotted_periods, 0)
        self.assertFalse(syl.over_planned)

    def test_refresh_link_after_the_curriculum_is_made(self):
        syl = self._syl(academic_year_id=self.year2.id)
        self.assertFalse(syl.curriculum_line_id)
        _make(self, academic_year_id=self.year2.id)
        syl.action_relink_curriculum()
        self.assertEqual(syl.curriculum_line_id.subject_id, self.maths)
        self.assertEqual(syl.allotted_periods, 216)

    def test_subject_must_belong_to_the_class(self):
        with self.assertRaises(ValidationError):
            self._syl(subject=self.only_class2)

    # ---- publishing ----------------------------------------------------------
    def _legacy_duplicate(self, syllabus, **kw):
        """A second syllabus for the same class / subject / year, as it already exists in old data
        (the check below stops new ones, so it is moved into place with SQL)."""
        dup = self._syl(subject=syllabus.subject_id, academic_year_id=self.year2.id, **kw)
        self.env.cr.execute("UPDATE school_syllabus SET academic_year_id = %s WHERE id = %s",
                            (syllabus.academic_year_id.id, dup.id))
        dup.invalidate_recordset()
        return dup

    def test_publish_rules(self):
        empty = self._syl(unit_ids=[], subject=self.english)
        with self.assertRaises(UserError):
            empty.action_publish()
        syl = self._syl()
        with self.assertRaises(AccessError):
            syl.with_user(self.teacher_user).action_publish()
        syl.with_user(self.principal).action_publish()
        self.assertEqual((syl.state, syl.approved_by), ('published', self.principal))
        second = self._legacy_duplicate(syl, name='Duplicate')
        with self.assertRaises(UserError):                               # one published per class/subject/year
            second.action_publish()
        syl.action_archive_syllabus()
        second.action_publish()
        self.assertEqual(second.state, 'published')

    def test_teacher_edits_draft_but_not_published(self):
        syl = self._syl()
        as_teacher = syl.with_user(self.teacher_user)
        as_teacher.write({'objectives': 'Draft aims'})
        as_teacher.unit_ids[0].write({'planned_periods': 90})
        syl.action_publish()
        with self.assertRaises(AccessError):
            as_teacher.write({'objectives': 'changed'})
        with self.assertRaises(AccessError):
            as_teacher.unit_ids[0].write({'planned_periods': 10})
        with self.assertRaises(AccessError):
            self.env['school.syllabus.unit'].with_user(self.teacher_user).create({'syllabus_id': syl.id, 'name': 'X'})
        with self.assertRaises(AccessError):
            as_teacher.unlink()
        syl.with_user(self.principal).write({'objectives': 'principal may edit'})

    # ---- drafts from the curriculum ------------------------------------------------
    def test_create_syllabus_drafts_from_published_curriculum(self):
        with self.assertRaises(UserError):
            self.curriculum.action_create_syllabus_drafts()              # curriculum still draft
        self.curriculum.action_publish()
        self.curriculum.action_create_syllabus_drafts()
        drafts = self.Syllabus.search([('class_id', '=', self.klass.id), ('academic_year_id', '=', self.year.id)])
        self.assertEqual(sorted(drafts.mapped('subject_id').ids),
                         sorted([self.maths.id, self.english.id, self.free_subject.id]))
        self.assertEqual(set(drafts.mapped('state')), {'draft'})
        self.assertEqual(self.curriculum.syllabus_count, 3)
        # only the maths teacher (has a login) is told
        told = drafts.message_ids.filtered(lambda m: self.teacher_user.partner_id in m.partner_ids)
        self.assertEqual(len(told), 1)
        self.assertIn('Please prepare', told.body)
        self.assertIn('216', told.body)
        self.assertIn('<b>CU Maths</b>', told.body)
        self.assertNotIn('&lt;', told.body)                      # shown as formatted text, not raw tags
        self.curriculum.action_create_syllabus_drafts()                  # again: nothing new, no new message
        self.assertEqual(self.Syllabus.search_count([('class_id', '=', self.klass.id)]), 3)
        self.assertEqual(len(drafts.message_ids.filtered(lambda m: self.teacher_user.partner_id in m.partner_ids)), 1)

    def test_my_syllabus_for_the_subject_teacher(self):
        self.curriculum.action_publish()
        self.curriculum.action_create_syllabus_drafts()
        mine = self.Syllabus.with_user(self.teacher_user).search(
            [('teacher_user_id', '=', self.teacher_user.id), ('state', '!=', 'archived')])
        self.assertEqual(mine.mapped('subject_id'), self.maths)

    # ---- copy ------------------------------------------------------------------------
    def test_copy_to_another_year(self):
        syl = self._syl(objectives='Aims', reference_books='NCERT')
        action = self.env['school.syllabus.copy.wizard'].create(
            {'syllabus_id': syl.id, 'target_year_id': self.year2.id}).action_copy()
        new = self.Syllabus.browse(action['res_id'])
        self.assertEqual((new.state, new.academic_year_id, new.subject_id), ('draft', self.year2, self.maths))
        self.assertEqual(new.unit_ids.mapped('name'), syl.unit_ids.mapped('name'))
        self.assertEqual(new.planned_periods, 180)
        self.assertEqual((new.objectives, new.reference_books), ('Aims', 'NCERT'))
        with self.assertRaises(UserError):
            self.env['school.syllabus.copy.wizard'].create(
                {'syllabus_id': syl.id, 'target_year_id': self.year.id}).action_copy()

    def test_uploaded_documents_belong_to_the_syllabus(self):
        att = self.env['ir.attachment'].create({'name': 'syllabus.pdf', 'raw': PDF, 'mimetype': 'application/pdf'})
        syl = self._syl(attachment_ids=[(4, att.id)])
        self.assertEqual((att.res_model, att.res_id), ('school.syllabus', syl.id))


@tagged('post_install', '-at_install', 'school_academic')
class TestOneSyllabusPerSubject(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _base(cls)
        cls.principal = cls.env['res.users'].create({
            'name': 'OS Principal', 'login': 'os_principal',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id,
                                  cls.env.ref('ad_school_management.group_school_principal').id])]})
        cls.Syllabus = cls.env['school.syllabus']

    def _make_syllabus(self, subject=None, **kw):
        vals = {'name': 'OS Syllabus', 'academic_year_id': self.year.id, 'class_id': self.klass.id,
                'subject_id': (subject or self.maths).id, 'unit_ids': _units(10)}
        vals.update(kw)
        return self.Syllabus.create(vals)

    def test_second_syllabus_for_the_same_class_subject_year_is_refused(self):
        first = self._make_syllabus()
        with self.assertRaises(ValidationError) as ctx:
            self._make_syllabus(name='Another one')
        self.assertIn(first.name, str(ctx.exception.args[0]))
        self._make_syllabus(subject=self.english)                       # other subject: fine
        self._make_syllabus(academic_year_id=self.year2.id)             # other year: fine
        self._make_syllabus(class_id=self.klass2.id, subject_id=self.only_class2.id)

    def test_archived_syllabus_does_not_block_a_new_one(self):
        first = self._make_syllabus()
        first.action_publish()
        first.action_archive_syllabus()
        again = self._make_syllabus(name='Fresh start')
        self.assertEqual(again.state, 'draft')

    def test_reopening_an_archived_syllabus_needs_the_active_one_archived_first(self):
        old = self._make_syllabus()
        old.action_publish()
        old.action_archive_syllabus()
        new = self._make_syllabus(name='New one')
        with self.assertRaises(UserError):
            old.with_user(self.principal).action_set_draft()
        new.action_archive_syllabus()
        old.with_user(self.principal).action_set_draft()
        self.assertEqual(old.state, 'draft')

    def test_copy_to_a_year_that_already_has_the_syllabus_is_refused(self):
        source = self._make_syllabus()
        self._make_syllabus(academic_year_id=self.year2.id, name='Already there')
        with self.assertRaises(ValidationError):
            self.env['school.syllabus.copy.wizard'].create(
                {'syllabus_id': source.id, 'target_year_id': self.year2.id}).action_copy()

    def test_create_syllabus_drafts_does_not_create_duplicates(self):
        curriculum = _make(self)
        curriculum.action_publish()
        existing = self._make_syllabus()                                  # maths already has one
        curriculum.action_create_syllabus_drafts()
        self.assertEqual(self.Syllabus.search_count(
            [('class_id', '=', self.klass.id), ('subject_id', '=', self.maths.id)]), 1)
        self.assertEqual(self.Syllabus.search([('subject_id', '=', self.maths.id)]), existing)

    def test_old_duplicates_can_still_be_cleaned_up(self):
        """The mess that already exists: a published old one, an empty draft and the good draft."""
        good = self._make_syllabus(name='Good draft')                      # has the units / topics
        old_published = self._make_syllabus(name='Old published', academic_year_id=self.year2.id)
        # build the legacy state with SQL (the new check would not allow it any more)
        empty = self._make_syllabus(name='Empty draft', subject=self.english, unit_ids=[])
        self.env.cr.execute("UPDATE school_syllabus SET academic_year_id = %s, state = 'published' WHERE id = %s",
                            (self.year.id, old_published.id))
        self.env.cr.execute("UPDATE school_syllabus SET subject_id = %s WHERE id = %s", (self.maths.id, empty.id))
        (old_published | empty).invalidate_recordset()
        self.assertEqual(len(self.Syllabus.search([('subject_id', '=', self.maths.id)])), 3)
        # 1. archive the old published one, 2. delete the empty draft, 3. publish the good one
        old_published.with_user(self.principal).action_archive_syllabus()
        empty.unlink()
        good.with_user(self.principal).action_publish()
        self.assertEqual((good.state, old_published.state), ('published', 'archived'))


@tagged('post_install', '-at_install', 'school_academic')
class TestSyllabusFromCurriculum(TransactionCase):
    """The syllabus follows what the curriculum gives: class, section, subject."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _base(cls)
        env = cls.env
        cls.sec_a = env['school.section'].create({'name': 'A', 'class_id': cls.klass.id, 'capacity': 30})
        cls.sec_b = env['school.section'].create({'name': 'B', 'class_id': cls.klass.id, 'capacity': 30})
        cls.sec_c = env['school.section'].create({'name': 'C', 'class_id': cls.klass.id, 'capacity': 30})
        cls.sec_other_class = env['school.section'].create({'name': 'Z', 'class_id': cls.klass2.id, 'capacity': 30})
        base_user = env.ref('base.group_user')
        tg = env.ref('ad_school_management.group_school_teacher')
        cls.teacher_user = env['res.users'].create({'name': 'FC Teacher', 'login': 'fc_t1', 'group_ids': [(6, 0, [base_user.id, tg.id])]})
        cls.other_user = env['res.users'].create({'name': 'FC Other', 'login': 'fc_t2', 'group_ids': [(6, 0, [base_user.id, tg.id])]})
        cls.teacher = env['school.teacher'].create({'name': 'FC Teacher', 'user_id': cls.teacher_user.id})
        cls.curriculum = _make(cls, line_ids=[
            (0, 0, {'subject_id': cls.maths.id, 'periods_per_week': 6, 'teacher_id': cls.teacher.id}),
            (0, 0, {'subject_id': cls.english.id, 'periods_per_week': 5}),
            (0, 0, {'subject_id': cls.free_subject.id, 'periods_per_week': 1})])
        Plan = env['school.curriculum.plan']
        for subject, section, topic in ((cls.maths, cls.sec_a, 'Numbers A'), (cls.maths, cls.sec_b, 'Numbers B'),
                                        (cls.english, False, 'Reading')):
            Plan.create({'curriculum_id': cls.curriculum.id, 'subject_id': subject.id, 'topic': topic,
                         'section_id': section.id if section else False})
        cls.Syllabus = env['school.syllabus']

    def _syl(self, **kw):
        vals = {'name': 'FC Syllabus', 'academic_year_id': self.year.id, 'class_id': self.klass.id,
                'subject_id': self.maths.id, 'unit_ids': _units(10)}
        vals.update(kw)
        return self.Syllabus.create(vals)

    # ---- drafts follow class + section + subject of the curriculum -----------------------------
    def test_drafts_are_made_for_every_class_section_subject(self):
        self.curriculum.action_publish()
        self.curriculum.action_create_syllabus_drafts()
        found = self.Syllabus.search([('class_id', '=', self.klass.id), ('academic_year_id', '=', self.year.id)])
        combos = sorted((s.subject_id.name, s.section_id.name or '-') for s in found)
        self.assertEqual(combos, [('CU Art', '-'), ('CU English', '-'), ('CU Maths', 'A'), ('CU Maths', 'B')])
        maths_a = found.filtered(lambda s: s.subject_id == self.maths and s.section_id == self.sec_a)
        self.assertEqual(maths_a.name, 'CU Maths - CU Class 1 A - 2026-27 Syllabus')
        self.assertEqual(maths_a.state, 'draft')
        self.assertEqual(maths_a.teacher_user_id, self.teacher_user)                     # the maths teacher of the curriculum
        self.curriculum.action_create_syllabus_drafts()                                  # again: nothing new
        self.assertEqual(self.Syllabus.search_count([('class_id', '=', self.klass.id)]), 4)

    def test_dropdowns_offer_only_what_the_curriculum_gave(self):
        new = self.Syllabus.new({'academic_year_id': self.year.id, 'company_id': self.env.company.id})
        self.assertEqual(new.allowed_class_ids.ids, self.klass.ids)                      # klass2 has no curriculum
        new.class_id = self.klass
        self.assertEqual(sorted(new.allowed_subject_ids.ids), sorted((self.maths | self.english | self.free_subject).ids))
        new.subject_id = self.maths
        self.assertEqual(sorted(new.allowed_section_ids.ids), sorted((self.sec_a | self.sec_b).ids))   # not C, not the other class
        new.subject_id = self.english
        self.assertFalse(new.allowed_section_ids)                                        # english is for the whole class

    def test_form_limits_the_choices_and_locks_them_after_saving(self):
        arch = self.env['school.syllabus'].get_view(view_type='form')['arch']
        tree = etree.fromstring(arch.encode())
        for field, allowed in (('class_id', 'allowed_class_ids'), ('section_id', 'allowed_section_ids'),
                               ('subject_id', 'allowed_subject_ids')):
            node = tree.xpath("//sheet/group//field[@name='%s']" % field)[0]
            self.assertEqual(node.get('readonly'), 'id')                                  # read-only once saved
            self.assertIn(allowed, node.get('domain'))                                    # only the curriculum values

    # ---- one active syllabus per class + SECTION + subject ----------------------------------------
    def test_duplicate_check_is_per_section(self):
        first = self._syl(section_id=self.sec_a.id)
        self.assertEqual(first.section_id, self.sec_a)
        with self.assertRaises(ValidationError):
            self._syl(section_id=self.sec_a.id, name='again for A')
        self._syl(section_id=self.sec_b.id, name='for B')                                # other section: fine
        self._syl(name='whole class')                                                    # whole class: fine
        with self.assertRaises(ValidationError):
            self._syl(name='whole class again')
        with self.assertRaises(ValidationError):                                         # a section of another class
            self._syl(section_id=self.sec_other_class.id, name='wrong section', subject_id=self.english.id)

    def test_each_section_has_its_own_published_syllabus(self):
        for_a = self._syl(section_id=self.sec_a.id, name='A')
        for_b = self._syl(section_id=self.sec_b.id, name='B')
        whole = self._syl(name='whole class')
        (for_a | for_b | whole).action_publish()                                         # no clash: different sections
        self.assertEqual(set((for_a | for_b | whole).mapped('state')), {'published'})

    def test_copy_to_next_year_keeps_the_section(self):
        syl = self._syl(section_id=self.sec_a.id)
        new = self.Syllabus.browse(self.env['school.syllabus.copy.wizard'].create(
            {'syllabus_id': syl.id, 'target_year_id': self.year2.id}).action_copy()['res_id'])
        self.assertEqual(new.section_id, self.sec_a)

    def test_diary_uses_the_syllabus_of_its_section(self):
        for_a = self._syl(section_id=self.sec_a.id, name='A')
        for_b = self._syl(section_id=self.sec_b.id, name='B')
        whole = self._syl(name='whole')
        Diary = self.env['school.class.diary']
        vals = {'date': date(2026, 8, 10), 'class_id': self.klass.id, 'subject_id': self.maths.id, 'summary': 'x'}
        self.assertEqual(Diary.create(dict(vals, section_id=self.sec_a.id)).syllabus_id, for_a)
        self.assertEqual(Diary.create(dict(vals, section_id=self.sec_b.id)).syllabus_id, for_b)
        self.assertEqual(Diary.create(dict(vals, section_id=self.sec_c.id)).syllabus_id, whole)   # C has none: whole class
        self.assertEqual(Diary.create(dict(vals)).syllabus_id, whole)

    # ---- the Units tab: chapters ----------------------------------------------------------------------
    def test_units_tab_columns(self):
        arch = self.env['school.syllabus'].get_view(view_type='form')['arch']
        tree = etree.fromstring(arch.encode())
        cols = [f.get('name') for f in tree.xpath("//field[@name='unit_ids']/list/field")]
        wanted = ['name', 'term_id', 'chapter_number', 'chapter_name', 'learning_objectives', 'teaching_materials', 'remarks']
        self.assertEqual([c for c in cols if c in wanted], wanted)                        # in the order you asked

    def test_chapter_details_and_who_may_write_remarks(self):
        syl = self._syl(unit_ids=[(0, 0, {
            'name': 'Unit 1', 'chapter_number': '1', 'chapter_name': 'Numbers', 'learning_objectives': 'Count to 100',
            'teaching_materials': 'Counters, charts', 'remarks': 'start in July'})])
        unit = syl.unit_ids
        self.assertEqual((unit.chapter_number, unit.chapter_name, unit.learning_objectives, unit.teaching_materials),
                         ('1', 'Numbers', 'Count to 100', 'Counters, charts'))
        syl.action_publish()
        unit.with_user(self.teacher_user).write({'remarks': 'Taught in 3 periods'})       # the subject teacher
        self.assertEqual(unit.remarks, 'Taught in 3 periods')
        with self.assertRaises(AccessError):                                              # structure is locked
            unit.with_user(self.teacher_user).write({'chapter_name': 'Changed'})
        with self.assertRaises(AccessError):                                              # another teacher
            unit.with_user(self.other_user).write({'remarks': 'sneaky'})

    def test_rows_are_editable_for_the_right_people(self):
        syl = self._syl()
        principal = self.env['res.users'].create({
            'name': 'ED Principal', 'login': 'ed_principal',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('ad_school_management.group_school_principal').id])]})
        self.assertTrue(syl.with_user(self.teacher_user).can_edit_structure)              # draft: the teacher types
        syl.action_publish()
        self.assertFalse(syl.with_user(self.teacher_user).can_edit_structure)             # published: not the teacher
        self.assertTrue(syl.with_user(principal).can_edit_structure)                       # ... but the principal / admin
        self.assertTrue(syl.can_edit_structure)                                            # (superuser)
        arch = self.env['school.syllabus'].get_view(view_type='form')['arch']
        tree = etree.fromstring(arch.encode())
        for field in ('name', 'term_id', 'chapter_number', 'chapter_name', 'learning_objectives', 'teaching_materials'):
            node = tree.xpath("//field[@name='unit_ids']/list/field[@name='%s']" % field)[0]
            self.assertEqual(node.get('readonly'), 'not parent.can_edit_structure')       # no longer "state != draft"
        # and the principal really can type into a published syllabus
        unit = syl.unit_ids
        unit.with_user(principal).write({'chapter_name': 'Typed after publishing', 'learning_objectives': 'New aim'})
        self.assertEqual(unit.chapter_name, 'Typed after publishing')

    def test_header_no_longer_shows_periods_and_progress_numbers(self):
        arch = self.env['school.syllabus'].get_view(view_type='form')['arch']
        tree = etree.fromstring(arch.encode())
        for name in ('allotted_periods', 'planned_periods', 'balance_periods', 'progress'):
            self.assertFalse(tree.xpath("//sheet/group//field[@name='%s']" % name), name)      # removed from the header
        for name in ('teacher_id', 'curriculum_line_id', 'unit_count', 'topic_count'):
            self.assertTrue(tree.xpath("//sheet/group//field[@name='%s']" % name), name)       # these stay
        syl = self._syl()                                                                     # the numbers still work inside
        self.assertEqual((syl.allotted_periods, syl.planned_periods), (6 * 36, 10))

    def test_unit_popup_opens_the_topics_form(self):
        unit = self._syl(unit_ids=[(0, 0, {'name': 'U', 'chapter_name': 'C'})]).unit_ids
        action = unit.action_open_unit_form()
        self.assertEqual((action['res_model'], action['res_id'], action['target']), ('school.syllabus.unit', unit.id, 'new'))
        self.assertTrue(action['views'][0][0])
