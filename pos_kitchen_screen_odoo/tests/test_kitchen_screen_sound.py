# -*- coding: utf-8 -*-
"""Tests for the kitchen screen notification-sound configuration.

Run against a scratch database (never production):
    odoo -d <scratch> --stop-after-init --test-enable \\
        -u pos_kitchen_screen_odoo --test-tags pos_kitchen_screen_odoo
"""
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestKitchenScreenSound(TransactionCase):
    def test_notification_defaults(self):
        kitchen = self.env['kitchen.screen'].create({})
        self.assertEqual(kitchen.notification_sound, 'chime')
        self.assertEqual(kitchen.notification_repeat_delay, 8)

    def test_repeat_delay_bounds_accepted(self):
        kitchen = self.env['kitchen.screen'].create({})
        kitchen.write({'notification_repeat_delay': 3})
        self.assertEqual(kitchen.notification_repeat_delay, 3)
        kitchen.write({'notification_repeat_delay': 60})
        self.assertEqual(kitchen.notification_repeat_delay, 60)

    def test_repeat_delay_too_low_rejected(self):
        kitchen = self.env['kitchen.screen'].create({})
        with self.assertRaises(ValidationError):
            kitchen.write({'notification_repeat_delay': 2})

    def test_repeat_delay_too_high_rejected(self):
        with self.assertRaises(ValidationError):
            self.env['kitchen.screen'].create(
                {'notification_repeat_delay': 61})

    def test_preview_sound_returns_mp3_url(self):
        kitchen = self.env['kitchen.screen'].create(
            {'notification_sound': 'bell'})
        action = kitchen.action_preview_notification_sound()
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertEqual(action['target'], 'new')
        self.assertTrue(
            action['url'].endswith(
                '/pos_kitchen_screen_odoo/static/src/sounds/bell.mp3'))

    def test_preview_none_returns_notification(self):
        kitchen = self.env['kitchen.screen'].create(
            {'notification_sound': 'none'})
        action = kitchen.action_preview_notification_sound()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'display_notification')
