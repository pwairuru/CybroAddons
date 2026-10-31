# -*- coding: utf-8 -*-
"""Billing accuracy: split, double-pay, pricing, meals, services/POS, periods."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


def _sale_product(env, name, price, taxes=None):
    prod = env['product.product'].create({
        'name': name, 'sale_ok': True, 'type': 'service',
        'list_price': price,
        'taxes_id': [(6, 0, (taxes or env['account.tax'].browse()).ids)],
    })
    return prod


def _cash_journal(env):
    journal = env['account.journal'].search([
        ('type', '=', 'cash'), ('company_id', '=', env.company.id)], limit=1)
    assert journal, "company cash journal must exist"
    return journal


class TestSplitBillingAccuracy(TransactionCase):
    def _pair(self):
        a = self.env['res.partner'].create({'name': 'Split Acc A'})
        b = self.env['res.partner'].create({'name': 'Split Acc B'})
        fa = self.env['hotel.folio'].create({'partner_id': a.id})
        fb = self.env['hotel.folio'].create({'partner_id': b.id})
        return fa, fb

    def test_split_three_ways_each_invoices_separately(self):
        fa, fb = self._pair()
        fc = self.env['hotel.folio'].create(
            {'partner_id': self.env['res.partner'].create({'name': 'Split Acc C'}).id})
        prod = _sale_product(self.env, 'Split Room Night', 1000.0)
        l1 = self.env['hotel.charge.service'].post_charge(fa.id, prod.id, 1, 1000.0, 'to_guest')
        l2 = self.env['hotel.charge.service'].post_charge(fa.id, prod.id, 1, 500.0, 'to_guest')
        l3 = self.env['hotel.charge.service'].post_charge(fa.id, prod.id, 1, 250.0, 'to_guest')
        l2.action_transfer(fb.id)
        l3.action_transfer(fc.id)
        ma = fa.action_post_invoice()
        mb = fb.action_post_invoice()
        mc = fc.action_post_invoice()
        self.assertEqual(ma.amount_total, 1000.0)
        self.assertEqual(mb.amount_total, 500.0)
        self.assertEqual(mc.amount_total, 250.0)
        self.assertEqual(ma.amount_total + mb.amount_total + mc.amount_total, 1750.0)
        self.assertEqual(fa.amount_total, 1000.0)
        self.assertEqual(fb.amount_total, 500.0)

    def test_split_taxed_lines_preserve_totals(self):
        fa, fb = self._pair()
        tax_group = self.env['account.tax.group'].create({'name': 'Split VAT Group'})
        tax = self.env['account.tax'].create({
            'name': 'Split 10%', 'amount': 10.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'tax_group_id': tax_group.id,
            'price_include_override': 'tax_excluded',
        })
        prod = _sale_product(self.env, 'Split Taxed', 1000.0, taxes=tax)
        self.env['hotel.charge.service'].post_charge(fa.id, prod.id, 1, 1000.0, 'to_guest')
        line = self.env['hotel.charge.service'].post_charge(fa.id, prod.id, 1, 500.0, 'to_guest')
        self.assertEqual(line.price_tax, 50.0)
        self.assertEqual(line.price_total, 550.0)
        line.action_transfer(fb.id)
        ma = fa.action_post_invoice()
        mb = fb.action_post_invoice()
        self.assertAlmostEqual(ma.amount_total, 1100.0, places=2)
        self.assertAlmostEqual(mb.amount_total, 550.0, places=2)
        self.assertAlmostEqual(ma.amount_total + mb.amount_total, fa.amount_total + fb.amount_total, places=2)

    def test_split_emptied_source_totals_zero(self):
        fa, fb = self._pair()
        prod = _sale_product(self.env, 'Split Move All', 400.0)
        line = self.env['hotel.charge.service'].post_charge(fa.id, prod.id, 1, 400.0, 'to_guest')
        line.action_transfer(fb.id)
        self.assertEqual(fa.amount_total, 0.0)
        self.assertEqual(fb.amount_total, 400.0)

    def test_transfer_invoiced_line_refused(self):
        fa, fb = self._pair()
        prod = _sale_product(self.env, 'Split Locked', 300.0)
        line = self.env['hotel.charge.service'].post_charge(fa.id, prod.id, 1, 300.0, 'to_guest')
        fa.action_generate_draft_invoice()
        with self.assertRaises(ValidationError):
            line.action_transfer(fb.id)
        self.assertEqual(line.folio_id.id, fa.id)


class TestDoublePayGuard(TransactionCase):
    def _paid_move(self, amount=200.0):
        partner = self.env['res.partner'].create({'name': 'No Double Pay'})
        prod = _sale_product(self.env, 'Double Pay Charge', amount)
        move = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': partner.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': prod.id, 'name': 't', 'quantity': 1,
                'price_unit': amount, 'tax_ids': [(6, 0, [])]})],
        })
        move.action_post()
        wiz = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=move.ids).create(
            {'amount': amount, 'journal_id': _cash_journal(self.env).id})
        wiz.action_create_payments()
        move.invalidate_recordset()
        return move

    def test_single_pay_zeroes_residual(self):
        move = self._paid_move(200.0)
        self.assertIn(move.payment_state, ('paid', 'in_payment'))
        self.assertEqual(move.amount_residual, 0.0)

    def test_second_pay_via_folio_register_refused(self):
        folio = self.env['hotel.folio'].create(
            {'partner_id': self.env.company.partner_id.id})
        prod = _sale_product(self.env, 'Folio Double Pay', 200.0)
        self.env['hotel.charge.service'].post_charge(folio.id, prod.id, 1, 200.0, 'to_guest')
        move = folio.action_post_invoice()
        wiz = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=move.ids).create(
            {'amount': 200.0, 'journal_id': _cash_journal(self.env).id})
        wiz.action_create_payments()
        move.invalidate_recordset()
        self.assertEqual(move.amount_residual, 0.0)
        with self.assertRaises(ValidationError):
            folio.action_register_payment()

    def test_second_payment_wizard_does_not_change_residual(self):
        move = self._paid_move(150.0)
        try:
            wiz2 = self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=move.ids).create(
                {'amount': 150.0, 'journal_id': _cash_journal(self.env).id})
            wiz2.action_create_payments()
        except Exception:
            pass
        move.invalidate_recordset()
        self.assertEqual(move.amount_residual, 0.0)
        self.assertIn(move.payment_state, ('paid', 'in_payment'))


class TestRoomPricingNightsExtras(TransactionCase):
    def setUp(self):
        super().setUp()
        self.co = self.env.company
        self.ro = self.env['hotel.meal.plan'].search([('code', '=', 'RO')], limit=1)
        self.assertTrue(self.ro, "RO meal plan must exist")
        self.rtype = self.env['hotel.room.type'].create({
            'name': 'FamAcc', 'base_rate': 20000.0,
            'adult_capacity': 3, 'child_capacity': 3, 'max_occupants': 6,
            'charge_mode': 'per_room'})
        self.period = self.env['hotel.rate.period'].create({
            'name': 'AccH1', 'start_md': '01-01', 'end_md': '12-31',
            'sequence': 10, 'priority': 10, 'company_id': self.co.id})
        self.room = self.env['product.template'].create({
            'name': 'FAM-ACC', 'is_room': True, 'room_type': 'double',
            'num_person': 6, 'list_price': 20000.0, 'room_type_id': self.rtype.id})
        self.line = self.env['hotel.rate.line'].create({
            'company_id': self.co.id, 'period_id': self.period.id,
            'room_type_id': self.rtype.id, 'meal_plan_id': self.ro.id,
            'price': 20000.0, 'included_adults': 2, 'included_children': 2,
            'extra_adult_mode': 'fixed', 'extra_adult_value': 3000.0,
            'extra_child_mode': 'percent', 'extra_child_value': 50.0})

    def test_three_nights_extra_adult_plus_child_combined(self):
        calc = self.line.compute_night(adults=3, children=3)
        # per_slot = 20000/4 = 5000; adult +3000; child 1 x 50% x 5000 = 2500
        self.assertEqual(calc['net'], 25500.0)
        self.assertEqual(calc['extra_a'], 3000.0)
        self.assertEqual(calc['extra_c'], 2500.0)
        self.assertEqual(round(calc['net'] * 3, 2), 76500.0)

    def test_extra_adult_percent_mode(self):
        self.line.write({'extra_adult_mode': 'percent', 'extra_adult_value': 100.0})
        calc = self.line.compute_night(adults=3, children=2)
        # per_slot 5000, 1 extra adult x 100% = 5000
        self.assertEqual(calc['net'], 25000.0)
        self.assertEqual(calc['extra_a'], 5000.0)

    def test_per_head_vs_per_room_mix(self):
        per_person_type = self.env['hotel.room.type'].create({
            'name': 'DormAcc', 'base_rate': 10000.0,
            'adult_capacity': 4, 'child_capacity': 4, 'max_occupants': 8,
            'charge_mode': 'per_person'})
        pp_line = self.env['hotel.rate.line'].create({
            'company_id': self.co.id, 'period_id': self.period.id,
            'room_type_id': per_person_type.id, 'meal_plan_id': self.ro.id,
            'price': 10000.0, 'included_children': 1,
            'extra_child_mode': 'fixed', 'extra_child_value': 1500.0})
        room_net = self.line.compute_night(adults=2, children=3)['net']
        head_net = pp_line.compute_night(adults=2, children=2)['net']
        self.assertEqual(room_net, 22500.0)
        self.assertEqual(head_net, 21500.0)
        self.assertEqual(room_net + head_net, 44000.0)

    def test_multinight_stay_total_posts_per_night(self):
        plan = self.env['hotel.rate.plan'].create({'name': 'AccRack', 'company_id': self.co.id})
        adult_prod = self.env['product.product'].create({'name': 'Extra Adult Acc', 'type': 'service', 'list_price': 3000.0})
        child_prod = self.env['product.product'].create({'name': 'Extra Child Acc', 'type': 'service', 'list_price': 2500.0})
        self.env['hotel.rate.occupancy'].create({
            'room_type_id': self.rtype.id, 'plan_id': plan.id, 'band': 'adult',
            'included_count': 0, 'mode': 'fixed', 'value': 0.0,
            'service_product_id': adult_prod.id})
        self.env['hotel.rate.occupancy'].create({
            'room_type_id': self.rtype.id, 'plan_id': plan.id, 'band': 'child',
            'included_count': 0, 'mode': 'fixed', 'value': 0.0,
            'service_product_id': child_prod.id})
        folio = self.env['hotel.folio'].create({'partner_id': self.co.partner_id.id})
        lines = self.env['hotel.rate.engine'].post_stay_nights(
            folio.id, self.room.id, '2027-03-01', '2027-03-04', plan.id,
            adults=3, children=3)
        # per night: 1 base + 1 adult band + 1 child band = 3 lines x 3 nights
        self.assertEqual(len(lines), 9)
        self.assertAlmostEqual(folio.amount_total, 25500.0 * 3, places=2)
        dates = sorted(set(l.hotel_date.isoformat() for l in lines))
        self.assertEqual(dates, ['2027-03-01', '2027-03-02', '2027-03-03'])


class TestMealPlanExtrasInteraction(TransactionCase):
    def setUp(self):
        super().setUp()
        self.co = self.env.company
        for code in ('RO', 'BB', 'HB', 'FB'):
            self.assertTrue(
                self.env['hotel.meal.plan'].search([('code', '=', code)], limit=1),
                "%s meal plan must exist" % code)
        self.rtype = self.env['hotel.room.type'].create({
            'name': 'MealAcc', 'base_rate': 20000.0,
            'adult_capacity': 2, 'child_capacity': 2, 'max_occupants': 4,
            'charge_mode': 'per_room'})
        self.period = self.env['hotel.rate.period'].create({
            'name': 'MealH1', 'start_md': '01-01', 'end_md': '12-31',
            'sequence': 10, 'priority': 10, 'company_id': self.co.id})
        self.room = self.env['product.template'].create({
            'name': 'MEAL-ACC', 'is_room': True, 'room_type': 'double',
            'num_person': 4, 'list_price': 20000.0, 'room_type_id': self.rtype.id})

    def _mk_line(self, board, price):
        meal = self.env['hotel.meal.plan'].search([('code', '=', board)], limit=1)
        return self.env['hotel.rate.line'].create({
            'company_id': self.co.id, 'period_id': self.period.id,
            'room_type_id': self.rtype.id, 'meal_plan_id': meal.id,
            'price': price, 'included_adults': 2, 'included_children': 0,
            'extra_adult_mode': 'fixed', 'extra_adult_value': 3000.0,
            'extra_child_mode': 'fixed', 'extra_child_value': 1500.0})

    def test_bb_hb_fb_price_differentially(self):
        ro = self._mk_line('RO', 20000.0)
        bb = self._mk_line('BB', 22000.0)
        hb = self._mk_line('HB', 25000.0)
        fb = self._mk_line('FB', 28000.0)
        self.assertEqual(ro.compute_night(adults=2)['net'], 20000.0)
        self.assertEqual(bb.compute_night(adults=2)['net'], 22000.0)
        self.assertEqual(hb.compute_night(adults=2)['net'], 25000.0)
        self.assertEqual(fb.compute_night(adults=2)['net'], 28000.0)

    def test_meal_extras_combined(self):
        bb = self._mk_line('BB', 22000.0)
        calc = bb.compute_night(adults=3, children=1)
        self.assertEqual(calc['net'], 22000.0 + 3000.0 + 1500.0)

    def test_meal_supplement_qty_is_nights_x_pax(self):
        meal_product = self.env['product.product'].create({
            'name': 'Meal Supp Acc', 'type': 'service', 'list_price': 3500.0})
        folio = self.env['hotel.folio'].create({'partner_id': self.co.partner_id.id})
        now = fields.Datetime.now()
        booking = self.env['room.booking'].create({
            'partner_id': self.co.partner_id.id, 'meal_plan': 'HB'})
        self.env['room.booking.line'].create({
            'booking_id': booking.id, 'room_id': self.room.id,
            'checkin_date': now, 'checkout_date': now + timedelta(days=2)})
        lines = booking.post_meal_supplement(folio.id, meal_product.id, nights=2)
        self.assertTrue(lines)
        # single room num_person=4 -> pax 4 x 2 nights = 8
        self.assertEqual(sum(lines.mapped('quantity')), 8.0)
        for line in lines:
            self.assertTrue(line.hotel_date)
            self.assertTrue(line.room_template_id)

    def test_ro_posts_no_supplement(self):
        meal_product = self.env['product.product'].create({
            'name': 'Meal Supp RO', 'type': 'service', 'list_price': 3500.0})
        folio = self.env['hotel.folio'].create({'partner_id': self.co.partner_id.id})
        now = fields.Datetime.now()
        booking = self.env['room.booking'].create({
            'partner_id': self.co.partner_id.id, 'meal_plan': 'RO'})
        self.env['room.booking.line'].create({
            'booking_id': booking.id, 'room_id': self.room.id,
            'checkin_date': now, 'checkout_date': now + timedelta(days=1)})
        self.assertFalse(booking.post_meal_supplement(folio.id, meal_product.id, nights=1))


class TestServicesPosInvoicingSplit(TransactionCase):
    def test_service_line_reaches_invoice(self):
        folio = self.env['hotel.folio'].create({'partner_id': self.env.company.partner_id.id})
        prod = _sale_product(self.env, 'Service Acc', 500.0)
        self.env['hotel.charge.service'].post_charge(
            folio.id, prod.id, 2, 500.0, 'to_guest', source='service')
        move = folio.action_post_invoice()
        self.assertEqual(move.amount_total, 1000.0)

    def test_pos_sourced_line_invoices_and_splits(self):
        fa = self.env['hotel.folio'].create({'partner_id': self.env.company.partner_id.id})
        fb = self.env['hotel.folio'].create(
            {'partner_id': self.env['res.partner'].create({'name': 'POS Split B'}).id})
        prod = _sale_product(self.env, 'POS Acc', 1000.0)
        line = self.env['hotel.charge.service'].post_charge(
            fa.id, prod.id, 1, 1000.0, 'to_guest', source='pos')
        self.assertEqual(line.source, 'pos')
        line.action_transfer(fb.id)
        self.assertEqual(fa.amount_total, 0.0)
        mb = fb.action_post_invoice()
        self.assertEqual(mb.amount_total, 1000.0)
        self.assertEqual(mb.hotel_folio_id.id, fb.id)

    def test_combined_room_plus_service_total(self):
        folio = self.env['hotel.folio'].create({'partner_id': self.env.company.partner_id.id})
        room_prod = _sale_product(self.env, 'Room Acc', 20000.0)
        svc_prod = _sale_product(self.env, 'Svc Acc', 1500.0)
        self.env['hotel.charge.service'].post_charge(folio.id, room_prod.id, 1, 20000.0, 'to_guest')
        self.env['hotel.charge.service'].post_charge(
            folio.id, svc_prod.id, 2, 1500.0, 'to_guest', source='service')
        self.assertEqual(folio.amount_total, 23000.0)
        move = folio.action_post_invoice()
        self.assertEqual(move.amount_total, 23000.0)


class TestRatePeriodAccuracy(TransactionCase):
    def setUp(self):
        super().setUp()
        self.co = self.env.company
        self.ro = self.env['hotel.meal.plan'].search([('code', '=', 'RO')], limit=1)
        self.rtype = self.env['hotel.room.type'].create({
            'name': 'SeasonAcc', 'base_rate': 10000.0,
            'adult_capacity': 2, 'child_capacity': 0, 'max_occupants': 2,
            'charge_mode': 'per_room'})
        self.jan = self.env['hotel.rate.period'].create({
            'name': 'AccJan', 'start_md': '01-01', 'end_md': '01-31',
            'sequence': 10, 'priority': 10, 'company_id': self.co.id})
        self.feb = self.env['hotel.rate.period'].create({
            'name': 'AccFeb', 'start_md': '02-01', 'end_md': '02-28',
            'sequence': 10, 'priority': 10, 'company_id': self.co.id})
        for period, price in ((self.jan, 10000.0), (self.feb, 12000.0)):
            self.env['hotel.rate.line'].create({
                'company_id': self.co.id, 'period_id': period.id,
                'room_type_id': self.rtype.id, 'meal_plan_id': self.ro.id,
                'price': price})
        self.room = self.env['product.template'].create({
            'name': 'SEASON-ACC', 'is_room': True, 'room_type': 'double',
            'num_person': 2, 'list_price': 10000.0, 'room_type_id': self.rtype.id})
        self.plan = self.env['hotel.rate.plan'].create({'name': 'SeasonRack', 'company_id': self.co.id})

    def test_midstay_spans_two_period_prices(self):
        eng = self.env['hotel.rate.engine']
        p1 = eng.price_for(self.room.id, '2027-01-31', self.plan.id, adults=2, board='RO')
        p2 = eng.price_for(self.room.id, '2027-02-01', self.plan.id, adults=2, board='RO')
        self.assertEqual(p1, 10000.0)
        self.assertEqual(p2, 12000.0)
        folio = self.env['hotel.folio'].create({'partner_id': self.co.partner_id.id})
        lines = eng.post_stay_nights(
            folio.id, self.room.id, '2027-01-31', '2027-02-02', self.plan.id, adults=2)
        self.assertEqual(len(lines), 2)
        self.assertAlmostEqual(folio.amount_total, 22000.0, places=2)

    def test_checkout_night_not_charged(self):
        folio = self.env['hotel.folio'].create({'partner_id': self.co.partner_id.id})
        lines = self.env['hotel.rate.engine'].post_stay_nights(
            folio.id, self.room.id, '2027-02-10', '2027-02-12', self.plan.id, adults=2)
        dates = sorted(l.hotel_date.isoformat() for l in lines)
        self.assertEqual(dates, ['2027-02-10', '2027-02-11'])

    def test_zero_night_raises(self):
        folio = self.env['hotel.folio'].create({'partner_id': self.co.partner_id.id})
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.engine'].post_stay_nights(
                folio.id, self.room.id, '2027-02-10', '2027-02-10', self.plan.id, adults=2)

    def test_closed_night_rejects_whole_stay(self):
        self.env['hotel.business.date'].create({
            'date': '2027-02-11', 'is_closed': True, 'company_id': self.co.id})
        folio = self.env['hotel.folio'].create({'partner_id': self.co.partner_id.id})
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.engine'].post_stay_nights(
                folio.id, self.room.id, '2027-02-10', '2027-02-12', self.plan.id, adults=2)
        self.assertEqual(self.env['hotel.folio.line'].search_count([('folio_id', '=', folio.id)]), 0)


class TestNumericAccuracyExtras(TransactionCase):
    def test_tax_included_vs_excluded_recompute(self):
        tax_group = self.env['account.tax.group'].create({'name': 'Incl VAT Group'})
        tax_excl = self.env['account.tax'].create({
            'name': 'Excl 10%', 'amount': 10.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'tax_group_id': tax_group.id,
            'price_include_override': 'tax_excluded'})
        tax_incl = self.env['account.tax'].create({
            'name': 'Incl 10%', 'amount': 10.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'tax_group_id': tax_group.id,
            'price_include_override': 'tax_included'})
        folio = self.env['hotel.folio'].create({'partner_id': self.env.company.partner_id.id})
        prod_e = _sale_product(self.env, 'Tax Excl', 1000.0, taxes=tax_excl)
        prod_i = _sale_product(self.env, 'Tax Incl', 1100.0, taxes=tax_incl)
        le = self.env['hotel.charge.service'].post_charge(folio.id, prod_e.id, 1, 1000.0, 'to_guest')
        li = self.env['hotel.charge.service'].post_charge(folio.id, prod_i.id, 1, 1100.0, 'to_guest')
        self.assertAlmostEqual(le.price_total, 1100.0, places=2)
        # 1100 incl 10% -> total stays 1100, subtotal 1000
        self.assertAlmostEqual(li.price_total, 1100.0, places=2)
        self.assertAlmostEqual(li.price_subtotal, 1000.0, places=2)

    def test_percent_rounding_drift_bounded(self):
        co = self.env.company
        ro = self.env['hotel.meal.plan'].search([('code', '=', 'RO')], limit=1)
        rtype = self.env['hotel.room.type'].create({
            'name': 'RoundAcc', 'base_rate': 10000.0,
            'adult_capacity': 1, 'child_capacity': 2, 'max_occupants': 3,
            'charge_mode': 'per_room'})
        period = self.env['hotel.rate.period'].create({
            'name': 'RoundH1', 'start_md': '01-01', 'end_md': '12-31',
            'sequence': 10, 'priority': 10, 'company_id': co.id})
        line = self.env['hotel.rate.line'].create({
            'company_id': co.id, 'period_id': period.id,
            'room_type_id': rtype.id, 'meal_plan_id': ro.id,
            'price': 10000.0, 'included_adults': 1, 'included_children': 2,
            'extra_child_mode': 'percent', 'extra_child_value': 33.33})
        calc = line.compute_night(adults=1, children=3)
        # per_slot = 10000/3; 1 extra child x 33.33% -> ~1111.00; net rounds to 2dp
        self.assertEqual(calc['net'], round(10000.0 + calc['extra_c'], 2))
        self.assertLess(abs((calc['net'] * 3) - round(calc['net'] * 3, 2)), 0.011)

    def test_negative_qty_rejected(self):
        folio = self.env['hotel.folio'].create({'partner_id': self.env.company.partner_id.id})
        prod = _sale_product(self.env, 'Neg Acc', 100.0)
        with self.assertRaises(ValidationError):
            self.env['hotel.charge.service'].post_charge(folio.id, prod.id, 0, 100.0, 'to_guest')
        with self.assertRaises(ValidationError):
            self.env['hotel.charge.service'].post_charge(folio.id, prod.id, -1, 100.0, 'to_guest')


class TestDepositSettleMath(TransactionCase):
    def test_deposit_reduces_due_and_settle_keeps_gross(self):
        folio = self.env['hotel.folio'].create({'partner_id': self.env.company.partner_id.id})
        prod = _sale_product(self.env, 'Deposit Room', 10000.0)
        self.env['hotel.charge.service'].post_charge(folio.id, prod.id, 1, 10000.0, 'to_guest')
        self.env['hotel.deposit'].create({'folio_id': folio.id, 'amount': 3000.0})
        folio.invalidate_recordset()
        self.assertAlmostEqual(folio.deposit_total, 3000.0, places=2)
        self.assertAlmostEqual(folio.amount_paid, 3000.0, places=2)
        self.assertAlmostEqual(folio.amount_due, 7000.0, places=2)
        move = folio.action_settle()
        self.assertAlmostEqual(move.amount_total, 10000.0, places=2)
        self.assertEqual(folio.state, 'settled')
        self.assertAlmostEqual(folio.amount_due, 0.0, places=2)

    def test_full_cover_deposit_refuses_settle(self):
        folio = self.env['hotel.folio'].create({'partner_id': self.env.company.partner_id.id})
        prod = _sale_product(self.env, 'Deposit Full', 5000.0)
        self.env['hotel.charge.service'].post_charge(folio.id, prod.id, 1, 5000.0, 'to_guest')
        self.env['hotel.deposit'].create({'folio_id': folio.id, 'amount': 5000.0})
        with self.assertRaises(ValidationError):
            folio.action_settle()

    def test_draft_invoice_idempotent(self):
        folio = self.env['hotel.folio'].create({'partner_id': self.env.company.partner_id.id})
        prod = _sale_product(self.env, 'Draft Idem', 1200.0)
        self.env['hotel.charge.service'].post_charge(folio.id, prod.id, 1, 1200.0, 'to_guest')
        d1 = folio.action_generate_draft_invoice()
        n1 = len(d1.invoice_line_ids)
        d2 = folio.action_generate_draft_invoice()
        self.assertEqual(d1.id, d2.id)
        self.assertEqual(len(d2.invoice_line_ids), n1)
        move = folio.action_post_invoice()
        self.assertEqual(move.id, d1.id)
        self.assertEqual(move.state, 'posted')


class TestPartialPaymentMath(TransactionCase):
    def test_partial_then_full_payment_tracks_residual(self):
        folio = self.env['hotel.folio'].create({'partner_id': self.env.company.partner_id.id})
        prod = _sale_product(self.env, 'Partial Pay', 1000.0)
        self.env['hotel.charge.service'].post_charge(folio.id, prod.id, 1, 1000.0, 'to_guest')
        move = folio.action_post_invoice()
        journal = _cash_journal(self.env)
        wiz1 = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=move.ids).create(
            {'amount': 400.0, 'journal_id': journal.id})
        wiz1.action_create_payments()
        move.invalidate_recordset()
        self.assertAlmostEqual(move.amount_residual, 600.0, places=2)
        self.assertEqual(move.payment_state, 'partial')
        folio.invalidate_recordset()
        self.assertAlmostEqual(folio.amount_paid, 400.0, places=2)
        self.assertAlmostEqual(folio.amount_due, 600.0, places=2)
        wiz2 = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=move.ids).create(
            {'amount': 600.0, 'journal_id': journal.id})
        wiz2.action_create_payments()
        move.invalidate_recordset()
        self.assertAlmostEqual(move.amount_residual, 0.0, places=2)
        self.assertIn(move.payment_state, ('paid', 'in_payment'))
        with self.assertRaises(ValidationError):
            folio.action_register_payment()


class TestFolioTotalsTruth(TransactionCase):
    def test_multiline_taxed_totals_sum(self):
        tax_group = self.env['account.tax.group'].create({'name': 'Truth VAT Group'})
        tax = self.env['account.tax'].create({
            'name': 'Truth 10%', 'amount': 10.0, 'amount_type': 'percent',
            'type_tax_use': 'sale', 'tax_group_id': tax_group.id,
            'price_include_override': 'tax_excluded'})
        folio = self.env['hotel.folio'].create({'partner_id': self.env.company.partner_id.id})
        prod = _sale_product(self.env, 'Truth Line', 1000.0, taxes=tax)
        self.env['hotel.charge.service'].post_charge(folio.id, prod.id, 1, 1000.0, 'to_guest')
        self.env['hotel.charge.service'].post_charge(folio.id, prod.id, 2, 500.0, 'to_guest')
        folio.invalidate_recordset()
        # untaxed 2000, tax 200, total 2200
        self.assertAlmostEqual(folio.amount_untaxed, 2000.0, places=2)
        self.assertAlmostEqual(folio.amount_tax, 200.0, places=2)
        self.assertAlmostEqual(folio.amount_total, 2200.0, places=2)
        self.assertAlmostEqual(
            folio.amount_total, sum(folio.line_ids.mapped('price_total')), places=2)
        move = folio.action_post_invoice()
        self.assertAlmostEqual(move.amount_total, folio.amount_total, places=2)
        self.assertAlmostEqual(move.amount_untaxed, folio.amount_untaxed, places=2)


class TestExtraBedIsolation(TransactionCase):
    def test_extra_bed_price_does_not_change_night_net(self):
        co = self.env.company
        ro = self.env['hotel.meal.plan'].search([('code', '=', 'RO')], limit=1)
        rtype = self.env['hotel.room.type'].create({
            'name': 'BedIso', 'base_rate': 20000.0,
            'adult_capacity': 2, 'child_capacity': 0, 'max_occupants': 3,
            'charge_mode': 'per_room'})
        period = self.env['hotel.rate.period'].create({
            'name': 'BedIsoH1', 'start_md': '01-01', 'end_md': '12-31',
            'sequence': 10, 'priority': 10, 'company_id': co.id})
        line = self.env['hotel.rate.line'].create({
            'company_id': co.id, 'period_id': period.id,
            'room_type_id': rtype.id, 'meal_plan_id': ro.id,
            'price': 20000.0, 'included_adults': 2,
            'extra_adult_mode': 'fixed', 'extra_adult_value': 3000.0,
            'extra_bed_price': 5000.0})
        base = line.compute_night(adults=3)
        line.write({'extra_bed_price': 0.0})
        nobed = line.compute_night(adults=3)
        self.assertEqual(base['net'], nobed['net'])
        self.assertEqual(base['net'], 23000.0)


class TestPerPersonMultinight(TransactionCase):
    def test_per_person_three_nights_posts_per_night(self):
        co = self.env.company
        ro = self.env['hotel.meal.plan'].search([('code', '=', 'RO')], limit=1)
        rtype = self.env['hotel.room.type'].create({
            'name': 'PPMulti', 'base_rate': 8000.0,
            'adult_capacity': 2, 'child_capacity': 0, 'max_occupants': 2,
            'charge_mode': 'per_person'})
        period = self.env['hotel.rate.period'].create({
            'name': 'PPMultiH1', 'start_md': '01-01', 'end_md': '12-31',
            'sequence': 10, 'priority': 10, 'company_id': co.id})
        self.env['hotel.rate.line'].create({
            'company_id': co.id, 'period_id': period.id,
            'room_type_id': rtype.id, 'meal_plan_id': ro.id, 'price': 8000.0})
        room = self.env['product.template'].create({
            'name': 'PP-MULTI', 'is_room': True, 'room_type': 'double',
            'num_person': 2, 'list_price': 8000.0, 'room_type_id': rtype.id})
        plan = self.env['hotel.rate.plan'].create({'name': 'PPMultiRack', 'company_id': co.id})
        folio = self.env['hotel.folio'].create({'partner_id': co.partner_id.id})
        lines = self.env['hotel.rate.engine'].post_stay_nights(
            folio.id, room.id, '2027-05-01', '2027-05-04', plan.id, adults=2)
        self.assertEqual(len(lines), 3)
        # 8000 x 2 adults = 16000/night x 3 = 48000
        self.assertAlmostEqual(folio.amount_total, 48000.0, places=2)


class TestBoardRuleSupplement(TransactionCase):
    def test_hb_board_rule_posts_per_person_per_night(self):
        co = self.env.company
        rtype = self.env['hotel.room.type'].create({
            'name': 'BoardRule', 'base_rate': 20000.0,
            'adult_capacity': 2, 'child_capacity': 2, 'max_occupants': 4,
            'charge_mode': 'per_room'})
        room = self.env['product.template'].create({
            'name': 'BOARD-RULE', 'is_room': True, 'room_type': 'double',
            'num_person': 2, 'list_price': 20000.0, 'room_type_id': rtype.id})
        self.env['hotel.board.rule'].create({
            'company_id': co.id, 'room_type_id': rtype.id, 'board': 'HB',
            'date_from': '2026-01-01', 'date_to': '2028-12-31',
            'supplement': 4000.0})
        meal_product = self.env['product.product'].create({
            'name': 'HB Board Prod', 'type': 'service', 'list_price': 4000.0})
        folio = self.env['hotel.folio'].create({'partner_id': co.partner_id.id})
        now = fields.Datetime.now()
        booking = self.env['room.booking'].create({
            'partner_id': co.partner_id.id, 'meal_plan': 'HB'})
        self.env['room.booking.line'].create({
            'booking_id': booking.id, 'room_id': room.id,
            'checkin_date': now, 'checkout_date': now + timedelta(days=2)})
        lines = booking.post_meal_supplement(folio.id, meal_product.id, nights=2)
        self.assertTrue(lines)
        self.assertAlmostEqual(sum(lines.mapped('quantity')), 4.0, places=2)
        for line in lines:
            self.assertAlmostEqual(line.price_unit, 4000.0, places=2)

    def test_multiroom_supplement_splits_per_capacity(self):
        co = self.env.company
        rtype = self.env['hotel.room.type'].create({
            'name': 'BoardMulti', 'base_rate': 20000.0,
            'adult_capacity': 2, 'child_capacity': 2, 'max_occupants': 4,
            'charge_mode': 'per_room'})
        rooms = self.env['product.template'].create([{
            'name': 'BOARD-M1', 'is_room': True, 'room_type': 'double',
            'num_person': 2, 'list_price': 20000.0, 'room_type_id': rtype.id,
        }, {
            'name': 'BOARD-M2', 'is_room': True, 'room_type': 'double',
            'num_person': 2, 'list_price': 20000.0, 'room_type_id': rtype.id,
        }])
        meal_product = self.env['product.product'].create({
            'name': 'HB Multi Prod', 'type': 'service', 'list_price': 3500.0})
        folio = self.env['hotel.folio'].create({'partner_id': co.partner_id.id})
        now = fields.Datetime.now()
        booking = self.env['room.booking'].create({
            'partner_id': co.partner_id.id, 'meal_plan': 'HB'})
        for room in rooms:
            self.env['room.booking.line'].create({
                'booking_id': booking.id, 'room_id': room.id,
                'checkin_date': now, 'checkout_date': now + timedelta(days=2)})
        lines = booking.post_meal_supplement(folio.id, meal_product.id, nights=2)
        self.assertTrue(lines)
        # 2 rooms x 2 pax x 2 nights = 8
        self.assertAlmostEqual(sum(lines.mapped('quantity')), 8.0, places=2)


class TestCapacityGuards(TransactionCase):
    def test_over_capacity_and_negative_pax_raise(self):
        co = self.env.company
        ro = self.env['hotel.meal.plan'].search([('code', '=', 'RO')], limit=1)
        rtype = self.env['hotel.room.type'].create({
            'name': 'CapGuard', 'base_rate': 10000.0,
            'adult_capacity': 2, 'child_capacity': 0, 'max_occupants': 2,
            'charge_mode': 'per_room'})
        period = self.env['hotel.rate.period'].create({
            'name': 'CapGuardH1', 'start_md': '01-01', 'end_md': '12-31',
            'sequence': 10, 'priority': 10, 'company_id': co.id})
        self.env['hotel.rate.line'].create({
            'company_id': co.id, 'period_id': period.id,
            'room_type_id': rtype.id, 'meal_plan_id': ro.id, 'price': 10000.0})
        room = self.env['product.template'].create({
            'name': 'CAP-GUARD', 'is_room': True, 'room_type': 'double',
            'num_person': 2, 'list_price': 10000.0, 'room_type_id': rtype.id})
        plan = self.env['hotel.rate.plan'].create({'name': 'CapRack', 'company_id': co.id})
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.engine'].price_for(
                room.id, '2027-06-01', plan.id, adults=3, board='RO')
        with self.assertRaises(ValidationError):
            self.env['hotel.rate.engine'].price_for(
                room.id, '2027-06-01', plan.id, adults=-1, board='RO')
