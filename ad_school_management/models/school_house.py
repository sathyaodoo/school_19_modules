from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

BOARD_SELECTION = [('cbse', 'CBSE'), ('state', 'State Board')]


class SchoolHouse(models.Model):
    """Student groups (houses) per board.

    CBSE:  Venus, Jupiter, Mercury, Uranus
    State: Ruby, Diamond, Emerald, Sapphire
    """
    _name = 'school.house'
    _description = 'Student Group (House)'
    _order = 'board, sequence, name'

    name = fields.Char(string='Group Name', required=True)
    board = fields.Selection(BOARD_SELECTION, string='Board', required=True, default='cbse')
    sequence = fields.Integer(default=10)
    color = fields.Integer(string='Color')
    active = fields.Boolean(default=True)
    description = fields.Text()
    student_ids = fields.One2many('school.student', 'house_id', string='Students')
    student_count = fields.Integer(compute='_compute_student_count')

    _name_board_uniq = models.Constraint(
        'unique(name, board)', 'This group already exists for this board!'
    )

    @api.depends('student_ids')
    def _compute_student_count(self):
        counts = dict(self.env['school.student']._read_group(
            [('house_id', 'in', self.ids)], ['house_id'], ['__count']))
        for house in self:
            house.student_count = counts.get(house, 0)

    @api.model_create_multi
    def create(self, vals_list):
        houses = super().create(vals_list)
        self.env['school.class'].search([('board', 'in', houses.mapped('board'))])._ensure_class_groups()
        return houses

    def action_view_students(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Students – %s', self.name),
            'res_model': 'school.student',
            'view_mode': 'list,form',
            'domain': [('house_id', '=', self.id)],
            'context': {'default_house_id': self.id},
        }


class SchoolClassHouse(models.Model):
    """One group inside one class (e.g. "Class 10 – Venus") with its two
    student leaders: one male and one female."""
    _name = 'school.class.house'
    _description = 'Class Group'
    _order = 'class_id, house_id'

    name = fields.Char(compute='_compute_name', store=True)
    class_id = fields.Many2one('school.class', string='Class', required=True, ondelete='cascade')
    house_id = fields.Many2one('school.house', string='Group', required=True, ondelete='cascade')
    board = fields.Selection(related='house_id.board', store=True)
    color = fields.Integer(related='house_id.color')
    male_leader_id = fields.Many2one(
        'school.student', string='Male Student Leader',
        domain="[('class_id', '=', class_id), ('house_id', '=', house_id), ('gender', '=', 'male')]")
    female_leader_id = fields.Many2one(
        'school.student', string='Female Student Leader',
        domain="[('class_id', '=', class_id), ('house_id', '=', house_id), ('gender', '=', 'female')]")
    student_ids = fields.Many2many('school.student', compute='_compute_students', string='Students')
    student_count = fields.Integer(compute='_compute_students', string='No. of Students')
    male_count = fields.Integer(compute='_compute_students', string='Boys')
    female_count = fields.Integer(compute='_compute_students', string='Girls')

    _class_house_uniq = models.Constraint(
        'unique(class_id, house_id)', 'This group already exists for this class!'
    )

    @api.depends('class_id.name', 'house_id.name')
    def _compute_name(self):
        for group in self:
            group.name = '%s – %s' % (group.class_id.name or '', group.house_id.name or '')

    def _compute_students(self):
        for group in self:
            students = self.env['school.student'].search([
                ('class_id', '=', group.class_id.id), ('house_id', '=', group.house_id.id)])
            group.student_ids = students
            group.student_count = len(students)
            group.male_count = len(students.filtered(lambda s: s.gender == 'male'))
            group.female_count = len(students.filtered(lambda s: s.gender == 'female'))

    @api.constrains('class_id', 'house_id')
    def _check_board(self):
        for group in self:
            if group.class_id.board and group.house_id.board != group.class_id.board:
                raise ValidationError(_(
                    "Group %(house)s belongs to the %(board)s board and cannot be used in %(cls)s.",
                    house=group.house_id.name,
                    board=dict(BOARD_SELECTION)[group.house_id.board],
                    cls=group.class_id.name,
                ))

    @api.constrains('male_leader_id', 'female_leader_id', 'class_id', 'house_id')
    def _check_leaders(self):
        for group in self:
            for leader, gender, label in ((group.male_leader_id, 'male', _('male')),
                                          (group.female_leader_id, 'female', _('female'))):
                if not leader:
                    continue
                if leader.class_id != group.class_id or leader.house_id != group.house_id:
                    raise ValidationError(_(
                        "%(student)s is not a member of %(group)s, so cannot be its leader.",
                        student=leader.name, group=group.name))
                if leader.gender != gender:
                    raise ValidationError(_(
                        "The %(label)s leader of %(group)s must be a %(label)s student.",
                        label=label, group=group.name))

    def action_view_students(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'school.student',
            'view_mode': 'list,form',
            'domain': [('class_id', '=', self.class_id.id), ('house_id', '=', self.house_id.id)],
            'context': {'default_class_id': self.class_id.id, 'default_house_id': self.house_id.id},
        }


