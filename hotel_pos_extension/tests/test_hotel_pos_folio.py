from odoo.tests.common import TransactionCase


class TestHotelPosFolio(TransactionCase):
    _order_seq = 0

    @classmethod
    def _next_ref(cls):
        cls._order_seq += 1
        return 'TEST-FOLIO-%s-%d' % (cls.__name__, cls._order_seq)

    def _create_pos_order(self, vals):
        """Create a POS order, tolerating the kitchen-screen module's
        create-time ``cr.commit()`` (forbidden -> AssertionError inside
        tests). The record itself is created before the commit attempt,
        so on AssertionError we re-fetch it by its deterministic ref.
        """
        vals = dict(vals)
        vals.setdefault('pos_reference', self._next_ref())
        Order = self.env['pos.order']
        try:
            return Order.create(vals)
        except AssertionError:
            order = Order.search(
                [('pos_reference', '=', vals['pos_reference'])], limit=1)
            assert order, "POS order %s lost after kitchen commit guard" % (
                vals['pos_reference'],)
            return order

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

    def test_hotel_charge_posts_pos_lines_to_folio(self):
        guest = self.env['res.partner'].create({'name': 'Folio POS Guest'})
        room = self._available_room()
        bk = self.env['room.booking'].create({
            'partner_id': guest.id,
            'room_line_ids': [(0, 0, {'room_id': room.id,
                                      'checkin_date': '2026-11-01 14:00:00',
                                      'checkout_date': '2026-11-02 11:00:00'})],
        })
        bk.action_reserve()
        bk.action_checkin()
        pm = self.env['pos.payment.method'].search(
            [('is_hotel_charge', '=', True)], limit=1)
        sess = self.env['pos.session'].search(
            [('state', '=', 'opened')], limit=1)
        prod = self.env['product.product'].search(
            [('available_in_pos', '=', True)], limit=1)
        order = self._create_pos_order({
            'session_id': sess.id, 'partner_id': guest.id,
            'booking_id': bk.id, 'company_id': self.env.company.id,
            'amount_tax': 0.0, 'amount_total': 10.0,
            'amount_paid': 0.0, 'amount_return': 0.0,
            'lines': [(0, 0, {'product_id': prod.id, 'qty': 2,
                              'price_unit': 5.0, 'price_subtotal': 10.0,
                              'price_subtotal_incl': 10.0})]})
        order.add_payment({'pos_order_id': order.id,
                           'payment_method_id': pm.id, 'amount': 10.0})
        order.action_pos_order_paid()
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', bk.id), ('state', '=', 'open')])
        posted = self.env['hotel.folio.line'].search(
            [('folio_id', '=', folio.id),
             ('pos_order_id', '=', order.id)])
        self.assertEqual(len(posted), 1)
        self.assertEqual(posted.source, 'pos')
        self.assertEqual(posted.quantity, 2)
        order.action_pos_order_paid()  # idempotent re-run
        self.assertEqual(self.env['hotel.folio.line'].search_count(
            [('folio_id', '=', folio.id),
             ('pos_order_id', '=', order.id)]), 1)

    def test_pos_totals_ignore_draft_orders(self):
        bk = self.env['room.booking'].search([], limit=1)
        before = bk.amount_total_pos
        sess = self.env['pos.session'].search(
            [('state', '=', 'opened')], limit=1)
        prod = self.env['product.product'].search(
            [('available_in_pos', '=', True)], limit=1)
        self._create_pos_order({
            'session_id': sess.id, 'partner_id': bk.partner_id.id,
            'booking_id': bk.id, 'company_id': self.env.company.id,
            'amount_tax': 0.0, 'amount_total': 99.0,
            'amount_paid': 0.0, 'amount_return': 0.0,
            'lines': [(0, 0, {'product_id': prod.id, 'qty': 1,
                              'price_unit': 99.0, 'price_subtotal': 99.0,
                              'price_subtotal_incl': 99.0})]})
        bk.invalidate_recordset()
        self.assertEqual(bk.amount_total_pos, before)

    def _settle_hotel_charge_order(self, bk, amount=10.0):
        """Reserve+checkin booking, pay a hotel-charge POS order for it."""
        bk.action_reserve()
        bk.action_checkin()
        pm = self.env['pos.payment.method'].search(
            [('is_hotel_charge', '=', True)], limit=1)
        sess = self.env['pos.session'].search(
            [('state', '=', 'opened')], limit=1)
        prod = self.env['product.product'].search(
            [('available_in_pos', '=', True)], limit=1)
        order = self._create_pos_order({
            'session_id': sess.id, 'partner_id': bk.partner_id.id,
            'booking_id': bk.id, 'company_id': self.env.company.id,
            'amount_tax': 0.0, 'amount_total': amount,
            'amount_paid': 0.0, 'amount_return': 0.0,
            'lines': [(0, 0, {'product_id': prod.id, 'qty': 1,
                              'price_unit': amount,
                              'price_subtotal': amount,
                              'price_subtotal_incl': amount})]})
        order.add_payment({'pos_order_id': order.id,
                           'payment_method_id': pm.id, 'amount': amount})
        order.action_pos_order_paid()
        return order

    def test_combined_total_matches_summary_lines(self):
        guest = self.env['res.partner'].create({'name': 'Combined Guest'})
        room = self._available_room()
        bk = self.env['room.booking'].create({
            'partner_id': guest.id,
            'room_line_ids': [(0, 0, {'room_id': room.id,
                                      'checkin_date': '2026-11-01 14:00:00',
                                      'checkout_date': '2026-11-02 11:00:00'})],
        })
        self._settle_hotel_charge_order(bk, amount=10.0)
        bk.invalidate_recordset()
        lines = bk.get_bill_summary_lines()
        self.assertEqual(bk.amount_total_pos, 10.0)
        self.assertEqual(bk.amount_total_combined,
                         bk.amount_total + 10.0)
        self.assertAlmostEqual(bk.get_bill_summary_total(),
                               sum(l['total'] for l in lines))
        self.assertAlmostEqual(bk.get_bill_summary_total(),
                               bk.amount_total + bk.amount_total_pos)

    def test_pay_at_checkout_stays_due_until_folio_settle(self):
        guest = self.env['res.partner'].create({'name': 'Due Guest'})
        room = self._available_room()
        bk = self.env['room.booking'].create({
            'partner_id': guest.id,
            'room_line_ids': [(0, 0, {'room_id': room.id,
                                      'checkin_date': '2026-11-01 14:00:00',
                                      'checkout_date': '2026-11-02 11:00:00'})],
        })
        order = self._settle_hotel_charge_order(bk, amount=10.0)
        link = self.env['hotel.pos.line'].search(
            [('pos_order_id', '=', order.id)], limit=1)
        self.assertTrue(link)
        self.assertTrue(link.is_pay_at_checkout)
        self.assertTrue(link.due_until_settle)
