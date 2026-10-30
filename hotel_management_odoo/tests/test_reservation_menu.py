# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestReservationMenu(TransactionCase):
    def test_reservation_opens_booking_view(self):
        parent = self.env.ref('hotel_management_odoo.room_booking_menu')
        leaves = parent.child_id.filtered(
            lambda m: not m.child_id and m.action)
        booking_leaves = leaves.filtered(
            lambda m: m.action.res_model == 'room.booking')
        self.assertTrue(
            booking_leaves,
            "Reservation menu must contain a leaf opening the booking view "
            "(navbar never fires parent-menu actions).")
