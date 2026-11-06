from odoo.tests.common import TransactionCase


class TestMealColumn(TransactionCase):
    def _available_room(self):
        from datetime import datetime

        ci = datetime(2026, 11, 1, 14, 0, 0)
        co = datetime(2026, 11, 2, 11, 0, 0)
        for room in self.env['product.template'].search(
                [('is_room', '=', True)]):
            try:
                self.env['room.booking']._check_room_available(
                    room, ci, co, ignore_booking=None)
            except Exception:
                continue
            return room
        self.fail("No available room template for 2026-11-01..02")

    def test_folio_line_stores_meal_plan(self):
        guest = self.env['res.partner'].create({'name': 'Meal Guest'})
        room = self._available_room()
        bk = self.env['room.booking'].create({
            'partner_id': guest.id,
            'meal_plan': 'HB',
            'room_line_ids': [(0, 0, {'room_id': room.id,
                                      'meal_plan': 'FB',
                                      'checkin_date': '2026-11-01 14:00:00',
                                      'checkout_date': '2026-11-02 11:00:00'})],
        })
        folio = self.env['hotel.folio'].create({
            'partner_id': guest.id, 'booking_id': bk.id})
        product = room.product_variant_id
        line = self.env['hotel.charge.service'].post_charge(
            folio.id, product.id, 1, 100.0, 'to_guest',
            hotel_date='2026-11-01', room_template_id=room.id,
            booking_line_id=bk.room_line_ids[:1].id, source='rate')
        self.assertEqual(line.meal_plan, 'FB')
        self.assertEqual(line.meal_name, 'Full Board')

    def test_statement_groups_carry_meal(self):
        guest = self.env['res.partner'].create({'name': 'Meal Stmt Guest'})
        room = self._available_room()
        bk = self.env['room.booking'].create({
            'partner_id': guest.id,
            'meal_plan': 'HB',
            'room_line_ids': [(0, 0, {'room_id': room.id,
                                      'meal_plan': 'BB',
                                      'checkin_date': '2026-11-01 14:00:00',
                                      'checkout_date': '2026-11-02 11:00:00'})],
        })
        folio = self.env['hotel.folio'].create({
            'partner_id': guest.id, 'booking_id': bk.id})
        product = room.product_variant_id
        self.env['hotel.charge.service'].post_charge(
            folio.id, product.id, 1, 100.0, 'to_guest',
            hotel_date='2026-11-01', room_template_id=room.id,
            booking_line_id=bk.room_line_ids[:1].id, source='rate')
        groups = folio.get_statement_groups()
        rooms = next(g for g in groups if g['label'] == 'Rooms')
        self.assertEqual(rooms['rows'][0]['meal'], 'Bed & Breakfast')

    def test_folio_invoice_carries_meal(self):
        guest = self.env['res.partner'].create({'name': 'Meal Inv Guest'})
        room = self._available_room()
        bk = self.env['room.booking'].create({
            'partner_id': guest.id,
            'meal_plan': 'HB',
            'room_line_ids': [(0, 0, {'room_id': room.id,
                                      'meal_plan': 'HB',
                                      'checkin_date': '2026-11-01 14:00:00',
                                      'checkout_date': '2026-11-02 11:00:00'})],
        })
        folio = self.env['hotel.folio'].create({
            'partner_id': guest.id, 'booking_id': bk.id})
        product = room.product_variant_id
        self.env['hotel.charge.service'].post_charge(
            folio.id, product.id, 1, 100.0, 'to_guest',
            hotel_date='2026-11-01', room_template_id=room.id,
            booking_line_id=bk.room_line_ids[:1].id, source='rate')
        move = folio.action_generate_draft_invoice()
        self.assertTrue(move.invoice_line_ids)
        self.assertEqual(
            move.invoice_line_ids[0].hotel_meal_plan, 'Half Board')
