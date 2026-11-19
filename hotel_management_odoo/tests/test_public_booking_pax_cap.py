# tests/test_public_booking_pax_cap.py
from odoo.tests.common import TransactionCase


class TestPublicBookingPaxCap(TransactionCase):
    def test_max_pax_matches_effective_room_cap(self):
        self.assertEqual(
            self.env['hotel.public.booking'].sudo().max_pax(), 4)

    def test_max_pax_fallback_without_rooms(self):
        rooms = self.env['product.template'].search([('is_room', '=', True)])
        rooms.write({'website_excluded': True})
        self.assertEqual(
            self.env['hotel.public.booking'].sudo().max_pax(), 2)

    def test_search_free_clamps_huge_pax_to_cap(self):
        svc = self.env['hotel.public.booking'].sudo()
        gmax = svc.max_pax()
        clamped = svc.search_free(
            '2026-12-01', '2026-12-03', adults=99, children=99)
        expected = svc.search_free(
            '2026-12-01', '2026-12-03', adults=gmax, children=0)
        self.assertEqual(
            [r['id'] for r in clamped], [r['id'] for r in expected])
