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
from odoo import api, fields, models,_
from odoo.addons.base.models.avatar_mixin import generate_text_avatar_svg
from odoo.exceptions import ValidationError
class ProductTemplate(models.Model):
    _inherit = "product.template"
    _description = "Product Template"

    is_room = fields.Boolean(string="Room", help="is room", tracking=True)
    status = fields.Selection([("available", "Available"),
                               ("reserved", "Reserved"),
                               ("occupied", "Occupied")],
                              default="available", string="Status",
                              help="Status of The Room",
                              tracking=True)
    is_room_avail = fields.Boolean(default=True, string="Available",
                                   help="Check if the room is available",
                                   tracking=True)
    room_amenities_ids = fields.Many2many("hotel.amenity",
                                          string="Room Amenities",
                                          help="List of room amenities.")
    floor_id = fields.Many2one('hotel.floor', string='Floor',
                               help="Automatically selects the Floor",
                               tracking=True)
    user_id = fields.Many2one('res.users', string="User",
                              related='floor_id.user_id',
                              help="Automatically selects the manager",
                              tracking=True)
    room_type = fields.Selection([('single', 'Single'),
                                   ('double', 'Double'),
                                   ('dormitory', 'Dormitory')],
                                  required=True, string="Room Type",
                                  help="Automatically selects the Room Type",
                                  tracking=True,
                                  default="single")
    room_type_id = fields.Many2one('hotel.room.type', string="Room Type",
                                   index=True, tracking=True)
    website_published = fields.Boolean(
        string="Website Published",
        related='room_type_id.website_published',
        store=True, readonly=True,
        help="Published on the website (from the room type). "
             "Availability is separate: Status / Available.")
    num_person = fields.Integer(string='Number Of Persons',
                                required=True, default=1,
                                help="Automatically chooses the No. of Persons",
                                tracking=True)
    avatar_128 = fields.Image(string='Avatar 128',
                              compute='_compute_avatar_128_hotel',
                              help="Uploaded room image, else a colored "
                              "first-letter tile for kanban.")

    @api.depends('name', 'image_128')
    def _compute_avatar_128_hotel(self):
        for room in self:
            if room.image_128:
                room.avatar_128 = room.image_128
            elif room.name:
                room.avatar_128 = generate_text_avatar_svg(
                    room.name[:1].upper(), room.name)
            else:
                room.avatar_128 = False

    def action_reserve_room(self):
        """Open the reservation form for this room. Navigation-only:
        creates nothing and mutates nothing; the clerk completes the
        booking in the form."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reserve %s') % self.display_name,
            'res_model': 'room.booking',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {
                'default_room_line_ids': [(0, 0, {'room_id': self.id})],
            },
        }

    @api.constrains("num_person")
    def _check_capacity(self):
        """Check capacity function"""
        for room in self:
            if room.num_person <= 0:
                raise ValidationError(_("Room capacity must be more than 0"))

    @api.constrains('status', 'is_room_avail')
    def _check_status_avail_sync(self):
        """status and is_room_avail are one flag in two fields (legacy).

        Invariant: available ⟺ True. All writers must set both via
        room.booking._hold_rooms/_release_rooms; this guard catches any
        path that updates only one side."""
        for room in self:
            if not room.is_room:
                continue
            consistent = (room.status == 'available') == bool(
                room.is_room_avail)
            if not consistent:
                raise ValidationError(
                    _("Room %s: status (%s) and Available (%s) disagree; "
                      "update both together.")
                    % (room.display_name, room.status,
                       room.is_room_avail))

    @api.onchange("room_type")
    def _onchange_room_type(self):
        """Based on selected room type, number of person will be updated.
        ----------------------------------------
        @param self: object pointer"""
        if self.room_type == "single":
            self.num_person = 1
        elif self.room_type == "double":
            self.num_person = 2
        else:
            self.num_person = 4

    @api.onchange('is_room')
    def _onchange_is_room(self):
        """Set product type to consumable if it is a room"""
        if self.is_room:
            self.type = 'consu'
            self.is_storable = False

    @api.constrains('is_room', 'is_storable')
    def _check_room_type(self):
        """Room products cannot be storable"""
        for record in self:
            if record.is_room and record.is_storable:
                raise ValidationError(_("Room products cannot be storable. Please disable 'Track Inventory'."))


