{
    'name': 'Alumni Management',
    'version': '19.0.1.0',
    'summary': 'Alumni network for the School Management System: Student → Graduate → Alumni → Mentor',
    'description': """
Alumni Management (add-on of School Management System)
======================================================
* Alumni details and graduation year (graduate students straight from School Management)
* Higher education and profession (with career history)
* Achievements
* Mentorship (alumni mentors guiding current students, with sessions)
* Donations (with receipts)
* Career guidance sessions for students
* Alumni events (reunions, meet-ups, webinars, fund-raisers)

Life cycle: Student → Graduate → Alumni → Mentor
    """,
    'category': 'Education',
    'author': 'ADream Innovations',
    'website': 'https://adreaminnovations.odoo.com',
    'depends': ['ad_school_management', 'mail'],
    'data': [
        'security/alumni_security.xml',
        'security/ir.model.access.csv',
        'data/alumni_sequence.xml',
        'views/alumni_views.xml',
        'views/alumni_mentorship_views.xml',
        'views/alumni_guidance_views.xml',
        'views/alumni_event_views.xml',
        'views/alumni_donation_views.xml',
        'views/alumni_config_views.xml',
        'views/school_student_views.xml',
        'wizard/alumni_graduate_wizard_views.xml',
        'report/alumni_donation_receipt.xml',
        'views/alumni_menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}