class SchoolClass(models.Model):
    _inherit = 'school.class'

    board = fields.Selection(BOARD_SELECTION, string='Board', default='cbse', tracking=True,
                             help='Decides which student groups (houses) this class uses.')
    class_house_ids = fields.One2many('school.class.house', 'class_id', string='Student Groups')

    def _ensure_class_groups(self):
        """Create the missing class groups for every house of the class board."""
        Group = self.env['school.class.house'].sudo()
        for school_class in self.filtered('board'):
            houses = self.env['school.house'].search([('board', '=', school_class.board)])
            missing = houses - school_class.class_house_ids.house_id
            Group.create([{'class_id': school_class.id, 'house_id': h.id} for h in missing])

    @api.model_create_multi
    def create(self, vals_list):
        classes = super().create(vals_list)
        classes._ensure_class_groups()
        return classes

    def write(self, vals):
        if 'board' in vals:
            for school_class in self:
                if school_class.board and vals['board'] != school_class.board and \
                        self.env['school.student'].search_count([('class_id', '=', school_class.id),
                                                                  ('house_id', '!=', False)]):
                    raise UserError(_(
                        "Students of %s are already assigned to groups. "
                        "Clear their groups before changing the board.", school_class.name))
        res = super().write(vals)
        if 'board' in vals:
            self.class_house_ids.filtered(lambda g: g.board != g.class_id.board).unlink()
            self._ensure_class_groups()
        return res

    def action_auto_assign_groups(self):
        """Assign every student of the class that has no group yet."""
        for school_class in self:
            school_class._ensure_class_groups()
            students = self.env['school.student'].search(
                [('class_id', '=', school_class.id), ('house_id', '=', False)], order='id')
            students._auto_assign_house()
        return True


class SchoolStudent(models.Model):
    _inherit = 'school.student'

    class_board = fields.Selection(related='class_id.board', string='Board')
    house_id = fields.Many2one(
        'school.house', string='Group (House)', tracking=True, index=True,
        domain="[('board', '=', class_board)]",
        help='Assigned automatically after admission (balanced by gender). Can be changed.')
    class_house_id = fields.Many2one('school.class.house', string='Class Group',
                                     compute='_compute_class_house')
    leader_role = fields.Char(string='Leader Role', compute='_compute_class_house')

    def _compute_class_house(self):
        Group = self.env['school.class.house']
        for student in self:
            group = Group.search([('class_id', '=', student.class_id.id),
                                  ('house_id', '=', student.house_id.id)], limit=1) \
                if student.class_id and student.house_id else Group
            student.class_house_id = group
            if group and group.male_leader_id == student:
                student.leader_role = _('Male Leader – %s', group.name)
            elif group and group.female_leader_id == student:
                student.leader_role = _('Female Leader – %s', group.name)
            else:
                student.leader_role = False

    @api.constrains('house_id', 'class_id')
    def _check_house_board(self):
        for student in self:
            if student.house_id and student.class_id.board and \
                    student.house_id.board != student.class_id.board:
                raise ValidationError(_(
                    "%(student)s is in %(cls)s (%(board)s) and cannot be in group %(house)s.",
                    student=student.name, cls=student.class_id.name,
                    board=dict(BOARD_SELECTION)[student.class_id.board], house=student.house_id.name))

    @api.onchange('class_id')
    def _onchange_class_id_house(self):
        if self.house_id and self.class_id.board and self.house_id.board != self.class_id.board:
            self.house_id = False

    def _auto_assign_house(self):
        """Put each student in the group of their class that currently has
        the fewest students of the same gender (then fewest overall)."""
        for student in self:
            if student.house_id or not student.class_id.board:
                continue
            houses = self.env['school.house'].search([('board', '=', student.class_id.board)])
            if not houses:
                continue
            student.class_id._ensure_class_groups()
            classmates = self.search([('class_id', '=', student.class_id.id),
                                      ('house_id', 'in', houses.ids), ('id', '!=', student.id)])

            def load(house):
                members = classmates.filtered(lambda s: s.house_id == house)
                same_gender = members.filtered(lambda s: s.gender == student.gender)
                return (len(same_gender), len(members), house.sequence, house.id)

            student.house_id = min(houses, key=load)

    @api.model_create_multi
    def create(self, vals_list):
        students = super().create(vals_list)
        if not self.env.context.get('school_skip_house_assign'):
            students.filtered(lambda s: not s.house_id)._auto_assign_house()
        return students

    def write(self, vals):
        groups = self.env['school.class.house']
        if {'class_id', 'house_id', 'gender'} & set(vals):
            # A student who changes class, group or gender may stop being a leader.
            groups = groups.sudo().search([
                '|', ('male_leader_id', 'in', self.ids), ('female_leader_id', 'in', self.ids)])

        # Moving to a class of the other board: clear the old group in the same
        # write (so the board check passes), then assign a group of the new board.
        reassign = self.browse()
        if vals.get('class_id') and 'house_id' not in vals:
            new_class = self.env['school.class'].browse(vals['class_id'])
            reassign = self.filtered(lambda s: s.house_id and new_class.board
                                     and s.house_id.board != new_class.board)
        if reassign:
            res = super(SchoolStudent, reassign).write(dict(vals, house_id=False))
            if self - reassign:
                res = super(SchoolStudent, self - reassign).write(vals)
        else:
            res = super().write(vals)

        for group in groups:
            updates = {}
            male, female = group.male_leader_id, group.female_leader_id
            if male and (male.class_id != group.class_id or male.house_id != group.house_id
                         or male.gender != 'male'):
                updates['male_leader_id'] = False
            if female and (female.class_id != group.class_id or female.house_id != group.house_id
                           or female.gender != 'female'):
                updates['female_leader_id'] = False
            if updates:
                group.write(updates)

        if reassign and not self.env.context.get('school_skip_house_assign'):
            reassign._auto_assign_house()
        return res