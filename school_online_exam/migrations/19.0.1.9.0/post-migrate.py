# -*- coding: utf-8 -*-
"""Give an Exam ID to every online exam that existed before the field was added."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("SELECT id FROM school_oe_exam WHERE exam_code IS NULL ORDER BY id")
    exam_ids = [row[0] for row in cr.fetchall()]
    Sequence = env['ir.sequence']
    for exam_id in exam_ids:
        # plain SQL: published exams lock their fields against write()
        cr.execute("UPDATE school_oe_exam SET exam_code = %s WHERE id = %s",
                   (Sequence.next_by_code('school.oe.exam'), exam_id))
    _logger.info("Online exam: assigned Exam IDs to %s existing exam(s)", len(exam_ids))
