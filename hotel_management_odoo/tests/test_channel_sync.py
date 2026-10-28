# -*- coding: utf-8 -*-
from unittest import mock

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase
from werkzeug.exceptions import Forbidden

from odoo.addons.hotel_management_odoo.controllers.channel_webhook import (
    ChannelWebhook,
)

try:
    from psycopg2 import IntegrityError
except ImportError:  # pragma: no cover - psycopg3 fallback
    from psycopg import IntegrityError


def _ota_payload(room_code='101', **overrides):
    payload = {
        'guest_name': 'OTA Guest',
        'checkin_date': '2026-12-10',
        'checkout_date': '2026-12-12',
        'room_code': room_code,
        'pax': 1,
    }
    payload.update(overrides)
    return payload


class TestChannelSync(TransactionCase):
    def setUp(self):
        super().setUp()
        self.room_101 = self.env['product.template'].create({
            'name': '101',
            'is_room': True,
            'room_type': 'single',
            'num_person': 1,
            'list_price': 10000.0,
        })
        self.plan = self.env['hotel.rate.plan'].create({
            'name': 'Channel Plan',
            'company_id': self.env.company.id,
        })

    def _enqueue(self, external_id='EXP-1', channel='expedia', **overrides):
        return self.env['hotel.channel.message'].enqueue_ota(
            channel, external_id, _ota_payload(**overrides))

    def test_same_ota_payload_twice_one_booking(self):
        first = self._enqueue()
        second = self._enqueue()
        self.assertEqual(first.id, second.id,
                         "same OTA payload must return the same queue record")
        count = self.env['room.booking'].search_count([
            ('partner_id', '=', first.booking_id.partner_id.id)])
        self.assertEqual(count, 1,
                         "same OTA payload twice must create one booking")

    def test_retry_after_error_reprocesses(self):
        with self.assertRaises(ValidationError):
            self._enqueue(external_id='EXP-ERR', room_code='NOPE')
        fixed = self.env['hotel.channel.message'].enqueue_ota(
            'expedia', 'EXP-ERR', _ota_payload(room_code='101'))
        self.assertEqual(fixed.state, 'done')
        self.assertTrue(fixed.booking_id.id)

    def test_missing_guest_raises(self):
        payload = _ota_payload()
        del payload['guest_name']
        with self.assertRaises(ValidationError):
            self.env['hotel.channel.message'].enqueue_ota(
                'expedia', 'EXP-NG', payload)

    def test_unknown_room_raises(self):
        with self.assertRaises(ValidationError):
            self._enqueue(external_id='EXP-NR', room_code='999')

    def test_checkout_before_checkin_raises(self):
        with self.assertRaises(ValidationError):
            self._enqueue(external_id='EXP-BD',
                          checkin_date='2026-12-12',
                          checkout_date='2026-12-10')

    def test_double_book_same_room_dates_raises(self):
        self._enqueue(external_id='EXP-A')
        with self.assertRaises(ValidationError):
            self._enqueue(external_id='EXP-B')

    def test_closed_dates_reject(self):
        self.env['hotel.rate.restriction'].create({
            'plan_id': self.plan.id,
            'room_template_id': self.room_101.id,
            'date_from': '2026-12-10',
            'date_to': '2026-12-12',
            'closed': True,
        })
        with self.assertRaises(ValidationError):
            self._enqueue(external_id='EXP-CLOSED',
                          rate_plan='Channel Plan')

    def test_sync_creates_folio_no_pos_orders(self):
        before = self.env['pos.order'].search_count([]) \
            if 'pos.order' in self.env else 0
        msg = self._enqueue(external_id='EXP-FOLIO')
        folio = self.env['hotel.folio'].search([
            ('booking_id', '=', msg.booking_id.id)], limit=1)
        self.assertTrue(folio.id, "OTA sync must open a folio per booking")
        after = self.env['pos.order'].search_count([]) \
            if 'pos.order' in self.env else 0
        self.assertEqual(before, after, "channel sync must not touch POS")

    def test_availability_shape(self):
        avail = self.env['hotel.channel.message'].get_availability(
            '2026-12-10', '2026-12-11', plan_id=self.plan.id)
        self.assertEqual(avail['date_from'], '2026-12-10')
        cell = next(
            c for c in avail['cells']
            if c['room_name'] == '101' and c['date'] == '2026-12-10')
        self.assertEqual(cell['status'], 'available')
        self.assertEqual(cell['price'], 10000.0)
        self.assertIn('booking_id', cell)

    def test_availability_bad_range_raises(self):
        with self.assertRaises(ValidationError):
            self.env['hotel.channel.message'].get_availability(
                '2026-12-12', '2026-12-10')

    def test_concurrent_duplicate_returns_winner(self):
        queued = self.env['hotel.channel.message'].create({
            'channel': 'expedia',
            'external_id': 'EXP-RACE',
            'company_id': self.env.company.id,
            'payload': 'null',
        })
        model_cls = type(self.env['hotel.channel.message'])
        with mock.patch.object(model_cls, 'create',
                               side_effect=IntegrityError('dup')):
            winner = self.env['hotel.channel.message'].enqueue_ota(
                'expedia', 'EXP-RACE', _ota_payload())
        self.assertEqual(winner.id, queued.id,
                         "unique conflict must re-fetch the winner")
        self.assertEqual(winner.state, 'done')
        self.assertTrue(winner.booking_id.id)
        self.assertEqual(self.env['room.booking'].search_count([
            ('id', '=', winner.booking_id.id)]), 1)

    def test_no_plan_still_checks_closed(self):
        self.env['hotel.rate.restriction'].create({
            'plan_id': self.plan.id,
            'room_template_id': self.room_101.id,
            'date_from': '2026-12-10',
            'date_to': '2026-12-12',
            'closed': True,
        })
        with self.assertRaises(ValidationError):
            self._enqueue(external_id='EXP-NOPLAN-CLOSED')

    def test_no_plan_still_checks_min_stay(self):
        self.env['hotel.rate.rule'].create({
            'plan_id': self.plan.id,
            'room_template_id': self.room_101.id,
            'period_id': self.env['hotel.rate.period'].search(
                [('start_md', '=', '12-01')], limit=1).id,
            'period_year': 2026,
            'date_from': '2026-12-10',
            'date_to': '2026-12-12',
            'adjustment_pct': 0.0,
            'min_stay': 3,
        })
        with self.assertRaises(ValidationError):
            self._enqueue(external_id='EXP-NOPLAN-MINSTAY')

    def test_ooo_room_rejected(self):
        self.env['maintenance.request'].create({
            'type': 'room',
            'room_maintenance_ids': [(6, 0, [self.room_101.id])],
        })
        # NOTE: plain try/except, not assertRaises — Odoo's assertRaises
        # rolls its block back to a savepoint, which would erase the
        # error row this test needs to inspect.
        try:
            self._enqueue(external_id='EXP-OOO')
            self.fail("OOO room must raise ValidationError")
        except ValidationError:
            pass
        msg = self.env['hotel.channel.message'].search([
            ('external_id', '=', 'EXP-OOO')], limit=1)
        self.assertEqual(msg.state, 'error')

    def test_webhook_route_is_public(self):
        import inspect
        src = inspect.getsource(ChannelWebhook.channel_webhook)
        self.assertIn('/hotel/channel/webhook', src)
        self.assertIn("auth='public'", src,
                      "OTA ingest must be public + token (no login needed)")

    def test_availability_route_stays_user(self):
        import inspect
        src = inspect.getsource(ChannelWebhook.channel_availability)
        self.assertIn("auth='user'", src,
                      "availability stays login-gated")

    def test_webhook_token_ok(self):
        ChannelWebhook._verify_token('s3cr3t', 's3cr3t')

    def test_webhook_token_mismatch_403(self):
        with self.assertRaises(Forbidden):
            ChannelWebhook._verify_token('wrong', 's3cr3t')

    def test_webhook_token_unconfigured_403(self):
        with self.assertRaises(Forbidden):
            ChannelWebhook._verify_token('s3cr3t', '')
        with self.assertRaises(Forbidden):
            ChannelWebhook._verify_token('', '')
