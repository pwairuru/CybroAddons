# addons/CybroAddons/hotel_management_odoo/tests/test_public_booking_service.py
from odoo.tests.common import TransactionCase
class TestPublicBookingService(TransactionCase):
    def test_search_free_returns_only_published(self):
        svc = self.env['hotel.public.booking']
        res = svc.search_free('2026-12-01', '2026-12-03')
        self.assertIsInstance(res, list)
        self.assertTrue(all('total' in r for r in res))
