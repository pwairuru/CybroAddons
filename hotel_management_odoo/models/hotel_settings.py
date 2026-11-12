# -*- coding: utf-8 -*-
from odoo import fields, models


class HotelSettings(models.TransientModel):
    """Hotel settings page (room capacity policy)."""
    _inherit = 'res.config.settings'

    hotel_capacity_policy = fields.Selection(
        [('block', 'Block saving'), ('warn', 'Warn only')],
        string='Over-capacity policy',
        related='company_id.hotel_capacity_policy',
        readonly=False,
        help='How to handle a room line where adults + children exceed '
        'the room capacity (room persons or type max occupants; '
        'toddlers never count). Block saving refuses to save the '
        'line; Warn only allows it and flags the line.')
    public_auto_confirm = fields.Boolean(related='company_id.public_auto_confirm', readonly=False)
