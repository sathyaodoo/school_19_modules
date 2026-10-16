{
    'name': 'School Helpdesk - Maintenance Link',
    'version': '19.0.1.0.0',
    'summary': 'Create a Maintenance Request from Helpdesk tickets marked as Maintenance',
    'category': 'Services/Helpdesk',
    'author': 'Banibro Technologies',
    'depends': ['dev_all_in_one_helpdesk', 'maintenance'],
    'data': [
        'views/helpdesk_maintenance_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
