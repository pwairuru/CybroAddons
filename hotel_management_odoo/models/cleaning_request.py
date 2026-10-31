# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


HK_STATUSES = [('dirty', 'Dirty'), ('clean', 'Clean'),
               ('inspected', 'Inspected'), ('ooo', 'Out of Order')]
HK_TASKS = [('departure', 'Departure Clean'), ('stayover', 'Stayover'),
            ('deep', 'Deep Clean'), ('inspection', 'Inspection'),
            ('public', 'Public Area')]


class CleaningRequest(models.Model):
    """Class for creating and assigning Cleaning Request"""
    _name = "cleaning.request"
    _inherit = ["mail.thread", "mail.activity.mixin", "avatar.mixin",
                "hotel.state.guarded"]
    _rec_name = "sequence"
    _description = "Cleaning Request"
    _avatar_name_field = "sequence"

    sequence = fields.Char(string="Sequence", readonly=True, default='New',
                           copy=False, tracking=True,
                           help="Sequence for identifying the request")
    state = fields.Selection([('draft', 'Draft'),
                              ('assign', 'Assigned'),
                              ('ongoing', 'Cleaning'),
                              ('support', 'Waiting For Support'),
                              ('done', 'Completed')],
                             string="State",
                             default='draft', help="State of cleaning request")
    cleaning_type = fields.Selection(selection=[('room', 'Room'),
                                                ('hotel', 'Hotel'),
                                                ('vehicle', 'Vehicle')],
                                     required=True, tracking=True,
                                     string="Cleaning Type",
                                     help="Choose what is to be cleaned")
    room_id = fields.Many2one('product.template', string="Room",
                              help="Choose the room")
    hotel = fields.Char(string="Hotel", help="Cleaning request space in hotel")
    vehicle_id = fields.Many2one('fleet.vehicle.model',
                                 string="Vehicle",
                                 help="Cleaning request from vehicle")
    support_team_ids = fields.Many2many('res.users',
                                        relation='cleaning_request_support_team_rel',
                                        column1='cleaning_id',
                                        column2='user_id',
                                        string="Support Team",
                                        help="Support team members")
    support_reason = fields.Char(string='Support', help="Support Reason")
    description = fields.Char(string="Description",
                              help="Description about the cleaning")
    team_id = fields.Many2one('cleaning.team', string="Team",
                              required=True,
                              tracking=True,
                              help="Choose the team")
    head_id = fields.Many2one('res.users', string="Head",
                              related='team_id.team_head_id',
                              help="Head of cleaning team")
    assigned_id = fields.Many2one('res.users', string="Assigned To",
                                  help="The team member to whom the request is"
                                       "Assigned To")
    domain_partner_ids = fields.Many2many('res.users',
                                          relation='cleaning_request_domain_partner_rel',
                                          column1='cleaning_id',
                                          column2='user_id',
                                          string="Domain Partner",
                                          help="Choose the Domain Partner")
    # Task 10 pro fields: task type (departure vs stayover), HK room
    # condition, SLA deadline/breach, company. Legacy `state` untouched
    # so rack dirty-count stays backward compatible.
    task_type = fields.Selection(selection=HK_TASKS, default='stayover',
                                 required=True, tracking=True,
                                 string="Task Type",
                                 help="Departure clean vs stayover service")
    room_status = fields.Selection(selection=HK_STATUSES, default='dirty',
                                   required=True, tracking=True,
                                   string="Room Condition",
                                   help="Housekeeping condition of the room")
    sla_deadline = fields.Datetime(string="SLA Deadline",
                                    help="Service must finish before this time")
    sla_breach = fields.Boolean(string="SLA Breach",
                                compute='_compute_sla_breach',
                                help="Deadline passed while request open. "
                                     "Non-stored so it is always fresh.")
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)

    _STATE_FLOW = {
        'draft': ('assign', 'done'),
        'assign': ('ongoing', 'support', 'done'),
        'ongoing': ('support', 'done'),
        'support': ('ongoing', 'done'),
        'done': (),
    }

    @api.model_create_multi
    def create(self, vals_list):
        """Sequence Generation"""
        for vals in vals_list:
            if vals.get('sequence', 'New') == 'New':
                vals['sequence'] = self.env['ir.sequence'].next_by_code(
                    'cleaning.request')
        return super().create(vals_list)

    @api.depends('sla_deadline', 'state', 'room_status')
    def _compute_sla_breach(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.sla_breach = bool(
                rec.sla_deadline and rec.state != 'done'
                and rec.room_status != 'inspected'
                and rec.sla_deadline < now)

    @api.onchange('team_id')
    def _onchange_team_id(self):
        """Function for updating the domain partner ids"""
        self.update(
            {'domain_partner_ids': self.team_id.member_ids.ids})

    def action_assign_cleaning(self):
        """Button action for updating the state to assign"""
        self._check_request_transition('assign')
        if not self.assigned_id:
            raise ValidationError(_('Please select an Assigned To person before assigning.'))
        if self.cleaning_type == 'room' and not self.room_id:
            raise ValidationError(_('Please choose a Room.'))
        if self.cleaning_type == 'hotel' and not self.hotel:
            raise ValidationError(_('Please enter the Hotel.'))
        if self.cleaning_type == 'vehicle' and not self.vehicle_id:
            raise ValidationError(_('Please choose a Vehicle.'))

        self.update({'state': 'assign'})

    def action_start_cleaning(self):
        """Button action for updating the state to ongoing"""
        self._check_request_transition('ongoing')
        self.write({'state': 'ongoing'})

    def action_done_cleaning(self):
        """Button action for  updating the state to done"""
        self._check_request_transition('done')
        self.write({'state': 'done'})

    # Task 10 pro transitions: dirty -> clean -> inspected, OOO closes.
    def _require_room_type(self):
        for rec in self:
            if rec.cleaning_type != 'room' or not rec.room_id:
                raise ValidationError(
                    _('Room condition transitions need a room request.'))

    def action_mark_clean(self):
        """Cleaner marks a dirty room clean."""
        self._require_room_type()
        for rec in self:
            if rec.room_status != 'dirty':
                raise ValidationError(
                    _('Only dirty rooms can be marked clean (now %s).')
                    % rec.room_status)
        self.write({'room_status': 'clean'})
        return self

    def action_mark_dirty(self):
        """Reopen a room as dirty (e.g. failed inspection)."""
        self._require_room_type()
        for rec in self:
            if rec.room_status == 'inspected':
                raise ValidationError(
                    _('Inspected rooms reopen via a new request.'))
        self.write({'room_status': 'dirty'})
        return self

    def action_inspect(self):
        """Supervisor verifies a clean room."""
        self._require_room_type()
        for rec in self:
            if rec.state == 'done':
                raise ValidationError(
                    _('Completed requests cannot be inspected; '
                      'open a new request.'))
            if rec.room_status != 'clean':
                raise ValidationError(
                    _('Only clean rooms can be inspected (now %s).')
                    % rec.room_status)
        self.write({'room_status': 'inspected'})
        return self

    def action_mark_ooo(self):
        """Pull room out of order; closes the request."""
        self._require_room_type()
        for rec in self:
            if rec.room_status == 'inspected':
                raise ValidationError(
                    _('Inspected rooms go OOO via a new request.'))
        self.write({'room_status': 'ooo', 'state': 'done'})
        return self

    def action_assign_support(self):
        """Button action for updating the state to support"""
        self._check_request_transition('support')
        if self.support_reason:
            self.write({'state': 'support'})
        else:
            raise ValidationError(_('Please enter the reason'))

    def action_assign_assign_support(self):
        """Button action for updating the state to ongoing"""
        if self.state != 'support' or not self.support_team_ids:
            raise ValidationError(_('Please choose a support'))
        self.write({'state': 'ongoing'})

    def action_maintain_request(self):
        """Button action for creating the maintenance request"""
        domain = [('state', 'not in', ('done', 'cancel'))]
        if self.cleaning_type == 'room' and self.room_id:
            domain.append(
                ('room_maintenance_ids', 'in', self.room_id.ids))
        elif self.cleaning_type == 'vehicle' and self.vehicle_id:
            domain.append(
                ('vehicle_maintenance_id', '=', self.vehicle_id.id))
        else:
            domain.append(('id', '=', 0))
        existing = self.env['maintenance.request'].search(domain,
                                                          limit=1)
        if existing:
            raise ValidationError(
                _('An open maintenance request already exists (%s).')
                % (existing.sequence or existing.name))
        vals = {
            'name': 'Maintenance Request - %s' % self.sequence,
            'date': fields.Date.today(),
            'state': 'draft',
            'type': self.cleaning_type,
            'is_hotel': True,
            'company_id': self.company_id.id,
        }
        if self.cleaning_type == 'room':
            vals['room_maintenance_ids'] = [(6, 0, self.room_id.ids)]
        elif self.cleaning_type == 'vehicle':
            vals['vehicle_maintenance_id'] = self.vehicle_id.id
        elif self.cleaning_type == 'hotel':
            vals['hotel_maintenance'] = self.hotel
        self.env['maintenance.request'].with_company(
            self.company_id).sudo().create(vals)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': "Maintenance Request Sent Successfully",
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }