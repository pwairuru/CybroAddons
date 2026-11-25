# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestBookingOriginTable(TransactionCase):
    def test_seed_and_lookup(self):
        Origin = self.env['room.booking.origin']
        for code in ('reception', 'website', 'phone'):
            self.assertEqual(Origin._by_code(code).code, code)
        self.assertEqual(Origin._by_code('website').code, 'website')
        self.assertFalse(Origin._by_code('nope'))

    def test_duplicate_code_raises(self):
        Origin = self.env['room.booking.origin']
        with self.assertRaises(Exception):
            Origin.create({'name': 'Website Copy', 'code': 'website'})

    def test_rename_safe_and_delete_guarded(self):
        Origin = self.env['room.booking.origin']
        web = Origin._by_code('website')
        web.name = 'Web Renamed'
        self.assertEqual(Origin._by_code('website').id, web.id)
        with self.assertRaises(Exception):
            Origin._by_code('reception').unlink()
