# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestBookingFlow(TransactionCase):
    def test_payment_carries_both_links(self):
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.env.company.partner_id.id})
        move = folio.action_generate_draft_invoice()
        self.assertTrue(move)
        pay = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_id': folio.partner_id.id,
            'amount': 10.0,
            'hotel_folio_id': folio.id,
        })
        self.assertEqual(pay.hotel_folio_id.id, folio.id)
        self.assertTrue(hasattr(pay, 'hotel_booking_id'))

    def test_deposit_cancel_and_refund(self):
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.env.company.partner_id.id})
        dep = self.env['hotel.deposit'].create(
            {'folio_id': folio.id, 'amount': 2000.0})
        dep.action_cancel_draft()
        self.assertEqual(dep.state, 'cancelled')
        dep2 = self.env['hotel.deposit'].create(
            {'folio_id': folio.id, 'amount': 1500.0})
        dep2.action_collect()
        rev = dep2.action_refund()
        self.assertEqual(dep2.state, 'refunded')
        self.assertTrue(rev)
