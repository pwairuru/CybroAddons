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

    def test_reservations_order_latest_first(self):
        self.assertEqual(
            self.env['room.booking']._order, 'id desc',
            "Reservations must list latest first (kanban + list).")

    def test_reservation_cards_show_quote_total_without_pos(self):
        # amount_total_combined lives in hotel_pos_extension, so the
        # base card renders the quote total; the POS inherit swaps it
        # to Combined Total (covered in hotel_pos_extension tests).
        kanban = self.env.ref(
            'hotel_management_odoo.room_booking_view_kanban')
        self.assertIn('amount_total', kanban.arch_db)
