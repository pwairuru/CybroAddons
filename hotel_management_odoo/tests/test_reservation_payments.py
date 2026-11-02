# -*- coding: utf-8 -*-
"""Reservation Payments button: links stamped on reconcile + reception
sees only hotel-linked payments.

Root causes (live-proven): register-wizard payments reconcile AFTER
post, so create/post backfill misses them (6 live payments with no
hotel links); and reception has no account.payment read at all while
the badge count uses sudo.
"""
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase


class TestReservationPayments(TransactionCase):
    def _hotel_move(self):
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.env.company.partner_id.id})
        booking = self.env['room.booking'].create(
            {'partner_id': folio.partner_id.id})
        prod = self.env['product.product'].create({
            'name': 'Reservation Pay Charge',
            'sale_ok': True,
            'list_price': 50.0,
            'taxes_id': [(6, 0, [])],
        })
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': folio.partner_id.id,
            'hotel_folio_id': folio.id,
            'hotel_booking_id': booking.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': prod.id,
                'name': 'room',
                'quantity': 1,
                'price_unit': 50.0,
                'tax_ids': [(6, 0, [])],
            })],
        })
        move.action_post()
        return booking, folio, move

    def _reception_user(self):
        group = self.env.ref(
            'hotel_management_odoo.hotel_group_reception')
        return self.env['res.users'].create({
            'name': 'Reception Pay Test',
            'login': 'reception_pay_test',
            'group_ids': [(6, 0, [group.id])],
        })

    def test_wizard_payment_stamped_after_reconcile(self):
        booking, folio, move = self._hotel_move()
        journal = self.env['account.journal'].search(
            [('type', '=', 'cash'),
             ('company_id', '=', self.env.company.id)], limit=1)
        self.assertTrue(journal, 'a company cash journal must exist')
        wiz = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=move.ids).create(
                {'amount': 50.0, 'journal_id': journal.id})
        wiz.action_create_payments()
        move.invalidate_recordset()
        payment = move.matched_payment_ids[:1]
        self.assertTrue(payment, 'wizard must link a payment')
        self.assertEqual(
            payment.hotel_booking_id.id, booking.id,
            'reconcile must stamp the booking link')
        self.assertEqual(
            payment.hotel_folio_id.id, folio.id,
            'reconcile must stamp the folio link')

    def test_reception_reads_only_hotel_payments(self):
        booking, folio, move = self._hotel_move()
        hotel_pay = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_id': folio.partner_id.id,
            'amount': 5.0,
            'hotel_booking_id': booking.id,
            'hotel_folio_id': folio.id,
        })
        other_pay = self.env['account.payment'].create({
            'payment_type': 'inbound',
            'partner_id': self.env.company.partner_id.id,
            'amount': 7.0,
        })
        recep = self._reception_user()
        seen = hotel_pay.with_user(recep).read(['name'])
        self.assertTrue(seen, 'reception must read hotel payments')
        with self.assertRaises(AccessError):
            other_pay.with_user(recep).read(['name'])
