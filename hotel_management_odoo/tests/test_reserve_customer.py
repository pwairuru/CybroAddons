# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestReserveCustomer(TransactionCase):
    def _make_room(self, name='Reserve Room'):
        return self.env['product.template'].create({
            'name': name, 'is_room': True,
            'num_person': 2, 'list_price': 10000.0})

    def test_reserve_action_only_navigates(self):
        room = self._make_room()
        bookings_before = self.env['room.booking'].search_count([])
        status_before = room.status
        action = room.action_reserve_room()
        self.assertEqual(action.get('res_model'), 'room.booking')
        self.assertEqual(action.get('type'), 'ir.actions.act_window')
        ctx = action.get('context', {})
        self.assertIn('default_room_line_ids', ctx)
        line_cmd = ctx['default_room_line_ids'][0]
        self.assertEqual(line_cmd[2].get('room_id'), room.id)
        # does nothing after: no booking created, room untouched
        self.assertEqual(
            self.env['room.booking'].search_count([]), bookings_before)
        self.assertEqual(room.status, status_before)

    def test_reserve_button_available_for_all_rooms(self):
        list_view = self.env.ref(
            'hotel_management_odoo.product_template_view_list_rooms')
        kanban_view = self.env.ref(
            'hotel_management_odoo.product_template_view_kanban_rooms')
        for view in (list_view, kanban_view):
            self.assertIn('action_reserve_room', view.arch_db)
        # no status gating: rooms book for future dates, not current status
        self.assertNotIn("status != 'available'", list_view.arch_db)
        self.assertNotIn('record.status.raw_value', kanban_view.arch_db)

    def test_booking_avatar_shows_customer_letter(self):
        guest = self.env['res.partner'].create({'name': 'Zelda Guest'})
        room = self._make_room('Avatar Reserve Room')
        bk = self.env['room.booking'].create({
            'partner_id': guest.id,
            'room_line_ids': [(0, 0, {'room_id': room.id,
                                      'checkin_date': '2026-11-01 14:00:00',
                                      'checkout_date': '2026-11-02 11:00:00'})]})
        self.assertTrue(bk.avatar_128)
        self.assertEqual(bytes(bk.avatar_128), bytes(guest.avatar_128))

    def test_folio_avatar_shows_customer_letter(self):
        guest = self.env['res.partner'].create({'name': 'Yara Folio'})
        folio = self.env['hotel.folio'].create({'partner_id': guest.id})
        self.assertTrue(folio.avatar_128)
        self.assertEqual(bytes(folio.avatar_128), bytes(guest.avatar_128))

    def test_customers_menu_under_reservations(self):
        parent = self.env.ref('hotel_management_odoo.room_booking_menu')
        leaves = parent.child_id.filtered(
            lambda m: not m.child_id and m.action)
        customer_leaves = leaves.filtered(
            lambda m: m.action.res_model == 'res.partner')
        self.assertTrue(
            customer_leaves,
            "Reservations menu must contain a Customers leaf opening "
            "res.partner (no model change).")
