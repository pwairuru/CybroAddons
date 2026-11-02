# -*- coding: utf-8 -*-
"""No-show policy: configurable per company, charged or not.

RED tests for the company-level no-show switch. Policies:
  no_charge      - silent cancel, nothing posted (today's behaviour)
  first_night    - post exactly one night at the booking rate, then cancel
  forfeit_deposit- collected deposits flip to forfeited (house keeps),
                   excluded from totals and refunds, then cancel
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestNoShowPolicy(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company = self.env.company
        self.partner = self.company.partner_id
        self.room_template = self.env['product.template'].create({
            'name': 'No-Show Room',
            'is_room': True,
            'list_price': 10000.0,
        })
        self.room_product = self.room_template.product_variant_id
        self.audit_date = (fields.Date.today() - timedelta(days=1)
                           ).isoformat()

    def _make_stale_booking(self, company=None, room=None):
        now = fields.Datetime.now()
        booking = self.env['room.booking'].create({
            'partner_id': self.partner.id,
            'checkin_date': now - timedelta(days=3),
            'checkout_date': now - timedelta(days=2),
            'state': 'reserved',
        })
        if company and company.id != booking.company_id.id:
            booking.write({'company_id': company.id})
        self.env['room.booking.line'].create({
            'booking_id': booking.id,
            'room_id': (room or self.room_template).id,
            'checkin_date': now - timedelta(days=3),
            'checkout_date': now - timedelta(days=2),
            'uom_qty': 1.0,
        })
        return booking

    def test_default_policy_is_no_charge(self):
        fresh = self.env['res.company'].create({'name': 'No-Show Fresh'})
        self.assertEqual(fresh.no_show_policy, 'no_charge')
        booking = self._make_stale_booking()
        self.env['hotel.night.audit'].run(self.audit_date)
        self.assertEqual(booking.state, 'cancel')
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        self.assertFalse(folio.line_ids,
                         "no_charge must post zero lines")

    def test_first_night_posts_single_night(self):
        self.company.no_show_policy = 'first_night'
        booking = self._make_stale_booking()
        self.env['hotel.night.audit'].run(self.audit_date)
        self.assertEqual(booking.state, 'cancel')
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        self.assertTrue(folio, "first_night needs a folio to charge")
        self.assertEqual(len(folio.line_ids), 1,
                         "exactly one night may be charged")
        line = folio.line_ids[0]
        self.assertEqual(str(line.hotel_date), self.audit_date,
                         "fee posts on the open audit day")
        plan = self.env['hotel.rate.plan']._plan_for_booking(booking)
        if plan:
            try:
                expected = self.env['hotel.rate.engine'].price_detailed(
                    self.room_template.id, booking.checkin_date.date(),
                    plan.id, adults=1, children=0,
                    board=booking.meal_plan or 'RO',
                    booking=booking)['net']
            except ValidationError:
                expected = 0.0
        else:
            expected = 0.0
        if not expected:
            expected = booking.room_line_ids[:1].price_unit or 0.0
        self.assertAlmostEqual(line.price_unit, expected, places=2)
        move = folio.action_settle()
        self.assertAlmostEqual(move.amount_total, folio.amount_total,
                               places=2)

    def test_first_night_company_isolation(self):
        company_b = self.env['res.company'].create(
            {'name': 'No-Show B'})
        room_b = self.env['product.template'].create({
            'name': 'No-Show Room B',
            'is_room': True,
            'list_price': 10000.0,
        })
        self.company.no_show_policy = 'first_night'
        booking_a = self._make_stale_booking()
        booking_b = self._make_stale_booking(company=company_b,
                                             room=room_b)
        self.env['hotel.night.audit'].run(self.audit_date)
        self.env['hotel.night.audit'].with_company(
            company_b).run(self.audit_date)
        folio_a = self.env['hotel.folio'].search(
            [('booking_id', '=', booking_a.id)], limit=1)
        folio_b = self.env['hotel.folio'].search(
            [('booking_id', '=', booking_b.id)], limit=1)
        self.assertTrue(folio_a.line_ids, "charging company posts a night")
        self.assertFalse(folio_b.line_ids if folio_b else False,
                         "default company stays free")

    def test_forfeit_deposit_keeps_cash_out_of_refund(self):
        self.company.no_show_policy = 'forfeit_deposit'
        booking = self._make_stale_booking()
        folio = booking._ensure_folio()
        deposit = self.env['hotel.deposit'].create({
            'folio_id': folio.id,
            'amount': 4000.0,
        })
        deposit.action_collect()
        self.env['hotel.night.audit'].run(self.audit_date)
        self.assertEqual(booking.state, 'cancel')
        self.assertEqual(deposit.state, 'forfeited')
        self.assertAlmostEqual(folio.deposit_total, 0.0, places=2,
                               msg="forfeited deposit leaves totals")
        with self.assertRaises(ValidationError):
            deposit.action_refund()

    def test_first_night_with_deposit_offsets_no_double_dip(self):
        self.company.no_show_policy = 'first_night'
        booking = self._make_stale_booking()
        folio = booking._ensure_folio()
        deposit = self.env['hotel.deposit'].create({
            'folio_id': folio.id,
            'amount': 10.0,
        })
        deposit.action_collect()
        self.env['hotel.night.audit'].run(self.audit_date)
        self.assertEqual(booking.state, 'cancel')
        fee = folio.line_ids[:1].price_unit
        move = folio.action_settle()
        self.assertAlmostEqual(move.amount_total, fee, places=2)
        self.assertEqual(deposit.state, 'applied',
                         "settle consumes the deposit against the fee")

    def test_no_show_with_posted_invoice_stays_reserved(self):
        self.company.no_show_policy = 'first_night'
        booking = self._make_stale_booking()
        folio = booking._ensure_folio()
        self.env['hotel.charge.service'].post_charge(
            folio.id, self.room_product.id, 1, 10000.0, 'to_guest',
            hotel_date=self.audit_date)
        folio.action_post_invoice()
        self.env['hotel.night.audit'].run(self.audit_date)
        self.assertEqual(booking.state, 'reserved',
                         "posted money blocks the auto-cancel; "
                         "staff must resolve, never silent-lose")

    def test_fee_product_company_constraint(self):
        company_b = self.env['res.company'].create(
            {'name': 'No-Show Other'})
        template_b = self.env['product.template'].create({
            'name': 'Other Fee Product',
            'company_id': company_b.id,
        })
        with self.assertRaises(ValidationError):
            self.company.write({
                'no_show_fee_product_id':
                    template_b.product_variant_id.id})

    def test_custom_fee_product_used(self):
        fee_template = self.env['product.template'].create({
            'name': 'No-Show Fee',
            'list_price': 5000.0,
        })
        self.company.no_show_fee_product_id = \
            fee_template.product_variant_id.id
        self.company.no_show_policy = 'first_night'
        booking = self._make_stale_booking()
        self.env['hotel.night.audit'].run(self.audit_date)
        self.assertEqual(booking.state, 'cancel')
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        self.assertEqual(len(folio.line_ids), 1)
        line = folio.line_ids[0]
        self.assertEqual(line.product_id.id,
                         fee_template.product_variant_id.id)
        move = folio.action_settle()
        self.assertAlmostEqual(move.amount_total, line.price_total,
                               places=2)

    def test_forfeit_is_idempotent(self):
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.partner.id})
        deposit = self.env['hotel.deposit'].create({
            'folio_id': folio.id,
            'amount': 4000.0,
        })
        deposit.action_collect()
        self.assertTrue(deposit.action_forfeit())
        move_id = deposit.move_id.id
        self.assertTrue(deposit.action_forfeit())
        self.assertEqual(deposit.state, 'forfeited')
        self.assertEqual(deposit.move_id.id, move_id,
                         "second forfeit posts nothing new")
        self.assertEqual(
            self.env['hotel.deposit'].search_count(
                [('id', '=', deposit.id),
                 ('state', '=', 'forfeited')]), 1)

    def test_forfeit_uncollected_raises(self):
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.partner.id})
        deposit = self.env['hotel.deposit'].create({
            'folio_id': folio.id,
            'amount': 4000.0,
        })
        with self.assertRaises(ValidationError):
            deposit.action_forfeit()

    def test_forfeit_applied_raises(self):
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.partner.id})
        deposit = self.env['hotel.deposit'].create({
            'folio_id': folio.id,
            'amount': 4000.0,
        })
        deposit.action_collect()
        deposit.apply()
        with self.assertRaises(ValidationError):
            deposit.action_forfeit()

    def test_forfeit_move_balanced(self):
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.partner.id})
        deposit = self.env['hotel.deposit'].create({
            'folio_id': folio.id,
            'amount': 4000.0,
        })
        deposit.action_collect()
        deposit.action_forfeit(reason="test")
        move = deposit.move_id
        self.assertEqual(move.state, 'posted')
        debit = [l for l in move.line_ids if l.debit > 0]
        credit = [l for l in move.line_ids if l.credit > 0]
        self.assertEqual(len(debit), 1)
        self.assertEqual(len(credit), 1)
        self.assertAlmostEqual(debit[0].debit, 4000.0, places=2)
        self.assertAlmostEqual(credit[0].credit, 4000.0, places=2)
        self.assertEqual(debit[0].account_id.account_type,
                         'liability_current')
        self.assertEqual(credit[0].account_id.account_type, 'income')

    def test_first_night_without_room_lines_stays_reserved(self):
        self.company.no_show_policy = 'first_night'
        booking = self._make_stale_booking()
        booking.room_line_ids.unlink()
        self.env['hotel.night.audit'].run(self.audit_date)
        self.assertEqual(booking.state, 'reserved',
                         "nothing to charge; staff must resolve")

    def test_applied_deposit_blocks_charging_cancel(self):
        self.company.no_show_policy = 'forfeit_deposit'
        booking = self._make_stale_booking()
        folio = booking._ensure_folio()
        deposit = self.env['hotel.deposit'].create({
            'folio_id': folio.id,
            'amount': 4000.0,
        })
        deposit.action_collect()
        deposit.apply()
        self.env['hotel.night.audit'].run(self.audit_date)
        self.assertEqual(booking.state, 'reserved',
                         "applied money needs staff; audit must not "
                         "void around it")

    def test_audit_counts_no_show(self):
        booking = self._make_stale_booking()
        self.env['hotel.night.audit'].run(self.audit_date)
        self.assertEqual(booking.state, 'cancel')
        audit = self.env['hotel.night.audit'].search(
            [('date', '=', self.audit_date),
             ('company_id', '=', self.company.id)], limit=1)
        self.assertEqual(audit.no_show_count, 1)
