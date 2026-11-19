# tests/test_public_booking_blocked.py — RED: blocked_days occupancy query.
from odoo.tests.common import TransactionCase


class TestPublicBookingBlocked(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env['room.booking.line'].search([]).unlink()
        self.env['room.booking'].search([]).unlink()
        self.env['maintenance.request'].search(
            [('type', '=', 'room')]).unlink()
        self.env['cleaning.request'].search([]).unlink()
        # Hide pre-existing rooms so "fully booked" is deterministic:
        # only our two rooms are published.
        self.env['product.template'].search(
            [('is_room', '=', True)]).write({'website_excluded': True})
        co = self.env.company
        co.public_auto_confirm = False
        self.rtype = self.env['hotel.room.type'].create({
            'name': 'BlockedCalFam',
            'base_rate': 20000.0,
            'adult_capacity': 2,
            'child_capacity': 3,
            'max_occupants': 5,
            'charge_mode': 'per_room',
            'website_published': True,
        })
        self.rooms = self.env['product.template'].create([{
            'name': 'CalBlock-TEST-%d' % i,
            'is_room': True,
            'room_type': 'single',
            'num_person': 5,
            'list_price': 20000.0,
            'room_type_id': self.rtype.id,
            'active': True,
        } for i in (1, 2)])
        self.guest = self.env['res.partner'].create(
            {'name': 'CalBlock Guest'})
        self.pricelist = self.env['product.pricelist'].create({
            'name': 'CalBlock Test Pricelist',
            'currency_id': co.currency_id.id,
            'company_id': co.id,
        })
        self.guest.property_product_pricelist = self.pricelist.id

    def _book(self, room, ci, co):
        """Draft booking holding room over [ci, co) datetimes."""
        bk = self.env['room.booking'].create({
            'partner_id': self.guest.id,
            'company_id': self.env.company.id,
            'meal_plan': 'BB',
            'checkin_date': ci,
            'checkout_date': co,
        })
        self.env['room.booking.line'].create({
            'booking_id': bk.id,
            'room_id': room.id,
            'company_id': self.env.company.id,
            'checkin_date': ci,
            'checkout_date': co,
            'adults': 2,
        })
        return bk

    def test_fully_booked_night_listed(self):
        svc = self.env['hotel.public.booking']
        for room in self.rooms:
            self._book(room, '2027-01-06 14:00:00', '2027-01-07 11:00:00')
        self.assertIn('2027-01-06', svc.blocked_days('2027-01-05', '2027-01-08'))

    def test_partial_night_absent(self):
        svc = self.env['hotel.public.booking']
        self._book(self.rooms[0], '2027-01-05 14:00:00', '2027-01-06 11:00:00')
        self.assertNotIn(
            '2027-01-05', svc.blocked_days('2027-01-05', '2027-01-08'))

    def test_checkout_day_turnover_free(self):
        # A line checking out D 11:00 ends before night D [14:00, D+1 11:00).
        svc = self.env['hotel.public.booking']
        for room in self.rooms:
            self._book(room, '2027-01-05 14:00:00', '2027-01-06 11:00:00')
        self.assertNotIn(
            '2027-01-06', svc.blocked_days('2027-01-05', '2027-01-08'))

    def test_draft_blocks_night(self):
        svc = self.env['hotel.public.booking']
        bookings = [
            self._book(room, '2027-01-06 14:00:00', '2027-01-07 11:00:00')
            for room in self.rooms]
        for bk in bookings:
            self.assertEqual(bk.state, 'draft')
        self.assertIn('2027-01-06', svc.blocked_days('2027-01-05', '2027-01-08'))

    def test_ooo_room_stays_busy(self):
        svc = self.env['hotel.public.booking']
        self._book(self.rooms[0], '2027-01-06 14:00:00', '2027-01-07 11:00:00')
        self.env['maintenance.request'].create({
            'type': 'room',
            'room_maintenance_ids': [(6, 0, [self.rooms[1].id])],
        })
        self.assertIn('2027-01-06', svc.blocked_days('2027-01-05', '2027-01-08'))

    def test_garbage_input_returns_empty(self):
        svc = self.env['hotel.public.booking']
        self.assertEqual(svc.blocked_days('xx', '2027-01-08'), [])
        self.assertEqual(svc.blocked_days('2027-01-08', '2027-01-05'), [])
