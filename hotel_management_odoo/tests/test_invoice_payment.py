# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestInvoicePayment(TransactionCase):
    def test_pay_wizard_posts_move_and_reconciles(self):
        partner = self.env['res.partner'].create({'name': 'Pay Guest'})
        prod = self.env['product.product'].create({
            'name': 'Pay Wizard Charge',
            'sale_ok': True,
            'list_price': 100.0,
            'taxes_id': [(6, 0, [])],
        })
        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': prod.id,
                'name': 't',
                'quantity': 1,
                'price_unit': 100.0,
                'tax_ids': [(6, 0, [])],
            })],
        })
        move.action_post()
        journal = self.env['account.journal'].search(
            [('type', '=', 'cash'),
             ('company_id', '=', self.env.company.id)], limit=1)
        self.assertTrue(journal, 'a company cash journal must exist')
        wiz = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=move.ids).create(
                {'amount': 100.0, 'journal_id': journal.id})
        wiz.action_create_payments()
        move.invalidate_recordset()
        payment = move.matched_payment_ids[:1]
        self.assertTrue(payment, 'pay wizard must link a payment')
        self.assertTrue(
            payment.move_id,
            'payment must post a journal entry (move_id missing: '
            'outbound/inbound Manual Payment lines lack payment accounts)')
        self.assertEqual(payment.move_id.state, 'posted')
        # Enterprise outstanding-account flow lands on in_payment (fully
        # matched to a posted payment, awaiting bank reconciliation),
        # not paid; either means the wizard money is real.
        self.assertIn(move.payment_state, ('paid', 'in_payment'))
        self.assertEqual(move.amount_residual, 0.0)
