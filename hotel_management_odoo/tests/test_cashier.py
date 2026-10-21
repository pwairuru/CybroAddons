# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestCashier(TransactionCase):
    def setUp(self):
        super().setUp()
        self.guest = self.env.company.partner_id
        self.product = self.env['product.product'].create({
            'name': 'Test Room Night Cashier',
            'sale_ok': True,
            'list_price': 5000.0,
            'taxes_id': [(6, 0, [])],
        })

    def _charged_folio(self, qty=2, price=5000.0):
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.guest.id})
        self.env['hotel.charge.service'].post_charge(
            folio.id, self.product.id, qty, price, 'to_guest')
        return folio

    def test_deposit_deducted_at_settle(self):
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.guest.id})
        self.env['hotel.charge.service'].post_charge(
            folio.id, self.product.id, 2, 5000.0, 'to_guest')
        self.env['hotel.deposit'].create(
            {'folio_id': folio.id, 'amount': 3000.0})
        move = folio.action_settle()
        assert move.amount_total == folio.total - 3000.0
        assert folio.amount_due == 0.0, "settled folio owes nothing"
        assert folio.deposit_total == 3000.0, "consumed deposits stay applied"

    def test_deposit_negative_rejected(self):
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.guest.id})
        with self.assertRaises(ValidationError):
            self.env['hotel.deposit'].create(
                {'folio_id': folio.id, 'amount': -100.0})

    def test_deposit_double_apply_rejected(self):
        folio = self._charged_folio()
        deposit = self.env['hotel.deposit'].create(
            {'folio_id': folio.id, 'amount': 1000.0})
        deposit.apply()
        with self.assertRaises(ValidationError):
            deposit.apply()

    def test_city_ledger_transfer_and_aging(self):
        folio = self._charged_folio()
        amount_due = folio.amount_due
        ledger = self.env['hotel.city.ledger'].transfer(folio.id)
        assert ledger.amount == amount_due, "ledger must carry folio balance"
        assert ledger.partner_id.id == folio.partner_id.id
        assert folio.ledger_id.id == ledger.id, "folio must link ledger"
        assert folio.amount_due == 0.0, "transferred folio owes nothing"
        assert ledger.age_days == 0, "fresh transfer ages zero days"
        ledger.write({'transfer_date': '2026-10-01'})
        ledger._compute_age_days()
        assert ledger.age_days > 0, "backdated transfer must age"

    def test_city_ledger_transfer_settled_rejected(self):
        folio = self._charged_folio()
        folio.action_settle()
        with self.assertRaises(ValidationError):
            self.env['hotel.city.ledger'].transfer(folio.id)

    def test_city_ledger_transfer_blocks_on_draft_deposit(self):
        folio = self._charged_folio()
        self.env['hotel.deposit'].create(
            {'folio_id': folio.id, 'amount': 1000.0})
        with self.assertRaises(ValidationError):
            self.env['hotel.city.ledger'].transfer(folio.id)

    def test_city_ledger_transfer_blocks_on_applied_deposit(self):
        folio = self._charged_folio()
        deposit = self.env['hotel.deposit'].create(
            {'folio_id': folio.id, 'amount': 1000.0})
        deposit.apply()
        with self.assertRaises(ValidationError):
            self.env['hotel.city.ledger'].transfer(folio.id)

    def test_settle_tax_truth_10_percent(self):
        tax_group = self.env['account.tax.group'].create({
            'name': 'Test VAT Group 10',
        })
        tax = self.env['account.tax'].create({
            'name': 'Test VAT 10',
            'tax_group_id': tax_group.id,
            'amount_type': 'percent',
            'amount': 10.0,
            'type_tax_use': 'sale',
            'price_include_override': 'tax_excluded',
        })
        product = self.env['product.product'].create({
            'name': 'Test Room Night Taxed',
            'sale_ok': True,
            'list_price': 5000.0,
            'taxes_id': [(6, 0, [tax.id])],
        })
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.guest.id})
        self.env['hotel.charge.service'].post_charge(
            folio.id, product.id, 2, 5000.0, 'to_guest')
        folio.invalidate_recordset(
            ['amount_untaxed', 'amount_tax', 'amount_total', 'total'])
        self.assertAlmostEqual(folio.amount_untaxed, 10000.0)
        self.assertAlmostEqual(folio.amount_tax, 1000.0)
        self.assertAlmostEqual(folio.amount_total, 11000.0)
        self.assertAlmostEqual(folio.total, 11000.0)
        move = folio.action_settle()
        self.assertAlmostEqual(move.amount_total, folio.amount_total)

    def test_shift_close_variance(self):
        shift = self.env['hotel.cashier.shift'].create(
            {'opening_cash': 10000.0, 'expected_cash': 15000.0})
        shift.action_open()
        shift.close(14800.0)
        assert shift.state == 'closed', "shift must close"
        assert shift.variance == -200.0, "variance = closing - expected"

    def test_shift_second_open_rejected(self):
        first = self.env['hotel.cashier.shift'].create(
            {'opening_cash': 10000.0, 'expected_cash': 15000.0})
        first.action_open()
        second = self.env['hotel.cashier.shift'].create(
            {'opening_cash': 5000.0, 'expected_cash': 8000.0})
        with self.assertRaises(ValidationError):
            second.action_open()

    def test_shift_double_close_rejected(self):
        shift = self.env['hotel.cashier.shift'].create(
            {'opening_cash': 10000.0, 'expected_cash': 15000.0})
        shift.action_open()
        shift.close(15000.0)
        with self.assertRaises(ValidationError):
            shift.close(15000.0)
