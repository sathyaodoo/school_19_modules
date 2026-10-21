# -*- coding: utf-8 -*-
{
    'name': 'School Smart Transport',
    'version': '19.0.1.1.0',
    'category': 'Education',
    'summary': 'Intelligent transport on top of the school transport module: geofencing, van approaching, boarding / '
               'off-boarding records, parent notifications, ETA, route-deviation, speed, breakdown and SOS alerts, '
               'driver behaviour.',
    'description': """
Smart Transport (BRS item 16)
=============================
Extends the existing transport module (vehicles, routes, stops, GPS pings, driver portal, attendance).

* Geofencing: stops with coordinates and radius, the school campus
* "Van approaching" notification to the parents of the stop, with the expected time
* Boarding confirmation, student boarding record, student off-boarding record (driver mobile page)
* Parent notification when the child boards and when the child reaches the stop / school
* Estimated arrival time for every stop (parent page, driver page)
* Alerts to the school: route deviation, excessive speed, vehicle stopped, vehicle breakdown, student left on board
* Emergency SOS (driver page and the GPS device's panic button)
* Driver AND caretaker use "My Trips" (live trip, boarding, SOS, breakdown); every confirmation records who did it
* Driver behaviour: speeding, harsh braking / acceleration, deviations -> score per trip and per driver
    """,
    'author': 'Custom',
    'license': 'LGPL-3',
    'depends': ['ad_school_management', 'mail', 'portal'],
    'data': [
        'security/ir.model.access.csv',
        'data/cron.xml',
        'views/transport_views.xml',
        'wizard/ping_wizard_views.xml',
        'views/menus.xml',
        'views/portal_templates.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
