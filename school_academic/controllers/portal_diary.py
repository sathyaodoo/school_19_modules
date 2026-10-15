# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, fields, http
from odoo.http import request

from .portal import AcademicPortal

DIARY_DAYS = (7, 14, 30, 90)


class DiaryPortal(AcademicPortal):
    """Class diary for students and parents."""

    def _dy_entries(self, student, days):
        since = fields.Date.context_today(request.env.user) - timedelta(days=days)
        entries = request.env['school.class.diary'].sudo().search(
            [('state', '=', 'published'), ('class_id', '=', student.class_id.id), ('date', '>=', since)],
            order='date desc, period_no, id desc')
        # an entry for one section is only for the students of that section
        return entries.filtered(lambda e: not e.section_id or e.section_id == student.section_id)

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'diary_count' in counters:
            students, _is_parent = self._ac_students()
            total = 0
            for st in students:
                total += len(self._dy_entries(st, 7))
            values['diary_count'] = total
        return values

    @http.route(['/my/diary'], type='http', auth='user', website=True)
    def portal_diary(self, student_id=None, days=None, **kw):
        students, is_parent = self._ac_students()
        if not students:
            return request.render('school_academic.portal_ac_message', {
                'title': _('No Student Record'), 'message': _('No student record is linked to your account.')})
        student = students[:1]
        if student_id:
            try:
                student = students.filtered(lambda s: s.id == int(student_id))[:1] or student
            except (TypeError, ValueError):
                pass
        try:
            days = int(days)
        except (TypeError, ValueError):
            days = 14
        days = days if days in DIARY_DAYS else 14
        entries = self._dy_entries(student, days)
        groups = []                                                  # [(date, [entries])] newest first
        for entry in entries:
            if groups and groups[-1][0] == entry.date:
                groups[-1][1].append(entry)
            else:
                groups.append((entry.date, [entry]))
        homework = {e.id: e.homework_ids.filtered(lambda a: a.state == 'published' and a._visible_for(student))
                    for e in entries}
        values = self._prepare_portal_layout_values()
        values.update({'students': students, 'student': student, 'is_parent': is_parent, 'groups': groups,
                       'homework': homework, 'days': days, 'day_options': DIARY_DAYS, 'page_name': 'diary'})
        return request.render('school_academic.portal_ac_diary', values)
