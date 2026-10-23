# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestChargeAncillaries(TransactionCase):
    def _available_room(self):
        from datetime import datetime

        ci = datetime(2026, 11, 1, 14, 0, 0)
        co = datetime(2026, 11, 2, 11, 0, 0)
        for room in self.env['product.template'].search(
                [('is_room', '=', True)]):
            try:
                self.env['room.booking']._check_room_available(
                    room, ci, co, ignore_booking=None)
            except Exception:
                continue
            return room
        self.fail("No available room template for 2026-11-01..02")

    def _mk(self):
        guest = self.env['res.partner'].create({'name': 'Anc Guest'})
        room = self._available_room()
        bk = self.env['room.booking'].create({
            'partner_id': guest.id,
            'room_line_ids': [(0, 0, {'room_id': room.id,
                                      'checkin_date': '2026-11-01 14:00:00',
                                      'checkout_date': '2026-11-02 11:00:00'})]})
        bk.action_reserve()
        bk.action_checkin()
        return bk

    def _mk_draft(self):
        guest = self.env['res.partner'].create({'name': 'Anc Draft Guest'})
        room = self._available_room()
        return self.env['room.booking'].create({
            'partner_id': guest.id,
            'room_line_ids': [(0, 0, {'room_id': room.id,
                                      'checkin_date': '2026-11-01 14:00:00',
                                      'checkout_date': '2026-11-02 11:00:00'})]})

    def _mk_food(self, price=15.0):
        cat = self.env['lunch.product.category'].create(
            {'name': 'Anc Test Cat'})
        partner = self.env['res.partner'].create(
            {'name': 'Anc Supplier Partner'})
        supplier = self.env['lunch.supplier'].create(
            {'partner_id': partner.id})
        return self.env['lunch.product'].create({
            'name': 'Anc Burger', 'category_id': cat.id,
            'price': price, 'supplier_id': supplier.id})

    def _mk_vehicle(self, price_per_km=2.5):
        brand = self.env['fleet.vehicle.model.brand'].create(
            {'name': 'Anc Brand'})
        return self.env['fleet.vehicle.model'].create({
            'name': 'Anc Model', 'brand_id': brand.id,
            'price_per_km': price_per_km})

    def _mk_ticket(self, price=30.0):
        ticket = self.env['product.product'].search(
            [('service_tracking', '=', 'event')], limit=1)
        if ticket:
            return ticket
        tmpl = self.env['product.template'].create({
            'name': 'Anc Event Ticket', 'type': 'service',
            'service_tracking': 'event', 'lst_price': price})
        return tmpl.product_variant_ids[:1]

    def test_service_line_posts_once(self):
        bk = self._mk()
        svc = self.env['hotel.service'].create(
            {'name': 'Anc Spa', 'unit_price': 40.0})
        line = self.env['service.booking.line'].create(
            {'booking_id': bk.id, 'service_id': svc.id, 'uom_qty': 2})
        bk.action_charge_ancillaries()
        line.invalidate_recordset()
        self.assertTrue(line.folio_line_id)
        self.assertEqual(line.folio_line_id.source, 'service')
        self.assertEqual(line.folio_line_id.price_unit, 40.0)
        bk.action_charge_ancillaries()  # idempotent re-run
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', bk.id), ('state', '=', 'open')])
        self.assertEqual(len(folio.line_ids.filtered(
            lambda l: l.source == 'service')), 1)

    def test_food_line_posts(self):
        bk = self._mk()
        food = self._mk_food()
        line = self.env['food.booking.line'].create(
            {'booking_id': bk.id, 'food_id': food.id, 'uom_qty': 2})
        bk.action_charge_ancillaries()
        line.invalidate_recordset()
        self.assertTrue(line.folio_line_id)
        self.assertEqual(line.folio_line_id.source, 'food')
        self.assertEqual(line.folio_line_id.price_unit, food.price)

    def test_fleet_line_posts(self):
        bk = self._mk()
        vehicle = self._mk_vehicle()
        line = self.env['fleet.booking.line'].create(
            {'booking_id': bk.id, 'fleet_id': vehicle.id, 'uom_qty': 3})
        bk.action_charge_ancillaries()
        line.invalidate_recordset()
        self.assertTrue(line.folio_line_id)
        self.assertEqual(line.folio_line_id.source, 'fleet')
        self.assertEqual(
            line.folio_line_id.price_unit, vehicle.price_per_km)

    def test_event_line_posts(self):
        bk = self._mk()
        ticket = self._mk_ticket()
        line = self.env['event.booking.line'].create(
            {'booking_id': bk.id, 'ticket_id': ticket.id, 'uom_qty': 1})
        bk.action_charge_ancillaries()
        line.invalidate_recordset()
        self.assertTrue(line.folio_line_id)
        self.assertEqual(line.folio_line_id.source, 'event')

    def test_zero_unposted_rerun_is_noop(self):
        bk = self._mk()
        svc = self.env['hotel.service'].create(
            {'name': 'Anc Rerun Spa', 'unit_price': 25.0})
        line = self.env['service.booking.line'].create(
            {'booking_id': bk.id, 'service_id': svc.id})
        bk.action_charge_ancillaries()
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', bk.id), ('state', '=', 'open')])
        before = len(folio.line_ids)
        bk.action_charge_ancillaries()
        folio.invalidate_recordset()
        self.assertEqual(len(folio.line_ids), before)
        line.invalidate_recordset()
        self.assertTrue(line.folio_line_id)

    def test_non_checkin_state_guard(self):
        bk = self._mk_draft()
        self.assertNotEqual(bk.state, 'check_in')
        with self.assertRaises(ValidationError):
            bk.action_charge_ancillaries()
