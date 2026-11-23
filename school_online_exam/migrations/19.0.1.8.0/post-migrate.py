# -*- coding: utf-8 -*-
"""Give a Question ID to every question that existed before the field was added."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Question = env['school.oe.question'].with_context(active_test=False)
    questions = Question.search(
        [('question_code', '=', False)], order='id')
    Sequence = env['ir.sequence']
    for question in questions:
        question.question_code = Sequence.next_by_code('school.oe.question')
    _logger.info("Online exam: assigned Question IDs to %s existing question(s)", len(questions))
