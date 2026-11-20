# -*- coding: utf-8 -*-
"""19.0.1.12 (pre): clear the stale Student 360 form extension before the views reload.

The behaviour ratings moved from school.student.behaviour to the per-student rows
(school.student.behaviour.feedback). The database still holds the OLD arch of
view_student_form_inherit_360, which lists behaviour / discipline / participation /
teacher_observation on school.student.behaviour. views/school_student_views.xml is
loaded before views/school_student_360_views.xml, so reloading the student form
validates it together with that old extension and the upgrade stops with
"Field "behaviour" does not exist in model "school.student.behaviour"".

Replace the old arch with an empty extension; school_student_360_views.xml writes
the real arch again later in the same upgrade. No data is touched.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE ir_ui_view v
           SET arch_db = jsonb_build_object('en_US', '<data/>')
          FROM ir_model_data d
         WHERE d.model = 'ir.ui.view'
           AND d.res_id = v.id
           AND d.module = 'ad_school_management'
           AND d.name = 'view_student_form_inherit_360'
    """)
    _logger.info("Student 360: cleared the old form extension (%s view), reloaded from XML", cr.rowcount)
