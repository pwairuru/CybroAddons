# tests/test_public_booking_create.py
from odoo.tests.common import TransactionCase


class TestPublicCreate(TransactionCase):
    def test_rejects_extra_keys(self):
        svc = self.env['hotel.public.booking']
        with self.assertRaises(Exception):
            svc.create_booking({'room_id': 1, 'ci': '2026-12-01', 'co': '2026-12-03',
                'name': 'A', 'phone': '+254700000000', 'model': 'res.users'})

    def test_double_idem_returns_same(self):
        svc = self.env['hotel.public.booking']
        rooms = svc.search_free('2026-12-01', '2026-12-03')
        if not rooms:
            self.skipTest('no published rooms')
        v = {'room_id': rooms[0]['id'], 'ci': '2026-12-01', 'co': '2026-12-03',
             'name': 'Test Guest', 'phone': '+254700000001', 'idem_key': 'k1'}
        b1 = svc.create_booking(v)
        b2 = svc.create_booking(v)
        self.assertEqual(b1.id, b2.id)

    def test_settings_write_through(self):
        Settings = self.env['res.config.settings']
        setting = Settings.create({})
        setting.public_auto_confirm = False
        self.assertFalse(self.env.company.public_auto_confirm)
        setting.public_auto_confirm = True
        self.assertTrue(self.env.company.public_auto_confirm)
