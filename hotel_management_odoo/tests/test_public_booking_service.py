# addons/CybroAddons/hotel_management_odoo/tests/test_public_booking_service.py
from odoo.tests.common import TransactionCase
class TestPublicBookingService(TransactionCase):
    def test_search_free_returns_only_published(self):
        svc = self.env['hotel.public.booking']
        res = svc.search_free('2026-12-01', '2026-12-03')
        self.assertIsInstance(res, list)
        self.assertTrue(all('total' in r for r in res))

    def test_search_free_includes_type_id(self):
        svc = self.env['hotel.public.booking']
        rows = svc.search_free('2026-12-01', '2026-12-03')
        self.assertTrue(rows)
        ids = [r['id'] for r in rows]
        rooms = self.env['product.template'].browse(ids)
        by_id = {r.id: (r.room_type_id.id or False) for r in rooms}
        for r in rows:
            self.assertIn('type_id', r)
            self.assertEqual(r['type_id'], by_id[r['id']])
