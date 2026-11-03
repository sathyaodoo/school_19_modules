import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class SchoolTimetable(models.Model):
    _name = 'school.timetable'
    _description = 'Class Timetable'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Name', compute='_compute_name', store=True)
    class_id = fields.Many2one('school.class', string='Class', required=True, tracking=True)
    section_id = fields.Many2one('school.section', string='Section', required=True, tracking=True)
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', required=True, tracking=True)
    # Entered ONCE per timetable (the room this class/section sits in);
    # every schedule line takes it from here (see SchoolTimetableLine.classroom).
    classroom = fields.Char(string='Classroom/Room', required=True, tracking=True)
    timetable_line_ids = fields.One2many('school.timetable.line', 'timetable_id', string='Timetable Lines')

    _class_sec_year_uniq = models.Constraint(
        'unique(class_id, section_id, academic_year_id)',
        'Timetable already exists for this Class, Section, and Academic Year!'
    )

    # One list per weekday tab of the form. All of them show the SAME
    # records as timetable_line_ids, filtered by day.
    monday_line_ids = fields.One2many(
        'school.timetable.line', 'timetable_id', string='Monday',
        domain=[('day_of_week', '=', 'monday')], context={'default_day_of_week': 'monday'})
    tuesday_line_ids = fields.One2many(
        'school.timetable.line', 'timetable_id', string='Tuesday',
        domain=[('day_of_week', '=', 'tuesday')], context={'default_day_of_week': 'tuesday'})
    wednesday_line_ids = fields.One2many(
        'school.timetable.line', 'timetable_id', string='Wednesday',
        domain=[('day_of_week', '=', 'wednesday')], context={'default_day_of_week': 'wednesday'})
    thursday_line_ids = fields.One2many(
        'school.timetable.line', 'timetable_id', string='Thursday',
        domain=[('day_of_week', '=', 'thursday')], context={'default_day_of_week': 'thursday'})
    friday_line_ids = fields.One2many(
        'school.timetable.line', 'timetable_id', string='Friday',
        domain=[('day_of_week', '=', 'friday')], context={'default_day_of_week': 'friday'})
    saturday_line_ids = fields.One2many(
        'school.timetable.line', 'timetable_id', string='Saturday',
        domain=[('day_of_week', '=', 'saturday')], context={'default_day_of_week': 'saturday'})

    @api.model
    def default_get(self, fields_list):
        """Open a new timetable with all 8 periods already listed on every
        day tab: the subject, teacher and times are entered by the user."""
        res = super().default_get(fields_list)
        periods = [key for key, _label in self.env['school.timetable.line']._fields['period'].selection]
        for day in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'):
            field_name = f'{day}_line_ids'
            if field_name in fields_list and not res.get(field_name):
                res[field_name] = [
                    fields.Command.create({
                        'day_of_week': day,
                        'period': period,
                    })
                    for period in periods
                ]
        return res

    DAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday')

    @api.model_create_multi
    def create(self, vals_list):
        timetables = super().create(vals_list)
        timetables._ensure_period_lines()
        return timetables

    def _ensure_period_lines(self):
        """Make sure every day (Mon-Sat) has all 8 periods, so they are
        always displayed automatically and never picked by hand."""
        Line = self.env['school.timetable.line'].with_context(school_timetable_no_notify=True)
        periods = [key for key, _label in Line._fields['period'].selection]
        vals_list = []
        for timetable in self:
            existing = {(l.day_of_week, l.period) for l in timetable.timetable_line_ids}
            for day in self.DAYS:
                for period in periods:
                    if (day, period) not in existing:
                        vals_list.append({
                            'timetable_id': timetable.id,
                            'day_of_week': day,
                            'period': period,
                        })
        if vals_list:
            Line.create(vals_list)

    def _register_hook(self):
        """Complete the periods of existing timetables when the server
        loads/upgrades the module (no separate data file needed)."""
        res = super()._register_hook()
        try:
            with self.env.cr.savepoint():
                self.sudo().search([])._ensure_period_lines()
        except Exception:
            _logger.exception("Could not complete the timetable periods")
        return res

    @api.depends('class_id', 'section_id', 'academic_year_id')
    def _compute_name(self):
        for rec in self:
            if rec.class_id and rec.section_id and rec.academic_year_id:
                rec.name = f"{rec.class_id.name} - {rec.section_id.name} ({rec.academic_year_id.name})"
            else:
                rec.name = "New Timetable"

    def write(self, vals):
        result = super().write(vals)
        if {'classroom', 'class_id', 'section_id', 'academic_year_id'} & set(vals):
            # Every teacher of this timetable is told about a changed room / class.
            self.timetable_line_ids._school_queue_teacher_notification()
        return result

    @api.constrains('classroom', 'academic_year_id')
    def _check_classroom_conflicts(self):
        """Changing the timetable's room must not double-book it with another
        class at the same time. The lines' room is a stored related field, so
        their own constraint isn't triggered by this change: run it here."""
        self.timetable_line_ids._check_conflicts()

