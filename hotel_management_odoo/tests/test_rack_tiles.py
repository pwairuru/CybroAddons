# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestRackTiles(TransactionCase):
    def setUp(self):
        super().setUp()
        # Hermetic fixture: rack/tiles read every room, booking,
        # maintenance and cleaning row in the database, so pre-existing
        # dev data would leak into the math. Wipe interfering rows here;
        # TransactionCase rolls everything back at teardown.
        self.env['room.booking.line'].search([]).unlink()
        self.env['room.booking'].search([]).unlink()
        self.env['maintenance.request'].search(
            [('type', '=', 'room')]).unlink()
        self.env['cleaning.request'].search([]).unlink()
        self.room_101 = self.env['product.template'].create({
            'name': '101',
            'is_room': True,
            'room_type': 'single',
            'num_person': 1,
            'list_price': 10000.0,
        })
        self.room_102 = self.env['product.template'].create({
            'name': '102',
            'is_room': True,
            'room_type': 'single',
            'num_person': 1,
            'list_price': 8000.0,
        })
        self.guest = self.env['res.partner'].create({'name': 'Rack Guest'})
        # Deterministic pricing: fixtures assert company-currency revenue,
        # so pin the guest to a dedicated rule-free pricelist. Never reuse
        # an ambient pricelist: dev DBs carry ruled pricelists (discounts
        # change price_unit) and search() order is not guaranteed.
        self.pricelist = self.env['product.pricelist'].create({
            'name': 'Rack Test Pricelist',
            'currency_id': self.env.company.currency_id.id,
            'company_id': self.env.company.id,
        })
        self.guest.property_product_pricelist = self.pricelist.id
        self.booking = self.env['room.booking'].create({
            'partner_id': self.guest.id,
            'checkin_date': '2026-10-19 14:00:00',
            'checkout_date': '2026-10-20 11:00:00',
        })
        self.line_101 = self.env['room.booking.line'].create({
            'booking_id': self.booking.id,
            'room_id': self.room_101.id,
            'checkin_date': '2026-10-19 14:00:00',
            'checkout_date': '2026-10-20 11:00:00',
            'uom_qty': 1,
        })
        self.booking.action_reserve()
        self.booking.action_checkin()

    def _cleaning_team(self):
        return self.env['cleaning.team'].create({
            'name': 'Rack Team',
            'team_head_id': self.env.ref('base.user_admin').id,
        })

    def test_rack_shows_inhouse_room_as_occupied(self):
        rack = self.env['hotel.daily.inventory'].get_rack('2026-10-19', '2026-10-19')
        cell = next(
            c for c in rack['cells']
            if c['room_name'] == '101' and c['date'] == '2026-10-19')
        assert cell['status'] == 'occupied', "in-house room must be occupied, got %s" % cell['status']
        assert cell['display'] == 'In-House'

    def test_rack_json_shape(self):
        rack = self.env['hotel.daily.inventory'].get_rack('2026-10-19', '2026-10-20')
        assert {'room_id', 'date', 'status'} <= set(rack['cells'][0]), "rack cell must carry room_id/date/status"
        dates = sorted({c['date'] for c in rack['cells']})
        assert dates == ['2026-10-19', '2026-10-20']

    def test_tiles_math(self):
        tiles = self.env['hotel.daily.inventory'].get_tiles('2026-10-19')
        sellable = tiles['sellable_rooms']
        assert tiles['occupied'] == 1, "one room in-house"
        assert tiles['sellable_rooms'] == tiles['total_rooms'], "no OOO in fixture"
        assert tiles['occupancy'] == round(100.0 / sellable, 1)
        assert tiles['room_revenue'] == 10000.0, "1-night stay posts full total, got %s" % tiles['room_revenue']
        assert tiles['adr'] == 10000.0
        assert tiles['revpar'] == round(10000.0 / sellable, 2)
        assert tiles['arrivals'] == 1
        assert tiles['departures'] == 0, "checkout is 10-20, not 10-19"
        assert tiles['dirty'] == 0
        assert tiles['ooo'] == 0
        for key in ('occupancy', 'adr', 'revpar', 'arrivals', 'departures', 'dirty'):
            assert key in tiles, "tile %s missing" % key

    def test_per_night_split_3_night_stay(self):
        room_103 = self.env['product.template'].create({
            'name': '103',
            'is_room': True,
            'room_type': 'single',
            'num_person': 1,
            'list_price': 9000.0,
        })
        booking = self.env['room.booking'].create({
            'partner_id': self.guest.id,
            'checkin_date': '2026-10-19 14:00:00',
            'checkout_date': '2026-10-22 11:00:00',
        })
        line = self.env['room.booking.line'].create({
            'booking_id': booking.id,
            'room_id': room_103.id,
            'checkin_date': '2026-10-19 14:00:00',
            'checkout_date': '2026-10-22 11:00:00',
            'uom_qty': 3,
        })
        booking.action_reserve()
        booking.action_checkin()
        nightly = round(line.price_total / 3, 2)
        # Mid-stay day: only room 103 in-house (101 checked out 10-20).
        mid = self.env['hotel.daily.inventory'].get_tiles('2026-10-20')
        assert mid['occupied'] == 1
        assert mid['room_revenue'] == nightly, "one night share only, got %s" % mid['room_revenue']
        assert mid['adr'] == nightly
        assert mid['revpar'] == round(nightly / mid['sellable_rooms'], 2)
        # First night: 101 full total + 103 one share.
        first = self.env['hotel.daily.inventory'].get_tiles('2026-10-19')
        assert first['occupied'] == 2
        assert first['room_revenue'] == round(10000.0 + nightly, 2)
        assert first['revpar'] <= first['adr'], "revpar cannot exceed adr"

    def test_dirty_counted(self):
        self.env['cleaning.request'].create({
            'cleaning_type': 'room',
            'room_id': self.room_102.id,
            'team_id': self._cleaning_team().id,
            'assigned_id': self.env.ref('base.user_admin').id,
        })
        tiles = self.env['hotel.daily.inventory'].get_tiles('2026-10-19')
        assert tiles['dirty'] == 1, "room 102 cleaning request must count as dirty"

    def test_ooo_beats_dirty(self):
        self.env['cleaning.request'].create({
            'cleaning_type': 'room',
            'room_id': self.room_102.id,
            'team_id': self._cleaning_team().id,
            'assigned_id': self.env.ref('base.user_admin').id,
        })
        self.env['maintenance.request'].create({
            'type': 'room',
            'room_maintenance_ids': [(6, 0, [self.room_102.id])],
        })
        rack = self.env['hotel.daily.inventory'].get_rack('2026-10-19', '2026-10-19')
        cell = next(
            c for c in rack['cells']
            if c['room_name'] == '102' and c['date'] == '2026-10-19')
        assert cell['status'] == 'ooo', "OOO must win over dirty, got %s" % cell['status']
        tiles = self.env['hotel.daily.inventory'].get_tiles('2026-10-19')
        assert tiles['ooo'] == 1
        assert tiles['dirty'] == 0, "OOO room must not inflate dirty count"

    def test_reserved_vs_occupied(self):
        booking = self.env['room.booking'].create({
            'partner_id': self.guest.id,
            'checkin_date': '2026-10-19 14:00:00',
            'checkout_date': '2026-10-20 11:00:00',
        })
        self.env['room.booking.line'].create({
            'booking_id': booking.id,
            'room_id': self.room_102.id,
            'checkin_date': '2026-10-19 14:00:00',
            'checkout_date': '2026-10-20 11:00:00',
            'uom_qty': 1,
        })
        booking.action_reserve()
        rack = self.env['hotel.daily.inventory'].get_rack('2026-10-19', '2026-10-19')
        cells = {c['room_name']: c for c in rack['cells'] if c['date'] == '2026-10-19'}
        assert cells['101']['status'] == 'occupied'
        assert cells['102']['status'] == 'reserved', "reserved (not checked in) must show reserved, got %s" % cells['102']['status']
        assert cells['102']['display'] == 'Reserved'
        tiles = self.env['hotel.daily.inventory'].get_tiles('2026-10-19')
        assert tiles['occupied'] == 1
        assert tiles['reserved'] == 1
        assert tiles['room_revenue'] == 10000.0, \
            "reserved nights post no revenue, got %s" % tiles['room_revenue']
        assert tiles['adr'] == 10000.0, "ADR = in-house revenue / occupied only"

    def test_checkout_day_excluded(self):
        rack = self.env['hotel.daily.inventory'].get_rack('2026-10-20', '2026-10-20')
        cell = next(
            c for c in rack['cells']
            if c['room_name'] == '101' and c['date'] == '2026-10-20')
        assert cell['status'] != 'occupied', "checkout day is not an occupied night, got %s" % cell['status']
        tiles = self.env['hotel.daily.inventory'].get_tiles('2026-10-20')
        assert tiles['occupied'] == 0
        assert tiles['departures'] == 1, "in-house line ending 10-20 is a departure"
        assert tiles['room_revenue'] == 0.0
