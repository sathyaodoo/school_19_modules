# -*- coding: utf-8 -*-
from urllib.parse import quote

from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import request

from .portal_assignment import OnlineAssignmentPortal

PRACTICE_SIZES = (5, 10, 20)
MAX_PRACTICE_QUESTIONS = 50


class OnlinePracticePortal(OnlineAssignmentPortal):
    """Self-practice: the student picks subject / chapter / topic and the size."""

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _pr_sizes(count):
        sizes = [n for n in PRACTICE_SIZES if n <= count]
        if count <= max(PRACTICE_SIZES) and count not in sizes:
            sizes.append(count)
        return sorted(sizes)

    def _pr_catalog(self, student):
        """[{subject, total, sizes, chapters: [{chapter, total, sizes, topics: [...]}]}]"""
        Question = request.env['school.oe.question'].sudo()
        groups = Question._read_group(
            [('class_id', '=', student.class_id.id), ('active', '=', True)],
            ['subject_id', 'chapter_id', 'topic_id'], ['__count'])
        subjects = {}
        for subject, chapter, topic, count in groups:
            s = subjects.setdefault(subject.id, {'subject': subject, 'total': 0, 'chapters': {}})
            s['total'] += count
            if chapter:
                c = s['chapters'].setdefault(chapter.id, {'chapter': chapter, 'total': 0, 'topics': []})
                c['total'] += count
                if topic:
                    c['topics'].append({'topic': topic, 'count': count, 'sizes': self._pr_sizes(count)})
        Setting = request.env['school.oe.practice.setting']
        result = []
        for s in subjects.values():
            if not Setting.is_practice_open(student.class_id, s['subject']):
                continue
            s['sizes'] = self._pr_sizes(s['total'])
            chapters = sorted(s['chapters'].values(),
                              key=lambda c: (c['chapter'].sequence, c['chapter'].name))
            for c in chapters:
                c['sizes'] = self._pr_sizes(c['total'])
                c['topics'].sort(key=lambda t: (t['topic'].sequence, t['topic'].name))
            s['chapters'] = chapters
            result.append(s)
        return sorted(result, key=lambda s: s['subject'].name)

    def _pr_redirect(self, student, error=None):
        url = '/my/online-practice?student_id=%s' % student.id
        if error:
            url += '&error=%s' % quote(error)
        return request.redirect(url)

    # ------------------------------------------------------------------ home
    @http.route(['/my/online-practice'], type='http', auth='user', website=True)
    def portal_pr_home(self, student_id=None, error=None, **kw):
        students, is_parent = self._oe_students()
        if not students:
            return self._oe_error(_('No Student Record'), _('No student record is linked to your account.'))
        student = self._oe_pick_student(students, student_id)
        catalog = [] if is_parent else self._pr_catalog(student)
        sessions = request.env['school.oe.exam'].sudo().search(
            [('exam_type', '=', 'practice'), ('practice_student_id', '=', student.id)],
            order='write_date desc')
        history = [{'exam': e, 'used': len(e.attempt_ids), 'final': e._final_attempt(student)}
                   for e in sessions if e.attempt_ids]
        values = self._prepare_portal_layout_values()
        values.update({'catalog': catalog, 'history': history, 'students': students,
                       'student': student, 'is_parent': is_parent, 'error': error,
                       'page_name': 'online_exam'})
        return request.render('school_online_exam.portal_oe_practice', values)

    # ------------------------------------------------------------------ start
    @http.route(['/my/online-practice/start'], type='http', auth='user', website=True,
                methods=['POST'], csrf=True)
    def portal_pr_start(self, subject_id=None, chapter_id=None, topic_id=None, n=None, **kw):
        students, is_parent = self._oe_students()
        if not students or is_parent:
            return self._oe_error(_('Not allowed'), _('Only the student can practise.'))
        student = students[0]
        env = request.env
        try:
            subject = env['school.subject'].sudo().browse(int(subject_id)).exists()
            chapter = env['school.oe.chapter'].sudo().browse(int(chapter_id or 0)).exists()
            topic = env['school.oe.topic'].sudo().browse(int(topic_id or 0)).exists()
            wanted = int(n)
        except (TypeError, ValueError):
            return self._pr_redirect(student, _("Invalid choice."))
        try:
            if not subject or not env['school.oe.practice.setting'].is_practice_open(student.class_id, subject):
                raise UserError(_("Practice is not open for this subject."))
            if chapter and (chapter.class_id != student.class_id or chapter.subject_id != subject):
                raise UserError(_("This chapter is not for your class and subject."))
            if topic and topic.chapter_id != chapter:
                raise UserError(_("This topic is not in the selected chapter."))
            domain = [('class_id', '=', student.class_id.id), ('subject_id', '=', subject.id),
                      ('active', '=', True)]
            if topic:
                domain.append(('topic_id', '=', topic.id))
            elif chapter:
                domain.append(('chapter_id', '=', chapter.id))
            pool = env['school.oe.question'].sudo().search_count(domain)
            if not pool:
                raise UserError(_("There are no questions for this choice yet."))
            size = max(1, min(wanted, pool, MAX_PRACTICE_QUESTIONS))
            exam = env['school.oe.exam']._practice_exam_for(student, subject, chapter, topic, size)
            attempt = exam._start_or_resume_attempt(student)
        except UserError as e:
            return self._pr_redirect(student, str(e))
        return request.redirect('/my/online-exams/attempt/%s' % attempt.id)
