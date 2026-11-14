# -*- coding: utf-8 -*-
"""Reservation deposit lifecycle: take at reservation onward, apply at pay.

Covers user ask: deposit taken right after reservation (or check-in),
then applied as payment later. Asserts folio double-entry, booking
totals include deposits, and reports surface deposits.
"""
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


def _rate_setup(env, co, rtype, price=20000.0):
    """Hermetic rate fixture: reserve prices the snapshot, and some
    DBs (prod) raise 'No rate configured' without one."""
    meal = env['hotel.meal.plan'].search([('code', '=', 'BB')], limit=1)
    period = env['hotel.rate.period'].create({
        'name': 'DepH', 'start_md': '01-01', 'end_md': '12-31',
        'sequence': 10, 'priority': 10, 'company_id': co.id})
    plan = env['hotel.rate.plan'].create({
        'name': 'DepBB', 'code': 'BB', 'company_id': co.id})
    env['hotel.rate.line'].create({
        'company_id': co.id, 'period_id': period.id,
        'room_type_id': rtype.id, 'meal_plan_id': meal.id,
        'price': price, 'included_adults': 2,
        'included_children': 0})
    return plan


class TestReservationDepositLifecycle(TransactionCase):
    def _booking_with_room(self):
        co = self.env.company
        rtype = self.env['hotel.room.type'].create({
            'name': 'DepFam', 'base_rate': 20000.0,
            'adult_capacity': 2, 'child_capacity': 2,
            'max_occupants': 4, 'charge_mode': 'per_room'})
        _rate_setup(self.env, co, rtype)
        room = self.env['product.template'].create({
            'name': 'Dep-101', 'is_room': True, 'num_person': 4,
            'list_price': 20000.0, 'room_type_id': rtype.id})
        guest = self.env['res.partner'].create({'name': 'Deposit Guest'})
        now = fields.Datetime.now()
        booking = self.env['room.booking'].create({
            'partner_id': guest.id,
            'company_id': co.id,
            'checkin_date': now + timedelta(days=-1),
            'checkout_date': now,
        })
        self.env['room.booking.line'].create({
            'booking_id': booking.id, 'room_id': room.id,
            'checkin_date': now + timedelta(days=-1),
            'checkout_date': now,
            'adults': 2, 'company_id': co.id})
        return booking

    def test_deposit_from_reservation_onward_applied_at_settle(self):
        booking = self._booking_with_room()
        booking.action_reserve()
        self.assertEqual(booking.state, 'reserved')

        # Take deposit immediately after reservation (folio auto-created).
        # HOOK: public /book will call this same entry after M-Pesa
        # confirms payment (see public_booking_service.create_booking).
        dep1 = booking.action_take_deposit(5000.0)
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        self.assertTrue(folio, "deposit must auto-create folio")
        self.assertEqual(dep1.folio_id.id, folio.id)
        self.assertEqual(dep1.state, 'draft')
        self.assertTrue(dep1.payment_move_id,
                        "take must collect cash immediately")
        self.assertEqual(dep1.payment_move_id.state, 'posted')
        folio.invalidate_recordset()
        self.assertEqual(folio.deposit_total, 5000.0)

        # Second deposit while checked in.
        booking.action_checkin()
        dep2 = booking.action_take_deposit(3000.0)
        self.assertEqual(dep2.folio_id.id, folio.id)
        folio.invalidate_recordset()
        self.assertEqual(folio.deposit_total, 8000.0)

        # Booking totals must reflect deposits (not invoices only).
        booking.invalidate_recordset()
        self.assertEqual(booking.deposit_total, 8000.0)
        self.assertGreaterEqual(booking.amount_paid, 8000.0)

        # Explicit charge (no rate-plan fixture needed): checkout then
        # invoices whatever folio lines are pending.
        product = self.env['product.product'].create({
            'name': 'Deposit Lifecycle Charge',
            'sale_ok': True,
            'list_price': 20000.0,
            'taxes_id': [(6, 0, [])],
        })
        self.env['hotel.charge.service'].post_charge(
            folio.id, product.id, 1, 20000.0, 'to_guest')
        # Checkout posts charges, settle applies deposits as payment.
        booking.action_checkout()
        folio.invalidate_recordset()
        self.assertTrue(folio.amount_total > 0.0)
        move = folio.action_settle()
        self.assertEqual(folio.state, 'settled')
        self.assertTrue(all(d.state == 'applied'
                            for d in folio.deposit_ids))
        # No negative revenue lines from deposits.
        self.assertFalse(
            move.invoice_line_ids.filtered(lambda l: l.price_unit < 0))
        # Deposit reversal consumed liability against receivable.
        self.assertTrue(dep1.move_id or dep2.move_id)
        booking.invalidate_recordset()
        self.assertEqual(booking.invoice_status, 'paid'
                         if booking.amount_due == 0 else 'invoiced')

        # Reports must surface deposits.
        folio_html = self.env['ir.actions.report']._render_qweb_html(
            'hotel_management_odoo.report_hotel_folio_statement',
            folio.ids)[0]
        self.assertIn('Deposits', str(folio_html))
        bill_html = self.env['ir.actions.report']._render_qweb_html(
            'hotel_management_odoo.report_booking_folio_bill',
            booking.ids)[0]
        self.assertIn('Deposit', str(bill_html))
        inv_html = self.env['ir.actions.report']._render_qweb_html(
            'account.report_invoice_with_payments',
            move.ids)[0]
        self.assertIn('Deposit', str(inv_html))


