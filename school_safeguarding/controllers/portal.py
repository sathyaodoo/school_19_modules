# -*- coding: utf-8 -*-
import hmac
import time
from datetime import date

from odoo import SUPERUSER_ID, _, http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal

from ..models.case import CATEGORIES

MAX_DESCRIPTION = 5000
MAX_SHORT = 200
MAX_REPORTS_PER_HOUR = 5
MAX_BAD_CODES = 10


class SafeguardingPortal(CustomerPortal):
    """Students and parents can tell the school about a concern, anonymously if they want.
    They can never read a case; with the reference and code they only see a short status."""

    # ------------------------------------------------------------------ helpers
    def _sg_students(self):
        partner = request.env.user.partner_id
        Student = request.env['school.student'].sudo()
        own = Student.search([('partner_id', '=', partner.id)])
        if own:
            return own, False
        kids = Student.search([('parent_ids.partner_id', '=', partner.id)])
        return kids, bool(kids)

    def _sg_recent(self):
        """Timestamps of the reports sent from this browser session in the last hour (no identity is stored)."""
        now = time.time()
        recent = [t for t in request.session.get('sg_reports', []) if now - t < 3600]
        request.session['sg_reports'] = recent
        return recent

    def _sg_render_form(self, values=None, error=None, status=200):
        students, is_parent = self._sg_students()
        data = {'categories': CATEGORIES, 'students': students, 'is_parent': is_parent, 'error': error,
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

        anonymous = bool(post.get('anonymous'))
        vals = {
            'category': category, 'description': description,
            'location': (post.get('location') or '').strip()[:MAX_SHORT],
            'involved_other': (post.get('involved') or '').strip()[:MAX_SHORT],
            'incident_date': self._sg_date(post.get('incident_date')),
            'immediate_risk': bool(post.get('urgent')),
        }
        if anonymous:
            vals['is_anonymous'] = True                       # nothing links the report to this user
        else:
            students, is_parent = self._sg_students()
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
        case = request.env['school.safeguarding.case'].with_user(SUPERUSER_ID).create(vals)
        request.session['sg_reports'] = self._sg_recent() + [time.time()]
        return request.render('school_safeguarding.portal_sg_done', {
            'reference': case.name, 'code': case.access_code, 'anonymous': anonymous,
            'urgent': bool(post.get('urgent')), 'page_name': 'safeguarding'})

    @http.route(['/my/safeguarding/status'], type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_safeguarding_status(self, **post):
        values = {'case': None, 'error': None, 'asked': False, 'page_name': 'safeguarding'}
        if request.httprequest.method == 'POST':
            values['asked'] = True
            bad = request.session.get('sg_bad_codes', 0)
            reference = (post.get('reference') or '').strip()
            code = (post.get('code') or '').strip().upper()
            if bad >= MAX_BAD_CODES:
                values['error'] = _("Too many tries. Please wait and try again later.")
            else:
                case = request.env['school.safeguarding.case'].sudo().search([('name', '=', reference)], limit=1)
                if case and case.access_code and hmac.compare_digest(case.access_code.encode(), code.encode()):
                    values['case'] = case
                else:
                    request.session['sg_bad_codes'] = bad + 1
                    values['error'] = _("We could not find a report with this reference and code.")
        return request.render('school_safeguarding.portal_sg_status', values)
