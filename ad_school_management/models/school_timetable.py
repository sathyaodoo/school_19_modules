from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SchoolTimetable(models.Model):
    _name = 'school.timetable'
    _description = 'Class Timetable'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Name', compute='_compute_name', store=True)
    class_id = fields.Many2one('school.class', string='Class', required=True, tracking=True)
    section_id = fields.Many2one('school.section', string='Section', required=True, tracking=True)
    academic_year_id = fields.Many2one('school.academic.year', string='Academic Year', required=True, tracking=True)
    timetable_line_ids = fields.One2many('school.timetable.line', 'timetable_id', string='Timetable Lines')

    _class_sec_year_uniq = models.Constraint(
        'unique(class_id, section_id, academic_year_id)',
        'Timetable already exists for this Class, Section, and Academic Year!'
    )

    @api.depends('class_id', 'section_id', 'academic_year_id')
    def _compute_name(self):
        for rec in self:
            if rec.class_id and rec.section_id and rec.academic_year_id:
                rec.name = f"{rec.class_id.name} - {rec.section_id.name} ({rec.academic_year_id.name})"
            else:
                rec.name = "New Timetable"

class SchoolTimetableLine(models.Model):
    _name = 'school.timetable.line'
    _description = 'Timetable Line'
    _order = 'day_of_week, start_time'

    timetable_id = fields.Many2one('school.timetable', string='Timetable Reference', required=True, ondelete='cascade')
    day_of_week = fields.Selection([
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
        ('saturday', 'Saturday'),
        ('sunday', 'Sunday')
    ], string='Day of Week', required=True)
    
    subject_id = fields.Many2one('school.subject', string='Subject', required=True)
    teacher_id = fields.Many2one('school.teacher', string='Teacher', required=True)
    classroom = fields.Char(string='Classroom/Room', required=True)
    
    start_time = fields.Float(string='Start Time (Hour)', required=True, help="Use 9.5 for 09:30 AM")
    end_time = fields.Float(string='End Time (Hour)', required=True, help="Use 10.5 for 10:30 AM")

    @api.constrains('start_time', 'end_time')
    def _check_times(self):
        for line in self:
            if line.start_time >= line.end_time:
                raise ValidationError(_("Start time must be before end time!"))
            if line.start_time < 0 or line.start_time >= 24 or line.end_time < 0 or line.end_time >= 24:
                raise ValidationError(_("Time must be between 0 and 24 hours."))

    @api.constrains('day_of_week', 'start_time', 'end_time', 'teacher_id', 'classroom')
    def _check_conflicts(self):
        for line in self:
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
