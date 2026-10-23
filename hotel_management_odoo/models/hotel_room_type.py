# -*- coding: utf-8 -*-
from odoo import fields, models


class HotelRoomType(models.Model):
    _name = 'hotel.room.type'
    _description = "Hotel Room Type"
    _inherit = ['mail.thread', 'mail.activity.mixin', 'avatar.mixin']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(tracking=True)
    company_id = fields.Many2one('res.company', required=True, index=True,
                                 default=lambda self: self.env.company,
                                 tracking=True)
    adult_capacity = fields.Integer(default=2, tracking=True)
    child_capacity = fields.Integer(default=0, tracking=True)
    max_occupants = fields.Integer(default=2, tracking=True)
    base_rate = fields.Float(required=True, default=0.0, tracking=True)
    default_board = fields.Selection(
        [('RO', 'Room Only'), ('BB', 'Bed & Breakfast'),
         ('HB', 'Half Board'), ('FB', 'Full Board')],
        default='RO', required=True, tracking=True)
    website_published = fields.Boolean(default=False, tracking=True)
    amenity_ids = fields.Many2many('hotel.amenity', string="Amenities")
    image = fields.Image()
    active = fields.Boolean(default=True, tracking=True)

    def default_rate(self):
        self.ensure_one()
        return self.base_rate
