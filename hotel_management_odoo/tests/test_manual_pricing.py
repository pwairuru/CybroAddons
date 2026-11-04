# -*- coding: utf-8 -*-
from unittest import mock

from odoo.tests.common import TransactionCase


class TestManualPricing(TransactionCase):
    """Rent is quick-math, not cast in stone.

    Engine fills price_unit, staff can overwrite it before saving,
    Reserve keeps the manual value (engine quote stays in rate_net
    audit fields), and changing the stay dates requotes (manual is
    overwritten by design — re-edit after dates settle).
    """

    def setUp(self):
        super().setUp()
        self.dtype = self.env['hotel.room.type'].create({
            'name': 'ManualT', 'base_rate': 10000.0})
        self.room = self.env['product.template'].create({
            'name': 'RM401', 'is_room': True, 'room_type': 'double',
            'num_person': 2, 'list_price': 10000.0,
            'room_type_id': self.dtype.id})
        self.booking = self.env['room.booking'].create({
            'partner_id': self.env.company.partner_id.id,
            'checkin_date': '2027-03-10 14:00:00',
            'checkout_date': '2027-03-12 11:00:00',
            'meal_plan': 'RO',
        })
        self.line = self.env['room.booking.line'].create({
            'booking_id': self.booking.id,
            'room_id': self.room.id,
            'checkin_date': '2027-03-10 14:00:00',
            'checkout_date': '2027-03-12 11:00:00',
            'adults': 2,
            'children': 0,
        })

    def test_manual_price_persists_without_trigger_change(self):
        subtotal_auto = self.line.price_subtotal
        manual = (self.line.price_unit or 0.0) + 5000.0
        self.line.write({'price_unit': manual})
        self.line.invalidate_recordset()
        self.assertEqual(self.line.price_unit, manual)
        # Totals follow the manual price (same qty/tax, new amount).
        self.assertNotEqual(self.line.price_subtotal, subtotal_auto)

    def test_checkout_extend_requotes_over_manual(self):
        self.line.write({'price_unit': 98765.43})
        self.line.write({'checkout_date': '2027-03-13 11:00:00'})
        self.line.invalidate_recordset()
        self.assertEqual(self.line.uom_qty, 3.0)
        self.assertNotEqual(self.line.price_unit, 98765.43)

    def test_reserve_keeps_manual_price(self):
        manual = (self.line.price_unit or 0.0) + 2500.0
        self.line.write({'price_unit': manual})
        quote = {'net': 4200.0, 'lines': [], 'line_id': False,
                 'rule_id': False, 'occupancy': 0.0}
        with mock.patch.object(
                type(self.line), '_detailed_price', return_value=quote):
            self.booking.action_reserve()
        self.assertEqual(self.booking.state, 'reserved')
        self.line.invalidate_recordset()
        self.assertEqual(self.line.price_unit, manual)
        self.assertEqual(self.line.rate_net, 4200.0)
