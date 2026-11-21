# -*- coding: utf-8 -*-
import time
from datetime import date

from odoo import SUPERUSER_ID, _, http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal

from ..models.case import CATEGORIES

MAX_DESCRIPTION = 5000
MAX_SHORT = 200
MAX_REPORTS_PER_HOUR = 5


class SafeguardingPortal(CustomerPortal):
    """Students and parents can tell the school about a concern, anonymously if they want.
    They can never read a case; they only see the reports they sent and the status of each."""

    # ------------------------------------------------------------------ helpers
    def _sg_students(self):
        partner = request.env.user.partner_id
        Student = request.env['school.student'].sudo()
        own = Student.search([('partner_id', '=', partner.id)])
        if own:
            return own, False
        kids = Student.search([('parent_ids.partner_id', '=', partner.id)])
        return kids, bool(kids)

    def _sg_classmates(self, students):
        """Students the reporter may name as 'involved': the classmates of the student
        (or of the parent's children). The whole school is never listed in the portal."""
        classes = students.mapped('class_id')
        if not classes:
            return request.env['school.student'].sudo()
        return request.env['school.student'].sudo().search(
            [('class_id', 'in', classes.ids), ('id', 'not in', students.ids)], order='name')

    def _sg_recent(self):
        """Timestamps of the reports sent from this browser session in the last hour."""
        now = time.time()
        recent = [t for t in request.session.get('sg_reports', []) if now - t < 3600]
        request.session['sg_reports'] = recent
        return recent

    def _sg_render_form(self, values=None, error=None, status=200):
        students, is_parent = self._sg_students()
        data = {'categories': CATEGORIES, 'students': students, 'is_parent': is_parent, 'error': error,
                'classmates': self._sg_classmates(students),
                'selected_involved': [int(x) for x in request.httprequest.form.getlist('involved_students')
                                      if str(x).isdigit()] if values else [],
                'values': values or {}, 'page_name': 'safeguarding'}
        response = request.render('school_safeguarding.portal_sg_form', data)
        response.status_code = status
        return response

    @staticmethod
    def _sg_date(text):
        try:
            return date.fromisoformat((text or '').strip()) if text else False
        except ValueError:
            return False

    # ------------------------------------------------------------------ pages
    @http.route(['/my/safeguarding'], type='http', auth='user', website=True)
    def portal_safeguarding(self, **kw):
        return self._sg_render_form()

    @http.route(['/my/safeguarding/submit'], type='http', auth='user', website=True, methods=['POST'])
    def portal_safeguarding_submit(self, **post):
        category = post.get('category')
        description = (post.get('description') or '').strip()
        error = None
        if category not in dict(CATEGORIES):
            error = _("Please choose what happened.")
        elif len(description) < 10:
            error = _("Please tell us a little more about what happened.")
        elif len(description) > MAX_DESCRIPTION:
            error = _("Please write a shorter description. You can add more later by telling the Safeguarding Officer.")
        elif len(self._sg_recent()) >= MAX_REPORTS_PER_HOUR:
            error = _("You have already sent several reports. Please wait a while, or tell a trusted adult.")
        if error:
            return self._sg_render_form(values=post, error=error, status=400)

        students, is_parent = self._sg_students()
        # students named as involved: only ids from the reporter's own class list are accepted
        allowed = self._sg_classmates(students)
        picked = {int(x) for x in request.httprequest.form.getlist('involved_students') if str(x).isdigit()}
        involved = allowed.filtered(lambda s: s.id in picked)

        anonymous = bool(post.get('anonymous'))
        vals = {
            'category': category, 'description': description,
            'location': (post.get('location') or '').strip()[:MAX_SHORT],
            'involved_other': (post.get('involved') or '').strip()[:MAX_SHORT],
            'involved_student_ids': [(6, 0, involved.ids)],
            'incident_date': self._sg_date(post.get('incident_date')),
            'immediate_risk': bool(post.get('urgent')),
            # hidden link so the sender sees their own reports (named or anonymous) in the portal
            'submitter_user_id': request.env.user.id,
        }
        if anonymous:
            vals['is_anonymous'] = True                       # the Safeguarding team does not see who sent it
        else:
            vals.update({'reporter_partner_id': request.env.user.partner_id.id,
                         'source': 'parent' if is_parent else 'student'})
            if post.get('about_me') and students:
                try:
                    child_id = int(post.get('child') or 0)
                except ValueError:
                    child_id = 0
                about = students.filtered(lambda s: s.id == child_id) if is_parent else students[:1]
                if about:
                    vals['affected_student_ids'] = [(6, 0, about.ids)]
        request.env['school.safeguarding.case'].with_user(SUPERUSER_ID).create(vals)
        request.session['sg_reports'] = self._sg_recent() + [time.time()]
        return request.render('school_safeguarding.portal_sg_done', {
            'anonymous': anonymous, 'urgent': bool(post.get('urgent')), 'page_name': 'safeguarding'})

    @http.route(['/my/safeguarding/status'], type='http', auth='user', website=True)
    def portal_safeguarding_status(self, **kw):
        """All reports this user sent (named and anonymous): only the date, the kind and the status."""
        user = request.env.user
        cases = request.env['school.safeguarding.case'].sudo().search(
            ['|', ('submitter_user_id', '=', user.id),
                  '&', ('reporter_partner_id', '=', user.partner_id.id), ('is_anonymous', '=', False)],
            order='create_date desc, id desc', limit=100)
        return request.render('school_safeguarding.portal_sg_status', {
            'cases': cases, 'category_labels': dict(CATEGORIES), 'page_name': 'safeguarding'})