# -*- coding: utf-8 -*-
{
    'name': 'School Academic Management',
    'version': '19.0.5.2.0',
    'category': 'Education',
    'summary': 'Curriculum management (class + academic year + subjects with periods). '
               'Syllabus, units, lesson plans, homework and more follow in the same module.',
    'description': """
School Academic Management (BRS Part II)
========================================
Step 1 - Curriculum management
* One curriculum per class and academic year
* Subject lines: type (core / elective / co-scholastic), periods per week, annual periods, subject teacher
* Draft -> Published (approved by principal / admin) -> Archived
* Copy a curriculum to the next academic year in one click
* (Curriculum and syllabus are managed by the school; they are not shown in the student portal)

Step 2 - Syllabus management
* One syllabus per class + subject + academic year: units with planned periods, term, objectives, references, documents
* Compared with the periods given in the curriculum; draft -> published (principal / admin) -> archived
* "Create Syllabus Drafts" from a published curriculum; the subject teachers are notified

Step 4 - Learning outcomes, lesson planning, class diary, homework
* Learning outcomes per unit / topic, marked covered when taught
* Lesson plans with principal approval
* Class diary (publishes to students / parents, moves topic progress)
* Homework = Online Exam assignment of type Homework (uploads, marks and feedback already exist there)

Step 3 - Unit / topic management
* Topics inside every unit with planned periods; Not started / In progress / Completed tracking
* Unit and syllabus progress (weighted by periods); the subject teacher can tick topics even after publishing
* Topic Tracker (list, pivot, graph) and progress shown to students and parents
    """,
    'author': 'Custom',
    'license': 'LGPL-3',
    'depends': ['ad_school_management', 'mail', 'portal', 'school_online_exam'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/curriculum_views.xml',
        'views/syllabus_views.xml',
        'views/learning_views.xml',
        'wizard/curriculum_copy_wizard_views.xml',
        'wizard/syllabus_copy_wizard_views.xml',
        'views/menus.xml',
        'views/portal_templates.xml',
        'views/portal_diary_templates.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
