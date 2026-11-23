# -*- coding: utf-8 -*-
"""Give an ID to every homework / assignment that existed before the field was added."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("SELECT id, kind FROM school_oe_assignment WHERE work_code IS NULL ORDER BY id")
    rows = cr.fetchall()
    Sequence = env['ir.sequence']
    for work_id, kind in rows:
        code = 'school.oe.assignment.homework' if kind == 'homework' else 'school.oe.assignment'
        # plain SQL: published work locks its fields against write()
        cr.execute("UPDATE school_oe_assignment SET work_code = %s WHERE id = %s",
                   (Sequence.next_by_code(code), work_id))
    _logger.info("Online exam: assigned IDs to %s existing homework / assignment(s)", len(rows))
