# -*- coding: utf-8 -*-
"""19.0.1.12: behaviour ratings and teacher observation moved per student.

The new columns on school_student_behaviour_feedback were filled with the
field defaults ('3' / empty) when they were created. Copy the review header
values into every EXISTING feedback row, so old reviews keep what the teacher
entered, then recompute the stored average from the copied ratings.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE school_student_behaviour_feedback f
           SET behaviour = r.behaviour,
               discipline = r.discipline,
               participation = r.participation,
               teacher_observation = r.teacher_observation
          FROM school_student_behaviour r
         WHERE f.review_id = r.id
    """)
    _logger.info("Behaviour feedback: copied header ratings into %s existing row(s)", cr.rowcount)
    cr.execute("""
        UPDATE school_student_behaviour_feedback
           SET average_rating = ROUND((
                   COALESCE(behaviour::int, 0) + COALESCE(discipline::int, 0) + COALESCE(participation::int, 0)
               )::numeric / NULLIF(
                   (behaviour IS NOT NULL)::int + (discipline IS NOT NULL)::int + (participation IS NOT NULL)::int, 0
               ), 1)
    """)
    cr.execute("UPDATE school_student_behaviour_feedback SET average_rating = 0 WHERE average_rating IS NULL")
