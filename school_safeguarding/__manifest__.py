# -*- coding: utf-8 -*-
{
    'name': 'School Safeguarding & Well-being (Confidential)',
    'version': '19.0.1.1.4',
    'category': 'Education',
    'summary': 'Confidential safeguarding (bullying, harassment, child-safety concerns, anonymous reporting, investigation, '
               'escalation) and confidential student well-being (counselling sessions, check-ins, referrals, interventions).',
    'description': """
School Digital Safeguarding / Child Protection (BRS item 14)
===========================================================
A separate module (not a generic complaints workflow).

* Concerns: bullying, cyberbullying, harassment, child-safety concerns, other safeguarding concerns
* Anonymous reporting from the student / parent portal (the reporter is never stored) with a private
  reference + code to check the status
* Staff report through a short form; they cannot read the cases afterwards
* Workflow: Reported -> Assessment -> Investigation -> Follow-up -> Closed, with escalation (principal / management /
  external authority)
* Case log, follow-up actions with reminders, evidence files
* Access restricted to the Safeguarding Officer and Safeguarding Lead groups (not even the Odoo administrator or the
  principal unless they are given the group); audit trail of who opened a case; no deletion; export only for the Lead;
  retention date

School Student Well-being (BRS item 13), in the same module
-----------------------------------------------------------
* Counselling sessions (private notes), emotional check-ins from the student portal (Good / Okay / Struggling / Need help),
  well-being cases (social adjustment, peer relationships, academic stress, bullying concerns, ...), screening ratings,
  referrals with parental consent, intervention follow-up with reminders
* Its own groups: Counsellor and Well-being Lead. Teachers raise a concern and cannot read it afterwards; the principal,
  the school admin and the Odoo administrator see nothing unless they are given the group. A case can be restricted to its
  own counsellor; audit log; no deletion; export for the Lead only; alerts carry the reference, never names or notes
* "Share with Safeguarding": the counsellor tells the Safeguarding team (only the summary typed, never the counselling notes)
    """,
    'author': 'Custom',
    'license': 'LGPL-3',
    'depends': ['ad_school_management', 'mail', 'portal'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'data/cron.xml',
        'data/wellbeing_data.xml',
        'data/wellbeing_cron.xml',
        'views/case_views.xml',
        'views/wellbeing_views.xml',
        'wizard/report_wizard_views.xml',
        'wizard/wellbeing_concern_wizard_views.xml',
        'wizard/wellbeing_share_wizard_views.xml',
        'views/menus.xml',
        'views/portal_templates.xml',
        'views/wellbeing_portal_templates.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
