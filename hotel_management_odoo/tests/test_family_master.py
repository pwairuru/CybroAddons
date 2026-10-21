# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestFamilyMaster(TransactionCase):
    def setUp(self):
        super().setUp()
        self.dad = self.env.company.partner_id

    def _room(self, name):
        return self.env['product.template'].create({
            'name': name, 'is_room': True, 'list_price': 10000.0,
        })

    def _booking_with_room(self, vals=None, room=None):
        room = room or self._room('Room Test')
        now = fields.Datetime.now()
        vals = dict(vals or {})
        vals.setdefault('partner_id', self.dad.id)
        booking = self.env['room.booking'].create(vals)
        self.env['room.booking.line'].create({
            'booking_id': booking.id,
            'room_id': room.id,
            'checkin_date': now,
            'checkout_date': now + timedelta(days=1),
        })
        return booking

    def _close(self, booking):
        booking.action_reserve()
        booking.action_checkin()
        booking.action_checkout()
        booking.action_done()

    def test_checkout_one_room_keeps_master_open(self):
        master = self.env['room.booking'].create({'partner_id': self.dad.id})
        room_a = self._booking_with_room({'master_id': master.id})
        room_b = self._booking_with_room({'master_id': master.id})
        room_a.action_reserve()
        room_a.action_checkin()
        room_a.action_checkout()
        room_a.action_done()
        assert room_b.state != 'done' and master.state != 'done'

    def test_master_done_blocked_until_children_done(self):
        master = self.env['room.booking'].create({'partner_id': self.dad.id})
        child = self._booking_with_room({'master_id': master.id})
        with self.assertRaises(ValidationError):
            master.action_done()
        self._close(child)
        with self.assertRaises(ValidationError):
            master.action_done()
        master.action_cancel()
        self.assertEqual(master.state, 'cancel')

    def test_per_room_occupant_differs_from_payer(self):
        master = self.env['room.booking'].create({'partner_id': self.dad.id})
        kid = self.env['res.partner'].create({'name': 'Kid Test'})
        child = self.env['room.booking'].create({
            'partner_id': self.dad.id,
            'master_id': master.id,
            'occupant_partner_id': kid.id,
        })
        self.assertEqual(child.occupant_partner_id.id, kid.id)
        self.assertNotEqual(child.occupant_partner_id.id,
                            child.partner_id.id)

    def test_hourly_requires_hour_uom(self):
        master = self.env['room.booking'].create({'partner_id': self.dad.id})
        with self.assertRaises(ValidationError):
            self.env['room.booking'].create({
                'partner_id': self.dad.id,
                'master_id': master.id,
                'use_type': 'hourly',
            })

    def test_dayuse_rejects_overnight_span(self):
        with self.assertRaises(ValidationError):
            self.env['room.booking'].create({
                'partner_id': self.dad.id,
                'use_type': 'dayuse',
                'checkin_date': '2026-11-01 08:00:00',
                'checkout_date': '2026-11-02 18:00:00',
            })

    def test_meal_plan_hb_supplement_positive_ro_zero(self):
        booking = self.env['room.booking'].create(
            {'partner_id': self.dad.id, 'meal_plan': 'RO'})
        self.assertEqual(booking.meal_plan_supplement(), 0.0)
        booking.write({'meal_plan': 'HB'})
        self.assertGreater(booking.meal_plan_supplement(), 0.0)
        # Invalid selection values are rejected by the ORM itself
        # (ValueError) before the model constrains run.
        with self.assertRaises(ValueError):
            booking.write({'meal_plan': 'XX'})

    def test_meal_supplement_defaults_and_param_override(self):
        booking = self.env['room.booking'].create(
            {'partner_id': self.dad.id, 'meal_plan': 'BB'})
        params = self.env['ir.config_parameter'].sudo()
        params.search([('key', 'in',
                        ['hotel.meal.bb', 'hotel.meal.hb', 'hotel.meal.fb'])
                       ]).unlink()
        self.assertEqual(booking.meal_plan_supplement(), 1500.0)
        booking.write({'meal_plan': 'HB'})
        self.assertEqual(booking.meal_plan_supplement(), 3500.0)
        booking.write({'meal_plan': 'FB'})
        self.assertEqual(booking.meal_plan_supplement(), 5000.0)
        params.set_str('hotel.meal.bb', '2000')
        booking.write({'meal_plan': 'BB'})
        self.assertEqual(booking.meal_plan_supplement(), 2000.0)

    def test_booking_checkout_must_follow_checkin(self):
        with self.assertRaises(ValidationError):
            self.env['room.booking'].create({
                'partner_id': self.dad.id,
                'checkin_date': '2026-11-02 10:00:00',
                'checkout_date': '2026-11-01 10:00:00',
            })
        with self.assertRaises(ValidationError):
            self.env['room.booking'].create({
                'partner_id': self.dad.id,
                'checkin_date': '2026-11-01 10:00:00',
                'checkout_date': '2026-11-01 10:00:00',
            })

    def test_hourly_rejects_overlong_span(self):
        master = self.env['room.booking'].create({'partner_id': self.dad.id})
        with self.assertRaises(ValidationError):
            self.env['room.booking'].create({
                'partner_id': self.dad.id,
                'master_id': master.id,
                'use_type': 'hourly',
                'checkin_date': '2026-11-01 08:00:00',
                'checkout_date': '2026-11-02 04:00:00',
            })

    def test_dayuse_cap_same_day(self):
        with self.assertRaises(ValidationError):
            self.env['room.booking'].create({
                'partner_id': self.dad.id,
                'use_type': 'dayuse',
                'checkin_date': '2026-11-01 08:00:00',
                'checkout_date': '2026-11-01 23:30:00',
            })
        ok = self.env['room.booking'].create({
            'partner_id': self.dad.id,
            'use_type': 'dayuse',
            'checkin_date': '2026-11-01 08:00:00',
            'checkout_date': '2026-11-01 18:00:00',
        })
        self.assertEqual(ok.use_type, 'dayuse')

    def test_master_cancel_blocked_until_children_closed(self):
        master = self.env['room.booking'].create({'partner_id': self.dad.id})
        child = self.env['room.booking'].create(
            {'partner_id': self.dad.id, 'master_id': master.id})
        with self.assertRaises(ValidationError):
            master.action_cancel()
        child.action_cancel()
        master.action_cancel()
        self.assertEqual(master.state, 'cancel')
