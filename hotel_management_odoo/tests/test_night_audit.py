# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

try:
    from psycopg2 import IntegrityError
except ImportError:  # pragma: no cover - psycopg3 fallback
    from psycopg import IntegrityError


class TestNightAudit(TransactionCase):
    def setUp(self):
        super().setUp()
        self.partner = self.env.company.partner_id
        self.product = self.env['product.product'].search(
            [('sale_ok', '=', True)], limit=1)
        if not self.product:
            self.product = self.env['product.product'].create({
                'name': 'Test Minibar',
                'sale_ok': True,
                'list_price': 500.0,
            })
        self.folio = self.env['hotel.folio'].create(
            {'partner_id': self.partner.id})
        # Room product for night-audit posting (template + variant).
        self.room_template = self.env['product.template'].create({
            'name': 'Test Room Night',
            'is_room': True,
            'list_price': 10000.0,
        })
        self.room_product = self.room_template.product_variant_id
        # Relative to today: fixtures span yesterday→tomorrow, so the
        # audit date (yesterday) is always covered. A fixed date rots
        # as soon as "now" moves past it (broke 2026-10-21).
        self.audit_date = (date.today() - timedelta(days=1)).isoformat()

    def _make_booking(self, state='check_in', checkin_days=-1,
                      checkout_days=1):
        now = fields.Datetime.now()
        booking = self.env['room.booking'].create({
            'partner_id': self.partner.id,
            'checkin_date': now + timedelta(days=checkin_days),
            'checkout_date': now + timedelta(days=checkout_days),
            'state': state,
        })
        self.env['room.booking.line'].create({
            'booking_id': booking.id,
            'room_id': self.room_template.id,
            'checkin_date': now + timedelta(days=checkin_days),
            'checkout_date': now + timedelta(days=checkout_days),
            'uom_qty': 1.0,
        })
        return booking

    def test_closed_day_rejects_posting(self):
        audit = self.env['hotel.night.audit'].create(
            {'date': self.audit_date})
        audit.action_close()
        with self.assertRaises(ValidationError):
            self.env['hotel.charge.service'].post_charge(
                self.folio.id, self.room_product.id, 1, 10000.0,
                'to_guest', hotel_date=self.audit_date)

    def test_run_posts_room_night(self):
        booking = self._make_booking(state='check_in')
        result = self.env['hotel.night.audit'].run(self.audit_date)
        self.assertTrue(result, "run must return a flash action")
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        self.assertTrue(folio, "run must create a folio per booking")
        self.assertTrue(folio.line_ids, "run must post room night")

    def test_run_is_idempotent(self):
        self._make_booking(state='check_in')
        first = self.env['hotel.night.audit'].run(self.audit_date)
        domain = [('hotel_date', '=', self.audit_date)]
        count_first = self.env['hotel.folio.line'].search_count(domain)
        second = self.env['hotel.night.audit'].run(self.audit_date)
        count_second = self.env['hotel.folio.line'].search_count(domain)
        self.assertTrue(first and second)
        self.assertGreater(count_first, 0)
        self.assertEqual(count_first, count_second,
                         "second run(date) posts zero duplicates")

    def test_run_handles_no_show(self):
        booking = self._make_booking(state='reserved', checkin_days=-3,
                                     checkout_days=-2)
        result = self.env['hotel.night.audit'].run(self.audit_date)
        self.assertTrue(result)
        self.assertEqual(booking.state, 'cancel',
                         "past reserved booking must be no-show cancelled")

    def test_unique_audit_per_day(self):
        self.env['hotel.night.audit'].create({'date': self.audit_date})
        with self.assertRaises(IntegrityError):
            self.env['hotel.night.audit'].create({'date': self.audit_date})

    def test_run_on_manually_closed_audit_with_pending_raises(self):
        self._make_booking(state='check_in')
        audit = self.env['hotel.night.audit'].create(
            {'date': self.audit_date})
        audit.action_close()
        with self.assertRaises(ValidationError):
            self.env['hotel.night.audit'].run(self.audit_date)

    def test_run_on_closed_business_date_raises(self):
        self.env['hotel.business.date'].create(
            {'date': self.audit_date, 'is_closed': True})
        with self.assertRaises(ValidationError):
            self.env['hotel.night.audit'].run(self.audit_date)
