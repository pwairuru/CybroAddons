# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestBlockedDates(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env['room.booking.line'].search([]).unlink()
        self.env['room.booking'].search([]).unlink()
        self.env['maintenance.request'].search(
            [('type', '=', 'room')]).unlink()
        self.env['cleaning.request'].search([]).unlink()
        co = self.env.company
        self.rtype = self.env['hotel.room.type'].create({
            'name': 'BlockedFam',
            'base_rate': 20000.0,
            'adult_capacity': 2,
            'child_capacity': 3,
            'max_occupants': 5,
            'charge_mode': 'per_room',
        })
        meal = self.env['hotel.meal.plan'].search([('code', '=', 'BB')], limit=1)
        period = self.env['hotel.rate.period'].create({
            'name': 'BlockedH', 'start_md': '01-01', 'end_md': '12-31',
            'sequence': 10, 'priority': 10, 'company_id': co.id})
        self.env['hotel.rate.plan'].create(
            {'name': 'BlockedBB', 'code': 'BB', 'company_id': co.id})
        self.env['hotel.rate.line'].create({
            'company_id': co.id, 'period_id': period.id,
            'room_type_id': self.rtype.id, 'meal_plan_id': meal.id,
            'price': 20000.0, 'included_adults': 2,
            'included_children': 0})
        self.room = self.env['product.template'].create({
            'name': 'Chui-TEST',
            'is_room': True,
            'room_type': 'single',
            'num_person': 5,
            'list_price': 20000.0,
            'room_type_id': self.rtype.id,
        })
        self.guest = self.env['res.partner'].create({'name': 'Blocked Guest'})
        self.pricelist = self.env['product.pricelist'].create({
            'name': 'Blocked Test Pricelist',
            'currency_id': self.env.company.currency_id.id,
            'company_id': self.env.company.id,
        })
        self.guest.property_product_pricelist = self.pricelist.id
        self.booking = self.env['room.booking'].create({
            'partner_id': self.guest.id,
            'company_id': co.id,
            'meal_plan': 'BB',
            'checkin_date': '2026-11-10 14:00:00',
            'checkout_date': '2026-11-12 11:00:00',
        })
        self.env['room.booking.line'].create({
            'booking_id': self.booking.id,
            'room_id': self.room.id,
            'company_id': co.id,
            'checkin_date': '2026-11-10 14:00:00',
            'checkout_date': '2026-11-12 11:00:00',
            'adults': 2,
        })
        self.booking.action_reserve()

    def test_blocked_excludes_checkout_day(self):
        res = self.env['hotel.daily.inventory'].get_blocked_dates(
            self.room.id, '2026-11-09', '2026-11-13')
        blocked = res['blocked']
        assert '2026-11-10' in blocked, "checkin night must block, got %s" % blocked
        assert '2026-11-11' in blocked, "middle night must block, got %s" % blocked
        assert '2026-11-12' not in blocked, "checkout day free for turnover, got %s" % blocked

    def test_ignore_own_booking_frees_dates(self):
        res = self.env['hotel.daily.inventory'].get_blocked_dates(
            self.room.id, '2026-11-09', '2026-11-13',
            ignore_booking_id=self.booking.id)
        assert res['blocked'] == [], "own booking must not block itself, got %s" % res['blocked']
        assert res['booked'] == []

    def test_turnover_checkout_on_other_checkin_allowed(self):
        """Checkout exactly on another booking's checkin is same-day
        turnover: no shared night, must reserve. Checkout mid-stay
        (a stayed night overlaps) must raise."""
        co = self.env.company
        ok_booking = self.env['room.booking'].create({
            'partner_id': self.guest.id,
            'company_id': co.id,
            'meal_plan': 'BB',
            'checkin_date': '2026-11-08 14:00:00',
            'checkout_date': '2026-11-10 11:00:00',
        })
        self.env['room.booking.line'].create({
            'booking_id': ok_booking.id,
            'room_id': self.room.id,
            'company_id': co.id,
            'checkin_date': '2026-11-08 14:00:00',
            'checkout_date': '2026-11-10 11:00:00',
            'adults': 2,
        })
        ok_booking.action_reserve()
        self.assertEqual(ok_booking.state, 'reserved')
        bad_booking = self.env['room.booking'].create({
            'partner_id': self.guest.id,
            'company_id': co.id,
            'meal_plan': 'BB',
            'checkin_date': '2026-11-09 14:00:00',
            'checkout_date': '2026-11-11 11:00:00',
        })
        # Line-level overlap guard fires at create (before Reserve).
        with self.assertRaises(Exception):
            self.env['room.booking.line'].create({
                'booking_id': bad_booking.id,
                'room_id': self.room.id,
                'company_id': co.id,
                'checkin_date': '2026-11-09 14:00:00',
                'checkout_date': '2026-11-11 11:00:00',
                'adults': 2,
            })

    def test_ooo_blocks_whole_window(self):
        self.env['maintenance.request'].create({
            'type': 'room',
            'room_maintenance_ids': [(6, 0, [self.room.id])],
        })
        res = self.env['hotel.daily.inventory'].get_blocked_dates(
            self.room.id, '2026-11-09', '2026-11-13')
        assert res['ooo'] is True
        for day in ('2026-11-09', '2026-11-12', '2026-11-13'):
            assert day in res['blocked'], "%s must block when OOO, got %s" % (day, res['blocked'])