class SchoolTimetableLine(models.Model):
    _name = 'school.timetable.line'
    _description = 'Timetable Line'
    _order = 'day_sequence, start_time, id'

    timetable_id = fields.Many2one('school.timetable', string='Timetable Reference', required=True, ondelete='cascade')
    # Stored copy of the class timetable's name ("Class-01 - Sec-A (2026-2027)"),
    # so teachers can see the class of their periods without having access to
    # the class timetables themselves.
    class_name = fields.Char(related='timetable_id.name', string='Class', store=True)
    day_of_week = fields.Selection([
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
        ('saturday', 'Saturday'),
        ('sunday', 'Sunday')
    ], string='Day of Week', required=True)
    period = fields.Selection([
        ('first period', 'First Period'),
        ('second period', 'Second Period'),
        ('third period', 'Third Period'),
        ('fourth period', 'Fourth Period'),
        ('fifth period', 'Fifth Period'),
        ('sixth period', 'Sixth Period'),
        ('seventh period', 'Seventh Period'),
        ('eighth period', 'Eighth Period'),
    ], string='Period', required=True)
    # Monday=1 ... Sunday=7, so lines sort in week order (not alphabetically).
    day_sequence = fields.Integer(compute='_compute_day_sequence', store=True, index=True)
    
    subject_id = fields.Many2one('school.subject', string='Subject')
    teacher_id = fields.Many2one('school.teacher', string='Teacher')
    # Taken from the timetable header (entered once there). Kept as a stored
    # field on the line so substitutions, the substitute-teacher e-mail, the
    # student portal and the room-conflict check keep working unchanged.
    classroom = fields.Char(
        string='Classroom/Room', related='timetable_id.classroom', store=True, readonly=True)
    
    # aggregator=False: times must never be added up in grouped lists
    start_time = fields.Float(string='Start Time (Hour)', default=0.0, aggregator=False,
                              help="Use 9.5 for 09:30 AM")
    end_time = fields.Float(string='End Time (Hour)', default=0.0, aggregator=False,
                            help="Use 10.5 for 10:30 AM")

    @api.depends('day_of_week')
    def _compute_day_sequence(self):
        days = [key for key, _label in self._fields['day_of_week'].selection]
        for line in self:
            line.day_sequence = days.index(line.day_of_week) + 1 if line.day_of_week else 0

    # ------------------------------------------------------------------
    # Tell teachers when their timetable changes
    # ------------------------------------------------------------------
    _TEACHER_FIELDS = {'teacher_id', 'day_of_week', 'period', 'start_time', 'end_time', 'subject_id', 'timetable_id'}

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._school_queue_teacher_notification()
        return lines

    def write(self, vals):
        if self._TEACHER_FIELDS & set(vals):
            self._school_queue_teacher_notification()  # teachers before the change
        result = super().write(vals)
        if self._TEACHER_FIELDS & set(vals):
            self._school_queue_teacher_notification()  # teachers after the change
        return result

    def unlink(self):
        self._school_queue_teacher_notification()
        return super().unlink()

    def _school_queue_teacher_notification(self):
        """Remember the teachers whose timetable changed. They get ONE
        in-app notification each (never an e-mail), when the transaction is
        committed: saving a timetable with 30 periods notifies each teacher
        once, not 30 times. See school.teacher._school_notify_timetable_updated."""
        ctx = self.env.context
        if ctx.get('install_mode') or ctx.get('import_file') or ctx.get('school_timetable_no_notify'):
            return
        teacher_ids = set(self.teacher_id.ids)
        if not teacher_ids:
            return
        precommit = self.env.cr.precommit
        pending = precommit.data.setdefault('school_timetable_teachers', set())
        if not pending:
            precommit.add(self._school_send_teacher_notifications)
        pending.update(teacher_ids)

    def _school_send_teacher_notifications(self):
        teacher_ids = self.env.cr.precommit.data.pop('school_timetable_teachers', set())
        teachers = self.env['school.teacher'].sudo().browse(teacher_ids).exists()
        teachers._school_notify_timetable_updated()

    # "Print My Timetable" button removed from the My Timetable menu (not required).
    # @api.model
    # def action_print_my_timetable(self):
    #     """'Print My Timetable' button of the My Timetable menu."""
    #     teacher = self.env['school.teacher'].sudo().search([('user_id', '=', self.env.uid)], limit=1)
    #     if not teacher:
    #         raise UserError(_("Your user is not linked to a teacher."))
    #     return teacher.action_print_timetable()

    @api.constrains('subject_id', 'teacher_id')
    def _check_subject_teacher(self):
        for line in self:
            if bool(line.subject_id) != bool(line.teacher_id):
                raise ValidationError(_(
                    "Please select both a Subject and a Teacher for %s on %s "
                    "(or leave both empty for a free period)."
                ) % (dict(self._fields['period'].selection).get(line.period, ''),
                     dict(self._fields['day_of_week'].selection).get(line.day_of_week, '')))

    @api.constrains('start_time', 'end_time')
    def _check_times(self):
        for line in self:
            if not line.subject_id and not line.teacher_id:
                continue  # free period: no times needed
            if line.start_time >= line.end_time:
                raise ValidationError(_("Start time must be before end time!"))
            if line.start_time < 0 or line.start_time >= 24 or line.end_time < 0 or line.end_time >= 24:
                raise ValidationError(_("Time must be between 0 and 24 hours."))

    @api.constrains('day_of_week', 'period', 'start_time', 'end_time', 'teacher_id', 'classroom')
    def _check_conflicts(self):
        for line in self:
            if not line.teacher_id:
                continue  # free period
            teacher_conflict = self.search([
                ('id', '!=', line.id),
                ('day_of_week', '=', line.day_of_week),
                ('teacher_id', '=', line.teacher_id.id),
                ('timetable_id.academic_year_id', '=', line.timetable_id.academic_year_id.id),
                ('start_time', '<', line.end_time),
                ('end_time', '>', line.start_time),
            ])
            if teacher_conflict:
                raise ValidationError(_(
                    "Teacher %s has a schedule conflict on %s between %.2f and %.2f!"
                ) % (line.teacher_id.name, dict(self._fields['day_of_week'].selection).get(line.day_of_week), line.start_time, line.end_time))

            room_conflict = self.search([
                ('id', '!=', line.id),
                ('day_of_week', '=', line.day_of_week),
                ('classroom', '=', line.classroom),
                ('timetable_id.academic_year_id', '=', line.timetable_id.academic_year_id.id),
                ('start_time', '<', line.end_time),
                ('end_time', '>', line.start_time),
            ])
            if room_conflict:
                raise ValidationError(_(
                    "Classroom %s is already occupied on %s between %.2f and %.2f!"
                ) % (line.classroom, dict(self._fields['day_of_week'].selection).get(line.day_of_week), line.start_time, line.end_time))