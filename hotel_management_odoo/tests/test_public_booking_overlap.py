# tests/test_public_booking_overlap.py — RED: public booking must block room even when draft.
from odoo.tests.common import TransactionCase


class TestPublicBookingOverlap(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env['room.booking.line'].search([]).unlink()
        self.env['room.booking'].search([]).unlink()
        co = self.env.company
        co.public_auto_confirm = False
        self.rtype = self.env['hotel.room.type'].create({
            'name': 'OverlapFam',
            'base_rate': 20000.0,
            'adult_capacity': 2,
            'child_capacity': 3,
            'max_occupants': 5,
            'charge_mode': 'per_room',
            'website_published': True,
        })
        meal = self.env['hotel.meal.plan'].search([('code', '=', 'BB')], limit=1)
        period = self.env['hotel.rate.period'].create({
            'name': 'OverlapH', 'start_md': '01-01', 'end_md': '12-31',
            'sequence': 10, 'priority': 10, 'company_id': co.id})
        self.env['hotel.rate.plan'].create(
            {'name': 'OverlapBB', 'code': 'BB', 'company_id': co.id})
        self.env['hotel.rate.line'].create({
            'company_id': co.id, 'period_id': period.id,
            'room_type_id': self.rtype.id, 'meal_plan_id': meal.id,
            'price': 20000.0, 'included_adults': 2,
            'included_children': 0})
        self.room = self.env['product.template'].create({
            'name': 'Overlap-TEST',
            'is_room': True,
            'room_type': 'single',
            'num_person': 5,
            'list_price': 20000.0,
            'room_type_id': self.rtype.id,
            'website_excluded': False,
            'active': True,
        })

    def _vals(self, idem, room_id=None):
        return {
            'room_id': room_id or self.room.id,
            'ci': '2026-12-01', 'co': '2026-12-03',
            'name': 'Overlap Guest', 'phone': '+254700000001',
            'adults': 2, 'children': 0, 'board': 'BB',
            'idem_key': idem,
        }

    def test_draft_public_booking_hides_room(self):
        svc = self.env['hotel.public.booking']
        self.assertIn(self.room.id, [r['id'] for r in svc.search_free('2026-12-01', '2026-12-03')])
        bk = svc.create_booking(self._vals('overlap-k1'))
        self.assertEqual(bk.state, 'draft')
        free = svc.search_free('2026-12-01', '2026-12-03')
        self.assertNotIn(
            self.room.id, [r['id'] for r in free],
            "draft public booking must block room in /book list")

    def test_second_public_booking_same_dates_rejected(self):
        svc = self.env['hotel.public.booking']
        svc.create_booking(self._vals('overlap-k2'))
        with self.assertRaisesRegex(Exception, 'room just sold'):
            svc.create_booking(self._vals('overlap-k3'))
