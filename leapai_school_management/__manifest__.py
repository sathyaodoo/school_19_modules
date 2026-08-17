# -*- coding: utf-8 -*-
{
    'name': 'School Management System',
    'version': '19.0.1.0.1',
    'category': 'Education',
    'summary': 'Comprehensive School Management System for Odoo 19',
    'description': """
School Management System
========================
A complete school management solution including:
- Student enrollment and management
- Class and classroom management
- Teacher management
- Subject management
- Examination and results
- Fee management and receipts
- Attendance tracking
- Transport management
- Hostel management
- Academic year configuration
    """,
    'author': 'leapai.ai',
    'website': 'https://leapai.ai',
    'license': 'LGPL-3',
    'images': [
        'static/description/banner.png',
        'static/description/screenshot_01_students_list.png',
        'static/description/screenshot_02_student_form.png',
        'static/description/screenshot_03_exam_results.png',
        'static/description/screenshot_04_fee_payment.png',
        'static/description/screenshot_05_hostel.png',
        'static/description/screenshot_06_student_report.png',
    ],
    'depends': ['base', 'mail', 'account', 'hr'],
    'application': True,
    'data': [
        'security/school_security.xml',
        'security/ir.model.access.csv',
        'data/school_sequence.xml',
        'views/school_academic_year_views.xml',
        'views/school_class_views.xml',
        'views/school_subject_views.xml',
        'views/school_teacher_views.xml',
        'views/school_student_views.xml',
        'views/school_exam_views.xml',
        'views/school_fee_views.xml',
        'views/school_attendance_views.xml',
        'views/school_transport_views.xml',
        'views/school_hostel_views.xml',
        'views/school_menu.xml',
        'report/school_student_report.xml',
        'report/school_student_report_template.xml',
        'report/school_fee_report.xml',
        'report/school_fee_report_template.xml',
        'report/school_exam_report.xml',
        'report/school_exam_report_template.xml',
    ],
    'demo': [
        'demo/school_demo.xml',
    ],
    'installable': True,
    'auto_install': False,
}
