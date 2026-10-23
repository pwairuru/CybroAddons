# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestFolioLifecycle(TransactionCase):
    def _make_booking(self, policy='manual'):
        partner = self.env.company.partner_id
        room = self.env['product.template'].create({
            'name': 'Folio Lifecycle Room',
            'is_room': True,
            'list_price': 10000.0,
        })
        now = fields.Datetime.now()
        booking = self.env['room.booking'].create({
            'partner_id': partner.id,
            'hotel_policy': policy,
            'checkin_date': now + timedelta(days=1),
            'checkout_date': now + timedelta(days=2),
        })
        self.env['room.booking.line'].create({
            'booking_id': booking.id,
            'room_id': room.id,
            'checkin_date': now + timedelta(days=1),
            'checkout_date': now + timedelta(days=2),
            'uom_qty': 1.0,
        })
        return booking

    def _charged_folio(self, price=5000.0, qty=2):
        product = self.env['product.product'].create({
            'name': 'Folio Lifecycle Charge',
            'sale_ok': True,
            'list_price': price,
            'taxes_id': [(6, 0, [])],
        })
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.env.company.partner_id.id})
        self.env['hotel.charge.service'].post_charge(
            folio.id, product.id, qty, price, 'to_guest')
        return folio

    def test_booking_creates_folio_and_draft_invoice_history(self):
        booking = self._make_booking(policy='picking')
        booking.action_reserve()
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        self.assertTrue(folio, "reserve must auto-create folio")
        self.assertEqual(folio.policy_snapshot, booking.hotel_policy)
        inv1 = folio.action_generate_draft_invoice()
        inv2 = folio.action_generate_draft_invoice()
        self.assertEqual(inv1.id, inv2.id)  # idempotent draft
        self.assertEqual(len(folio.invoice_ids), 1)

    def test_deposit_not_negative_revenue(self):
        folio = self._charged_folio()
        self.env['hotel.deposit'].create(
            {'folio_id': folio.id, 'amount': 3000.0})
        move = folio.action_settle()
        neg_lines = move.invoice_line_ids.filtered(
            lambda l: l.price_unit < 0)
        self.assertFalse(neg_lines, "deposits must not post as negative revenue")

    def test_split_flow_post_apply_settle(self):
        folio = self._charged_folio()
        self.env['hotel.deposit'].create(
            {'folio_id': folio.id, 'amount': 1000.0})
        draft = folio.action_generate_draft_invoice()
        self.assertEqual(draft.state, 'draft')
        posted = folio.action_post_invoice()
        self.assertEqual(posted.state, 'posted')
        self.assertTrue(folio.action_apply_deposit())
        move = folio.action_settle()
        self.assertEqual(folio.state, 'settled')
        self.assertEqual(move.id, posted.id)
        self.assertEqual(move.hotel_folio_id.id, folio.id)
        self.assertTrue(all(l.locked for l in folio.line_ids))

    def test_post_charge_source_stored(self):
        product = self.env['product.product'].create({
            'name': 'Folio Source Charge',
            'sale_ok': True,
            'list_price': 1000.0,
        })
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.env.company.partner_id.id,
             'notes': 'lifecycle note'})
        line = self.env['hotel.charge.service'].post_charge(
            folio.id, product.id, 1, 1000.0, 'to_guest',
            source='pos')
        self.assertEqual(line.source, 'pos')
        self.assertTrue(folio.notes)
        void_folio = self.env['hotel.folio'].create(
            {'partner_id': self.env.company.partner_id.id})
        void_folio.action_void()
        self.assertEqual(void_folio.state, 'void')
