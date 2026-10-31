# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PosSession(models.Model):
    """Keep room-charged outlet sales out of the closing sale move.

    A fully hotel-charged, booking-linked order is billed on the
    folio invoice (the sole bill — see pos.order._generate_order_invoice).
    If it stayed in the closing sale move, the outlet would book the
    same revenue a second time. Excluded orders are still marked done;
    stock moves were already created at order time, and the sale stays
    visible on the booking (Bar/Restaurant tab) and folio statement.
    """
    _inherit = 'pos.session'

    def _get_order_for_session_closing(self):
        orders = super()._get_order_for_session_closing()
        hotel_only = orders.filtered(
            lambda o: o.booking_id and o._is_fully_hotel_charge())
        if hotel_only:
            hotel_only.write({'state': 'done'})
        return orders - hotel_only
