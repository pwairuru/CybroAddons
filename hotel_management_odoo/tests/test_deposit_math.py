# -*- coding: utf-8
"""Deposit money math: conservation at every stage.

The invariant: every cent is exactly one place. Gross folio total
must always equal residual + reconciled payments + reversed deposits
+ refunded/forfeited amounts. Any test here failing means money
leaked, doubled, or stranded — fix the code, never the test.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


def _rate_setup(env, co, rtype, price=20000.0):
    meal = env['hotel.meal.plan'].search([('code', '=', 'BB')], limit=1)
    period = env['hotel.rate.period'].create({
        'name': 'MathH', 'start_md': '01-01', 'end_md': '12-31',
        'sequence': 10, 'priority': 10, 'company_id': co.id})
    env['hotel.rate.plan'].create({
        'name': 'MathBB', 'code': 'BB', 'company_id': co.id})
    env['hotel.rate.line'].create({
        'company_id': co.id, 'period_id': period.id,
        'room_type_id': rtype.id, 'meal_plan_id': meal.id,
        'price': price, 'included_adults': 2, 'included_children': 0})


class TestDepositMath(TransactionCase):
    def _booking(self, price=20000.0):
        co = self.env.company
        guest = self.env['res.partner'].create({'name': 'Math Guest'})
        now = fields.Datetime.now()
        booking = self.env['room.booking'].create({
            'partner_id': guest.id, 'company_id': co.id,
            'checkin_date': now + timedelta(days=1),
            'checkout_date': now + timedelta(days=2),
        })
        rtype = self.env['hotel.room.type'].create({
            'name': 'MathFam', 'base_rate': price,
            'adult_capacity': 2, 'child_capacity': 0,
            'max_occupants': 2, 'charge_mode': 'per_room'})
        _rate_setup(self.env, co, rtype, price=price)
        room = self.env['product.template'].create({
            'name': 'Math-101', 'is_room': True, 'num_person': 2,
            'list_price': price, 'room_type_id': rtype.id})
        self.env['room.booking.line'].create({
            'booking_id': booking.id, 'room_id': room.id,
            'checkin_date': now + timedelta(days=1),
            'checkout_date': now + timedelta(days=2),
            'adults': 1, 'company_id': co.id})
        booking.action_reserve()
        return booking

    def _folio(self, booking):
        return self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)

    def _charge_post_settle(self, folio, amount, booking):
        product = self.env['product.product'].create({
            'name': 'Math Charge', 'sale_ok': True,
            'list_price': amount, 'taxes_id': [(6, 0, [])]})
        self.env['hotel.charge.service'].post_charge(
            folio.id, product.id, 1, amount, 'to_guest')
        if booking.state == 'reserved':
            booking.action_checkin()
        booking.action_checkout()
        return folio.action_settle()

    def _assert_coherent(self, folio, move, booking):
        """The money equation, valid at EVERY stage:

        due + paid == invoice total; wizard proposes residual;
        folio mirrors booking while open (settled folios report 0,
        the still-owed residual lives on the booking/invoice).
        """
        folio.invalidate_recordset()
        booking.invalidate_recordset()
        self.assertAlmostEqual(
            booking.amount_due + booking.amount_paid,
            move.amount_total, places=2)
        self.assertAlmostEqual(
            folio.amount_paid, booking.amount_paid, places=2)
        if folio.state == 'settled':
            self.assertEqual(folio.amount_due, 0.0)
            self.assertAlmostEqual(booking.amount_due,
                                   move.amount_residual, places=2)
        else:
            self.assertAlmostEqual(folio.amount_due, booking.amount_due,
                                   places=2)
        self.assertGreaterEqual(booking.amount_due, 0.0)
        self.assertGreaterEqual(folio.amount_due, 0.0)
        wiz = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=move.ids).create({})
        self.assertAlmostEqual(wiz.amount, move.amount_residual, places=2)
        return booking.amount_paid

    def test_single_deposit_exact_split(self):
        booking = self._booking()
        dep = booking.action_take_deposit(5000.0)
        folio = self._folio(booking)
        move = self._charge_post_settle(folio, 20000.0, booking)
        paid = self._assert_coherent(folio, move, booking)
        self.assertAlmostEqual(paid, 5000.0, places=2)
        self.assertAlmostEqual(move.amount_residual,
                               move.amount_total - 5000.0, places=2)
        self.assertEqual(move.payment_state, 'partial')
        self.assertTrue(dep.move_id, "reversal must exist")

    def test_multiple_deposits_add_up(self):
        booking = self._booking()
        booking.action_take_deposit(5000.0)
        booking.action_checkin()
        booking.action_take_deposit(3000.0)
        booking.action_take_deposit(2000.0)
        folio = self._folio(booking)
        move = self._charge_post_settle(folio, 20000.0, booking)
        paid = self._assert_coherent(folio, move, booking)
        self.assertAlmostEqual(paid, 10000.0, places=2)
        self.assertAlmostEqual(move.amount_residual,
                               move.amount_total - 10000.0, places=2)

    def test_cents_stay_exact(self):
        booking = self._booking()
        booking.action_take_deposit(3333.33)
        folio = self._folio(booking)
        move = self._charge_post_settle(folio, 20000.0, booking)
        paid = self._assert_coherent(folio, move, booking)
        self.assertAlmostEqual(paid, 3333.33, places=2)
        self.assertAlmostEqual(
            move.amount_residual, move.amount_total - 3333.33, places=2)

    def test_deposit_after_invoice_nets_at_once(self):
        booking = self._booking()
        booking.action_checkin()
        folio = self._folio(booking)
        product = self.env['product.product'].create({
            'name': 'Math Early', 'sale_ok': True,
            'list_price': 20000.0, 'taxes_id': [(6, 0, [])]})
        self.env['hotel.charge.service'].post_charge(
            folio.id, product.id, 1, 20000.0, 'to_guest')
        booking.action_checkout()
        move = folio.action_post_invoice()
        gross = move.amount_total
        booking.action_take_deposit(5000.0)
        self.assertAlmostEqual(move.amount_residual, gross - 5000.0,
                               places=2)
        self._assert_coherent(folio, move, booking)
        settled = folio.action_settle()
        self.assertEqual(settled.id, move.id)
        self.assertAlmostEqual(move.amount_residual, gross - 5000.0,
                               places=2)

    def test_refund_before_settle_unwinds_clean(self):
        booking = self._booking()
        dep = booking.action_take_deposit(5000.0)
        folio = self._folio(booking)
        liability = folio._ensure_liability_account()
        cash_account = dep.payment_move_id.line_ids.filtered(
            lambda l: l.debit > 0).account_id
        dep.action_refund(reason="math test")
        self.assertEqual(dep.state, 'refunded')
        folio.invalidate_recordset()
        booking.invalidate_recordset()
        self.assertEqual(folio.deposit_total, 0.0)
        self.assertEqual(booking.deposit_total, 0.0)
        self.assertEqual(booking.amount_paid, 0.0)
        # Every live entry linked to the receipt (original + any
        # reversal; voided moves don't count) must net to zero.
        moves = (dep.payment_move_id + self.env['account.move'].search(
            [('reversed_entry_id', '=', dep.payment_move_id.id)]
        )).filtered(lambda m: m.state == 'posted')
        for account in (liability, cash_account):
            lines = moves.mapped('line_ids').filtered(
                lambda l: l.account_id == account)
            self.assertAlmostEqual(
                sum(lines.mapped('debit')) - sum(lines.mapped('credit')),
                0.0, places=2)

    def test_refund_after_settle_restores_gross(self):
        booking = self._booking()
        dep = booking.action_take_deposit(5000.0)
        folio = self._folio(booking)
        move = self._charge_post_settle(folio, 20000.0, booking)
        gross = move.amount_total
        dep.action_refund(reason="math test")
        self.assertAlmostEqual(move.amount_residual, gross, places=2)
        booking.invalidate_recordset()
        self.assertEqual(booking.deposit_total, 0.0)
        self.assertAlmostEqual(booking.amount_due, gross, places=2)

    def test_forfeit_keeps_books_balanced(self):
        booking = self._booking()
        dep = booking.action_take_deposit(4000.0)
        dep.action_forfeit(reason="math test")
        folio = self._folio(booking)
        folio.invalidate_recordset()
        booking.invalidate_recordset()
        self.assertEqual(folio.deposit_total, 0.0)
        self.assertEqual(booking.deposit_total, 0.0)
        finc = dep.move_id.line_ids.filtered(lambda l: l.credit > 0)
        fliab = dep.move_id.line_ids.filtered(lambda l: l.debit > 0)
        self.assertAlmostEqual(sum(finc.mapped('credit')), 4000.0,
                               places=2)
        self.assertAlmostEqual(sum(fliab.mapped('debit')), 4000.0,
                               places=2)

    def test_post_invoice_reverses_collected_deposits(self):
        """Deposit collected before invoicing must net at post time.

        The normal flow: Take at reservation, invoice at checkout.
        Posting must trigger the reversal so the Register Payment
        default is net during the whole post-to-settle window —
        previously it stayed gross until settle.
        """
        booking = self._booking()
        booking.action_take_deposit(5000.0)
        folio = self._folio(booking)
        dep = folio.deposit_ids[:1]
        product = self.env['product.product'].create({
            'name': 'Math Post', 'sale_ok': True,
            'list_price': 20000.0, 'taxes_id': [(6, 0, [])]})
        self.env['hotel.charge.service'].post_charge(
            folio.id, product.id, 1, 20000.0, 'to_guest')
        move = folio.action_post_invoice()
        self.assertTrue(dep.move_id, "reversal must post at invoice time")
        self.assertAlmostEqual(move.amount_residual,
                               move.amount_total - 5000.0, places=2)
        self._assert_coherent(folio, move, booking)

    def test_over_deposit_blocked_not_absorbed(self):
        # Settle straight on a fixed 1000 charge (no checkout, so no
        # room nights inflate the gross): 5000 deposit covers it fully
        # and must be refunded, never absorbed.
        booking = self._booking()
        folio = self._folio(booking)
        product = self.env['product.product'].create({
            'name': 'Math Small', 'sale_ok': True,
            'list_price': 1000.0, 'taxes_id': [(6, 0, [])]})
        self.env['hotel.charge.service'].post_charge(
            folio.id, product.id, 1, 1000.0, 'to_guest')
        booking.action_take_deposit(5000.0)
        with self.assertRaises(ValidationError):
            folio.action_settle()
        self.assertEqual(folio.state, 'open')

    def test_collect_creates_balanced_cash_entry(self):
        booking = self._booking()
        dep = booking.action_take_deposit(7500.0)
        entry = dep.payment_move_id
        self.assertEqual(entry.state, 'posted')
        self.assertAlmostEqual(sum(entry.line_ids.mapped('debit')),
                               7500.0, places=2)
        self.assertAlmostEqual(sum(entry.line_ids.mapped('credit')),
                               7500.0, places=2)
        liab = self._folio(booking)._ensure_liability_account()
        self.assertIn(liab.id, entry.line_ids.mapped('account_id').ids)

    def test_reversal_balanced_and_reconciled(self):
        booking = self._booking()
        dep = booking.action_take_deposit(5000.0)
        folio = self._folio(booking)
        move = self._charge_post_settle(folio, 20000.0, booking)
        rev = dep.move_id
        self.assertTrue(rev)
        self.assertEqual(rev.state, 'posted')
        self.assertAlmostEqual(sum(rev.line_ids.mapped('debit')),
                               5000.0, places=2)
        self.assertAlmostEqual(sum(rev.line_ids.mapped('credit')),
                               5000.0, places=2)
        partials = (rev.line_ids.mapped('matched_debit_ids')
                    + rev.line_ids.mapped('matched_credit_ids'))
        self.assertTrue(partials, "reversal must reconcile vs invoice")
        inv_lines = move.line_ids.filtered(
            lambda l: l.account_id == self.env['account.account'].browse(
                rev.line_ids.filtered(
                    lambda r: r.credit > 0).account_id.id))
        self.assertTrue(
            set(partials.mapped('debit_move_id').ids)
            & set(move.line_ids.ids)
            or set(partials.mapped('credit_move_id').ids)
            & set(move.line_ids.ids),
            "reconcile must touch the invoice")

    def test_city_ledger_takes_net_due(self):
        # Ledger only runs on open folios: charge, then transfer the
        # gross; a draft deposit blocks it until refunded, and the
        # transferred amount always equals the live balance due.
        booking = self._booking()
        folio = self._folio(booking)
        product = self.env['product.product'].create({
            'name': 'Math Ledger', 'sale_ok': True,
            'list_price': 20000.0, 'taxes_id': [(6, 0, [])]})
        self.env['hotel.charge.service'].post_charge(
            folio.id, product.id, 1, 20000.0, 'to_guest')
        folio.invalidate_recordset()
        gross = folio.amount_total
        ledger = self.env['hotel.city.ledger'].transfer(folio.id)
        self.assertAlmostEqual(ledger.amount, gross, places=2)
        # Second folio: deposit blocks, refund unblocks, gross intact.
        booking2 = self._booking()
        folio2 = self._folio(booking2)
        self.env['hotel.charge.service'].post_charge(
            folio2.id, product.id, 1, 20000.0, 'to_guest')
        dep = booking2.action_take_deposit(5000.0)
        with self.assertRaises(ValidationError):
            self.env['hotel.city.ledger'].transfer(folio2.id)
        dep.action_refund(reason="math test")
        folio2.invalidate_recordset()
        ledger2 = self.env['hotel.city.ledger'].transfer(folio2.id)
        self.assertAlmostEqual(ledger2.amount, folio2.amount_total,
                               places=2)

    def test_deposit_payment_visible_on_reservation(self):
        """Deposit cash must show in reservation Payments.

        Drives the payments refactor: collection posts a real
        inbound payment linked to the booking, not an invisible
        misc entry.
        """
        booking = self._booking()
        dep = booking.action_take_deposit(5000.0)
        payments = self.env['account.payment'].search(
            booking._payment_domain())
        self.assertTrue(
            payments,
            "collected deposit must appear in reservation Payments")
        self.assertAlmostEqual(sum(payments.mapped('amount')), 5000.0,
                               places=2)
        self.assertIn(dep.payment_move_id.id,
                      payments.mapped('move_id').ids)
