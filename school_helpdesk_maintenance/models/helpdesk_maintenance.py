from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

# helpdesk priority (Low, Medium, High, Very High) -> maintenance priority (Very Low, Low, Normal, High)
PRIORITY_MAP = {'0': '1', '1': '2', '2': '3', '3': '3'}


class DevHelpdeskTicket(models.Model):
    _inherit = 'dev.helpdesk.ticket'

    is_maintenance = fields.Boolean(
        string='Maintenance Ticket', tracking=True,
        help="Tick for repair / maintenance complaints. A Maintenance Request is created and linked on save.")
    maintenance_location = fields.Char(string='Location', tracking=True,
                                       help="Block / Building / Room, e.g. Main Block - Room 12")
    maintenance_equipment_id = fields.Many2one('maintenance.equipment', string='Equipment / Asset')
    maintenance_request_id = fields.Many2one('maintenance.request', string='Maintenance Request',
                                             readonly=True, copy=False)
    maintenance_stage_id = fields.Many2one(related='maintenance_request_id.stage_id',
                                           string='Maintenance Status')

    def _assignee_field(self):
        """Name of the helpdesk 'Assigned To' (res.users) field."""
        for name, field in self._fields.items():
            if field.type == 'many2one' and field.comodel_name == 'res.users' \
                    and (field.string or '').strip().lower() == 'assigned to':
                return name
        return False

    @api.model_create_multi
    def create(self, vals_list):
        tickets = super().create(vals_list)
        tickets.filtered(lambda t: t.is_maintenance and not t.maintenance_request_id)._create_maintenance_request()
        return tickets

    def write(self, vals):
        if vals.get('is_maintenance') is False and self.filtered('maintenance_request_id'):
            raise ValidationError(_(
                "This ticket already has a Maintenance Request. Cancel the request instead of unticking."))
        res = super().write(vals)
        if vals.get('is_maintenance'):
            self.filtered(lambda t: t.is_maintenance and not t.maintenance_request_id)._create_maintenance_request()
        # ticket priority changed -> update request priority
        if 'priority' in vals:
            for ticket in self.filtered('maintenance_request_id'):
                ticket.maintenance_request_id.sudo().write({
                    'priority': PRIORITY_MAP.get(ticket.priority or '0', '1')})
        # ticket Assigned To changed -> update request Responsible (+ Assigned On)
        assignee = self._assignee_field()
        if assignee and assignee in vals:
            for ticket in self.filtered('maintenance_request_id'):
                ticket.maintenance_request_id.sudo().write({'user_id': ticket[assignee].id or False})
        return res

    def _create_maintenance_request(self):
        Request = self.env['maintenance.request'].sudo()
        assignee = self._assignee_field()
        for ticket in self:
            title = ticket.name or (ticket.subject_id.display_name if ticket.subject_id else '') or _('Complaint')
            vals = {
                'name': '%s - %s' % (ticket.ticket_sequnce or '', title),
                'description': ticket.notes,
                'priority': PRIORITY_MAP.get(ticket.priority or '0', '1'),
                'equipment_id': ticket.maintenance_equipment_id.id,
                'maintenance_type': 'corrective',
                'helpdesk_ticket_id': ticket.id,
                'school_location': ticket.maintenance_location,
                'company_id': ticket.company_id.id or self.env.company.id,
            }
            if assignee and ticket[assignee]:
                vals['user_id'] = ticket[assignee].id
            request = Request.create(vals)
            ticket.maintenance_request_id = request.id
            # copy ticket attachments (photos / documents) to the request
            ticket._sync_attachments_to_request()
            ticket.message_post(body=_("Maintenance Request %s created.") % request.display_name)

    def _sync_attachments_to_request(self):
        """Copy ticket attachments that are not yet on the linked maintenance request."""
        Attachment = self.env['ir.attachment'].sudo()
        for ticket in self.filtered('maintenance_request_id'):
            request = ticket.maintenance_request_id
            done = set(Attachment.search([
                ('res_model', '=', 'maintenance.request'),
                ('res_id', '=', request.id)]).mapped('checksum'))
            for att in Attachment.search([
                    ('res_model', '=', 'dev.helpdesk.ticket'), ('res_id', '=', ticket.id)]):
                if att.checksum not in done:
                    att.copy({'res_model': 'maintenance.request', 'res_id': request.id})
                    done.add(att.checksum)

    def action_view_maintenance_request(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Maintenance Request'),
            'res_model': 'maintenance.request',
            'res_id': self.maintenance_request_id.id,
            'view_mode': 'form',
        }


class MaintenanceRequest(models.Model):
    _inherit = 'maintenance.request'

    helpdesk_ticket_id = fields.Many2one('dev.helpdesk.ticket', string='Helpdesk Ticket', readonly=True,
                                         copy=False, index=True)
    school_location = fields.Char(string='Location')
    assigned_on = fields.Datetime(string='Assigned On', readonly=True, copy=False, tracking=True,
                                  help="Date and time when the Responsible person was assigned.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('user_id') and not vals.get('assigned_on'):
                vals['assigned_on'] = fields.Datetime.now()
        records = super().create(vals_list)
        records._update_repeat_fault_by_text_location()
        return records

    def _update_repeat_fault_by_text_location(self):
        """Repeated-fault check using the text Location, when the request has no
        equipment and no location master (the standard check skips such requests)."""
        if 'repeat_fault' not in self._fields or 'repeat_count' not in self._fields:
            return
        params = self.env['ir.config_parameter'].sudo()
        days = int(params.get_param('school_maintenance.repeat_days', 30))
        threshold = int(params.get_param('school_maintenance.repeat_tickets', 2))
        for rec in self:
            has_location_master = 'school_location_id' in self._fields and rec.school_location_id
            if rec.equipment_id or has_location_master or not rec.school_location:
                continue
            since = (rec.request_date or fields.Date.context_today(rec)) - timedelta(days=days)
            earlier = self.sudo().search_count([
                ('school_location', '=ilike', rec.school_location.strip()),
                ('equipment_id', '=', False),
                ('id', '!=', rec.id),
                ('request_date', '>=', since)])
            rec.sudo().write({'repeat_count': earlier, 'repeat_fault': earlier + 1 >= threshold})

    def write(self, vals):
        if 'user_id' in vals:
            vals['assigned_on'] = fields.Datetime.now() if vals['user_id'] else False
        old_stage = {r.id: r.stage_id for r in self}
        res = super().write(vals)
        if 'stage_id' in vals:
            for req in self.filtered('helpdesk_ticket_id'):
                if req.stage_id != old_stage.get(req.id):
                    req.helpdesk_ticket_id.sudo().message_post(
                        body=_("Maintenance status changed to %s.") % req.stage_id.name)
        return res


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def _sync_helpdesk_ticket_attachments(self):
        ticket_ids = {a.res_id for a in self
                      if a.res_model == 'dev.helpdesk.ticket' and a.res_id}
        if ticket_ids:
            tickets = self.env['dev.helpdesk.ticket'].sudo().browse(list(ticket_ids)).exists()
            tickets.filtered('maintenance_request_id')._sync_attachments_to_request()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_helpdesk_ticket_attachments()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'res_id' in vals or 'res_model' in vals:
            self._sync_helpdesk_ticket_attachments()
        return res