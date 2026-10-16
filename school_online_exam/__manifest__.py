# -*- coding: utf-8 -*-
{
    'name': 'School Online Exam',
    'version': '19.0.1.7.0',
    'category': 'Education',
    'summary': 'Online MCQ exams with question bank, random questions per attempt, '
               'server-side timer, resume on re-login and full attempt history',
    'description': """
School Online Exam
==================
* Class / Subject / Chapter / Topic wise question bank (staff / admin)
* Exam setup: N questions per attempt (default 10) picked randomly from the bank
* Configurable duration (default 2 minutes) - timer runs on the SERVER
* Configurable attempts (0 = unlimited), "avoid repeating questions" option
* Student leaves and logs in again -> same attempt, same questions, remaining time
* Time over -> attempt is auto-submitted and scored
* Every attempt (questions, answers, score) is stored as history
* Backend menu "Online Exam" and a portal card "Online Exam" (student / parent)
* Descriptive answer-sheet / assignment / project upload (PDF, JPG, PNG) from the portal
* Teacher evaluation: marks + feedback, visible to the student
* Mock tests: practice exams, answers always shown, never counted in the marks register
* Self-practice: the student picks subject / chapter / topic and the number of questions
* Performance analysis: student, chapter (weak areas) and question difficulty reports + 'My Performance' portal page
* Approved marks integration: teacher sends marks (MCQ exam / assignment), the principal approves,
  only then they are written into School Exam Results
    """,
    'author': 'Custom',
    'license': 'LGPL-3',
    'depends': ['ad_school_management', 'portal'],
    'data': [
        'security/ir.model.access.csv',
        'views/oe_question_views.xml',
        'views/oe_exam_views.xml',
        'views/oe_attempt_views.xml',
        'views/oe_assignment_views.xml',
        'views/oe_practice_views.xml',
        'views/oe_analysis_views.xml',
        'views/oe_marks_views.xml',
        'views/oe_menus.xml',
        'data/oe_cron.xml',
        'views/portal_templates.xml',
        'views/portal_assignment_templates.xml',
        'views/portal_practice_templates.xml',
        'views/portal_performance_templates.xml',
    ],
    'demo': [
        'demo/oe_demo.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