class TestReservationDepositGuards(TransactionCase):
    """Guards around the booking deposit entry point."""

    def _reserved_booking(self):
        co = self.env.company
        guest = self.env['res.partner'].create({'name': 'Guard Guest'})
        now = fields.Datetime.now()
        booking = self.env['room.booking'].create({
            'partner_id': guest.id,
            'company_id': co.id,
            'checkin_date': now + timedelta(days=1),
            'checkout_date': now + timedelta(days=2),
        })
        rtype = self.env['hotel.room.type'].create({
            'name': 'GuardFam', 'base_rate': 10000.0,
            'adult_capacity': 2, 'child_capacity': 0,
            'max_occupants': 2, 'charge_mode': 'per_room'})
        _rate_setup(self.env, co, rtype, price=10000.0)
        room = self.env['product.template'].create({
            'name': 'Guard-101', 'is_room': True, 'num_person': 2,
            'list_price': 10000.0, 'room_type_id': rtype.id})
        self.env['room.booking.line'].create({
            'booking_id': booking.id, 'room_id': room.id,
            'checkin_date': now + timedelta(days=1),
            'checkout_date': now + timedelta(days=2),
            'adults': 1, 'company_id': co.id})
        booking.action_reserve()
        return booking

    def test_draft_booking_cannot_take_deposit(self):
        booking = self.env['room.booking'].create({
            'partner_id': self.env.company.partner_id.id})
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            booking.action_take_deposit(1000.0)

    def test_rejects_nonpositive_amount(self):
        from odoo.exceptions import ValidationError
        booking = self._reserved_booking()
        with self.assertRaises(ValidationError):
            booking.action_take_deposit(0.0)
        with self.assertRaises(ValidationError):
            booking.action_take_deposit(-500.0)

    def test_no_amount_opens_take_deposit_dialog(self):
        booking = self._reserved_booking()
        action = booking.action_take_deposit()
        self.assertEqual(action['res_model'], 'hotel.deposit.wizard')
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        self.assertEqual(action['context']['default_folio_id'], folio.id)
        self.assertIn('default_amount', action['context'])

    def test_wizard_confirm_collects_and_applies(self):
        booking = self._reserved_booking()
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        journal = self.env['account.journal'].search(
            [('type', 'in', ('bank', 'cash')),
             ('company_id', '=', self.env.company.id)], limit=1)
        wiz = self.env['hotel.deposit.wizard'].create({
            'folio_id': folio.id, 'amount': 2500.0,
            'journal_id': journal.id})
        wiz.action_confirm()
        dep = self.env['hotel.deposit'].search(
            [('folio_id', '=', folio.id)], limit=1, order='id desc')
        self.assertEqual(dep.amount, 2500.0)
        self.assertTrue(dep.payment_id, "wizard must post a payment")
        self.assertEqual(dep.payment_move_id, dep.payment_id.move_id)
        self.assertEqual(dep.state, 'applied')
        payments = self.env['account.payment'].search(
            booking._payment_domain())
        self.assertIn(dep.payment_id.id, payments.ids)

    def test_cancel_blocked_with_open_deposits(self):
        from odoo.exceptions import ValidationError
        booking = self._reserved_booking()
        booking.action_take_deposit(2000.0)
        with self.assertRaises(ValidationError):
            booking.action_cancel()

    def test_apply_delegate_flips_draft(self):
        booking = self._reserved_booking()
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        dep = self.env['hotel.deposit'].create(
            {'folio_id': folio.id, 'amount': 1500.0})
        dep.action_collect()
        self.assertTrue(booking.action_apply_deposit())
        self.assertEqual(dep.state, 'applied')

    def test_apply_uncollected_rejected(self):
        from odoo.exceptions import ValidationError
        booking = self._reserved_booking()
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        self.env['hotel.deposit'].create(
            {'folio_id': folio.id, 'amount': 1500.0})
        with self.assertRaises(ValidationError):
            booking.action_apply_deposit()

    def test_settle_refuses_uncollected(self):
        from odoo.exceptions import ValidationError
        booking = self._reserved_booking()
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        self.env['hotel.deposit'].create(
            {'folio_id': folio.id, 'amount': 1500.0})
        with self.assertRaises(ValidationError):
            folio.action_settle()

    def test_promises_do_not_net(self):
        booking = self._reserved_booking()
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        self.env['hotel.deposit'].create(
            {'folio_id': folio.id, 'amount': 1500.0})
        folio.invalidate_recordset()
        booking.invalidate_recordset()
        self.assertEqual(folio.deposit_total, 0.0)
        self.assertEqual(booking.deposit_total, 0.0)

    def test_collect_with_posted_invoice_nets_immediately(self):
        """Deposit taken after invoicing must drop the balance at once.

        Pre-settle path: folio open, invoice posted, then Take
        Deposit collects cash. The reversal reconciles immediately
        so residual, booking Due and the wizard default all show net.
        """
        booking = self._reserved_booking()
        booking.action_checkin()
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        product = self.env['product.product'].create({
            'name': 'Early Charge', 'sale_ok': True,
            'list_price': 20000.0, 'taxes_id': [(6, 0, [])]})
        self.env['hotel.charge.service'].post_charge(
            folio.id, product.id, 1, 20000.0, 'to_guest')
        # Checkout first so the invoice covers every folio charge.
        booking.action_checkout()
        move = folio.action_post_invoice()
        self.assertEqual(move.amount_residual, move.amount_total)
        dep = booking.action_take_deposit(5000.0)
        self.assertTrue(dep.move_id, "reversal must post at once")
        net = move.amount_total - 5000.0
        self.assertAlmostEqual(move.amount_residual, net, places=2)
        folio.invalidate_recordset()
        booking.invalidate_recordset()
        self.assertAlmostEqual(folio.amount_due, net, places=2)
        self.assertAlmostEqual(booking.amount_due, net, places=2)
        wiz = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=move.ids).create({})
        self.assertAlmostEqual(wiz.amount, net, places=2)
        # Settle afterwards must not reverse a second time.
        settled = folio.action_settle()
        self.assertEqual(settled.id, move.id)
        self.assertAlmostEqual(move.amount_residual, net, places=2)

    def test_booking_views_expose_deposit(self):
        # File-based: view arch_db in DB refreshes only on -u, so assert
        # the shipped XML plus the live methods instead.
        import os
        views = os.path.join(os.path.dirname(__file__), '..', 'views',
                             'room_booking_views.xml')
        with open(os.path.normpath(views), encoding='utf-8') as fh:
            arch = fh.read()
        self.assertIn('action_take_deposit', arch)
        self.assertNotIn('action_apply_deposit', arch,
                         "manual Apply is automatic now; no button")
        self.assertIn('action_view_deposits', arch)
        self.assertIn('deposit_total', arch)
        wiz_views = os.path.join(os.path.dirname(__file__), '..',
                                 'wizard',
                                 'hotel_deposit_wizard_views.xml')
        with open(os.path.normpath(wiz_views), encoding='utf-8') as fh:
            self.assertIn('hotel.deposit.wizard', fh.read())
        booking = self._reserved_booking()
        self.assertTrue(hasattr(booking, 'action_take_deposit'))
        self.assertTrue(hasattr(booking, 'action_apply_deposit'))
        self.assertTrue(hasattr(booking, 'action_view_deposits'))
        self.assertIn('deposit_total', booking._fields)

    def test_double_collect_blocked(self):
        from odoo.exceptions import ValidationError
        booking = self._reserved_booking()
        dep = booking.action_take_deposit(1200.0)
        with self.assertRaises(ValidationError):
            dep.action_collect()

    def test_refund_after_take(self):
        booking = self._reserved_booking()
        dep = booking.action_take_deposit(1200.0)
        rev = dep.action_refund(reason="guest cancelled")
        self.assertEqual(dep.state, 'refunded')
        self.assertTrue(rev)
        booking.invalidate_recordset()
        self.assertEqual(booking.deposit_total, 0.0)

    def _settled_with_deposit(self, amount=5000.0):
        """Reserve -> checkin -> deposit -> charge 20000 -> checkout."""
        booking = self._reserved_booking()
        booking.action_checkin()
        dep = booking.action_take_deposit(amount)
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        product = self.env['product.product'].create({
            'name': 'Settle Charge', 'sale_ok': True,
            'list_price': 20000.0, 'taxes_id': [(6, 0, [])]})
        self.env['hotel.charge.service'].post_charge(
            folio.id, product.id, 1, 20000.0, 'to_guest')
        booking.action_checkout()
        move = folio.action_settle()
        return booking, folio, dep, move

    def test_settle_reconciles_deposit_against_invoice(self):
        """Settle must reconcile the deposit reversal with the invoice.

        Otherwise the invoice residual (and the Register Payment
        wizard default) stays gross even though deposits are paid.
        """
        booking, folio, dep, move = self._settled_with_deposit()
        net = move.amount_total - 5000.0
        self.assertGreater(net, 0.0)
        self.assertAlmostEqual(move.amount_residual, net, places=2)
        self.assertEqual(move.payment_state, 'partial')
        booking.invalidate_recordset()
        self.assertAlmostEqual(booking.amount_due, net, places=2)
        self.assertAlmostEqual(booking.amount_paid, 5000.0, places=2)
        wiz = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=move.ids).create({})
        self.assertAlmostEqual(wiz.amount, net, places=2)

    def test_refund_after_settle_restores_residual(self):
        """Refunding a settled deposit must give the invoice its
        balance back (unreconcile + reverse the reversal)."""
        booking, folio, dep, move = self._settled_with_deposit()
        dep.action_refund(reason="overpaid deposit returned")
        self.assertEqual(dep.state, 'refunded')
        self.assertAlmostEqual(
            move.amount_residual, move.amount_total, places=2)
        booking.invalidate_recordset()
        self.assertEqual(booking.deposit_total, 0.0)
        self.assertAlmostEqual(
            booking.amount_due, move.amount_total, places=2)
