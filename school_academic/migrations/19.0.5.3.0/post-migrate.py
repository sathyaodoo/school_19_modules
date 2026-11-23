# -*- coding: utf-8 -*-
"""Give a Plan ID to every lesson plan that existed before the field was added."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("SELECT id FROM school_lesson_plan WHERE plan_code IS NULL ORDER BY id")
    plan_ids = [row[0] for row in cr.fetchall()]
    Sequence = env['ir.sequence']
    for plan_id in plan_ids:
        # plain SQL: submitted / approved plans are locked against write()
        cr.execute("UPDATE school_lesson_plan SET plan_code = %s WHERE id = %s",
                   (Sequence.next_by_code('school.lesson.plan'), plan_id))
    _logger.info("Academic: assigned Plan IDs to %s existing lesson plan(s)", len(plan_ids))
