# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestDashboardPos(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env['room.booking.line'].search([]).unlink()
        self.env['room.booking'].search([]).unlink()
        co = self.env.company
        rtype = self.env['hotel.room.type'].create({
            'name': 'POSStd', 'base_rate': 10000.0,
            'adult_capacity': 2, 'child_capacity': 0,
            'max_occupants': 2, 'charge_mode': 'per_room'})
        meal_ro = self.env['hotel.meal.plan'].search(
            [('code', '=', 'RO')], limit=1)
        period = self.env['hotel.rate.period'].create(
            {'name': 'POSH', 'start_md': '01-01', 'end_md': '12-31',
             'sequence': 10, 'priority': 10, 'company_id': co.id})
        self.env['hotel.rate.plan'].create(
            {'name': 'POSRO', 'code': 'RO', 'company_id': co.id})
        self.env['hotel.rate.line'].create(
            {'company_id': co.id, 'period_id': period.id,
             'room_type_id': rtype.id, 'meal_plan_id': meal_ro.id,
             'price': 10000.0, 'included_adults': 2,
             'included_children': 0, 'extra_adult_mode': 'fixed',
             'extra_adult_value': 0.0})
        self.room_101 = self.env['product.template'].create({
            'name': 'POS101',
            'is_room': True,
            'room_type': 'single',
            'room_type_id': rtype.id,
            'num_person': 1,
            'list_price': 10000.0,
        })
        self.guest = self.env['res.partner'].create({'name': 'POS Guest'})
        self.booking = self.env['room.booking'].create({
            'partner_id': self.guest.id,
            'checkin_date': '2026-10-19 14:00:00',
            'checkout_date': '2026-10-20 11:00:00',
        })
        self.env['room.booking.line'].create({
            'booking_id': self.booking.id,
            'room_id': self.room_101.id,
            'checkin_date': '2026-10-19 14:00:00',
            'checkout_date': '2026-10-20 11:00:00',
            'adults': 1,
        })
        self.booking.action_reserve()
        self.booking.action_checkin()

    def test_series_shape(self):
        series = self.env['hotel.daily.inventory'].get_dashboard_series(
            '2026-10-19', days=7)
        assert series['days'] == 7
        assert len(series['dates']) == 7
        assert series['dates'][0] == '2026-10-19'
        for key in ('occupancy', 'arrivals', 'departures', 'room_revenue',
                    'adr', 'revpar', 'available', 'food_orders'):
            assert key in series, "series %s missing" % key
            assert len(series[key]) == 7
        # No food lines in fixture: food series is all zeros but present.
        assert sum(series['food_orders']) == 0
        # In-house night posts revenue on 10-19 only; series must
        # agree with the single-day tiles math (no hardcoded total —
        # rate engine owns pricing).
        idx = series['dates'].index('2026-10-19')
        tiles = self.env['hotel.daily.inventory'].get_tiles('2026-10-19')
        assert series['occupancy'][idx] > 0
        assert series['occupancy'][idx] == tiles['occupancy']
        assert series['room_revenue'][idx] == tiles['room_revenue']
        assert series['room_revenue'][idx] > 0

    def _checkout_booking(self):
        """Second stay, fully completed (check_out): must still count as
        an arrival on check-in day and a departure on checkout day."""
        room_102 = self.env['product.template'].create({
            'name': 'POS102',
            'is_room': True,
            'room_type': 'single',
            'room_type_id': self.room_101.room_type_id.id,
            'num_person': 1,
            'list_price': 10000.0,
        })
        bk = self.env['room.booking'].create({
            'partner_id': self.guest.id,
            'checkin_date': '2026-10-19 14:00:00',
            'checkout_date': '2026-10-20 11:00:00',
        })
        self.env['room.booking.line'].create({
            'booking_id': bk.id,
            'room_id': room_102.id,
            'checkin_date': '2026-10-19 14:00:00',
            'checkout_date': '2026-10-20 11:00:00',
            'adults': 1,
        })
        bk.action_reserve()
        bk.action_checkin()
        bk.action_checkout()
        assert bk.state == 'check_out'
        return bk

    def test_completed_stay_counts_as_arrival_and_departure(self):
        self._checkout_booking()
        tiles_in = self.env['hotel.daily.inventory'].get_tiles('2026-10-19')
        assert tiles_in['arrivals'] == 2, \
            "completed stay must count as arrival, got %s" % tiles_in['arrivals']
        tiles_out = self.env['hotel.daily.inventory'].get_tiles('2026-10-20')
        assert tiles_out['departures'] == 2, \
            "completed stay must count as departure, got %s" % tiles_out['departures']
        series = self.env['hotel.daily.inventory'].get_dashboard_series(
            '2026-10-19', days=2)
        assert series['arrivals'][0] == 2
        assert series['departures'][1] == 2

    def test_tiles_has_folio_fields(self):
        tiles = self.env['hotel.daily.inventory'].get_tiles('2026-10-19')
        for key in ('open_folios', 'ooo', 'sellable_rooms', 'room_revenue',
                    'reserved', 'currency_symbol'):
            assert key in tiles, "tile %s missing" % key
