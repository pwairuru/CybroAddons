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
