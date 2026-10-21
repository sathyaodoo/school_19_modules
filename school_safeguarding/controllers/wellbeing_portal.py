# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import SUPERUSER_ID, fields, http
from odoo.http import request


class WellbeingPortal(http.Controller):
    """Student: check-in, ask to talk. Parent: share a concern. Nobody sees the counsellors' records here."""

    def _people(self):
        partner = request.env.user.partner_id
        Student = request.env['school.student'].sudo()
        return Student.search([('partner_id', '=', partner.id)], limit=1), Student.search([('parent_ids.partner_id', '=', partner.id)])

    def _page(self, error=None, done=None):
        own, children = self._people()
        cfg = request.env['school.wellbeing.config'].sudo()._get(own.company_id or request.env.company)
        Checkin = request.env['school.wellbeing.checkin'].sudo()
        history, today_checkin, due = Checkin.browse(), Checkin.browse(), False
        if own:
            history = Checkin.search([('student_id', '=', own.id)], limit=8)
            today = fields.Date.context_today(request.env.user)
            today_checkin = history.filtered(lambda c: c.checkin_date == today)[:1]
            due = not history or (today - history[0].checkin_date).days >= cfg.checkin_interval_days
        values = {
            'own': own, 'children': children, 'history': history, 'today_checkin': today_checkin, 'due': due and not today_checkin,
            'cfg': cfg, 'error': error, 'done': done, 'page_name': 'wellbeing',
            'states': request.env['school.wellbeing.checkin']._fields['status'].selection,
            'areas': request.env['school.wellbeing.area'].sudo().search([('for_parents', '=', True)]),
        }
        return request.render('school_safeguarding.portal_wellbeing', values)

    @http.route('/my/wellbeing', type='http', auth='user', website=True)
    def wellbeing(self, done=None, **kw):
        return self._page(done=done if done in ('checkin', 'talk', 'concern') else None)

    @http.route('/my/wellbeing/checkin', type='http', auth='user', methods=['POST'], website=True)
    def wellbeing_checkin(self, **post):
        own, _children = self._people()
        status = post.get('status')
        if not own or status not in dict(request.env['school.wellbeing.checkin']._fields['status'].selection):
            return self._page(error="Please choose how you feel.")
        Checkin = request.env['school.wellbeing.checkin'].sudo()
        today = fields.Date.context_today(request.env.user)
        vals = {'status': status, 'note': (post.get('note') or '').strip()[:1000], 'wants_to_talk': bool(post.get('wants_to_talk'))}
        existing = Checkin.search([('student_id', '=', own.id), ('checkin_date', '=', today)], limit=1)
        if existing:
            existing.write(vals)
        else:
            Checkin.create(dict(vals, student_id=own.id, checkin_date=today, source='student'))
        return request.redirect('/my/wellbeing?done=checkin')

    @http.route('/my/wellbeing/talk', type='http', auth='user', methods=['POST'], website=True)
    def wellbeing_talk(self, **post):
        own, _children = self._people()
        if not own:
            return request.redirect('/my/wellbeing')
        area = request.env.ref('school_safeguarding.area_emotional', raise_if_not_found=False)
        request.env['school.wellbeing.case'].sudo()._raise_for_student(
            own, 'medium', (post.get('reason') or '').strip()[:500] or "The student asked to talk to a counsellor.", source='self',
            talk=True, company=own.company_id or request.env.company, reporter=own.partner_id, areas=area, alert=True)
        return request.redirect('/my/wellbeing?done=talk')

    @http.route('/my/wellbeing/concern', type='http', auth='user', methods=['POST'], website=True)
    def wellbeing_concern(self, **post):
        _own, children = self._people()
        try:
            child = children.filtered(lambda s: s.id == int(post.get('child_id') or 0))[:1]
        except ValueError:
            child = children.browse()
        text = (post.get('description') or '').strip()
        if not child or len(text) < 10:
            return self._page(error="Please choose your child and write a few words about your concern.")
        level = post.get('level') if post.get('level') in ('low', 'medium', 'high') else 'medium'
        Area = request.env['school.wellbeing.area'].sudo()
        area = Area.search([('id', '=', int(post.get('area_id') or 0)), ('for_parents', '=', True)], limit=1)
        Case = request.env['school.wellbeing.case'].sudo()
        partner = request.env.user.partner_id
        since = fields.Datetime.now() - timedelta(hours=1)
        if Case.search_count([('reporter_partner_id', '=', partner.id), ('source', '=', 'parent'), ('opened_datetime', '>=', since)]) >= 5:
            return self._page(error="Too many messages. Please try again later or call the school.")
        Case.with_user(SUPERUSER_ID).create({
            'student_id': child.id, 'source': 'parent', 'level': level, 'area_ids': [(6, 0, area.ids)],
            'concern_text': text[:3000], 'reporter_partner_id': partner.id, 'company_id': child.company_id.id or request.env.company.id})
        return request.redirect('/my/wellbeing?done=concern')
