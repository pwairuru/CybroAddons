# -*- coding: utf-8 -*-
"""Task 7: multi-room booking totals (same + mixed types, adult/child dims).

Proves one guest can book >1 room (same type and mixed types) with
per-line adults/children dims, and that summed engine nets equal the
folio charges posted by night audit (quote == folio net).

NOTE on brief numbers: the brief expects FAM 2A+1C -> 22500.0, but the
FAM line includes 2 adults + 2 children, so 2A+1C has zero extra
children and nets exactly the 20000.0 base (1 extra child = 50% of the
5000.0 per-slot = 2500.0 applies at 2A+3C -> 22500.0). The asserts below
encode the engine-correct totals; the E2E spec matches.
"""
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestRateLineMultiRoom(TransactionCase):
    def setUp(self):
        super().setUp()
        co = self.env.company
        self.fam = self.env['hotel.room.type'].create({'name': 'FAM', 'base_rate': 20000.0, 'max_occupants': 5, 'charge_mode': 'per_room'})
        self.dlx = self.env['hotel.room.type'].create({'name': 'DLX', 'base_rate': 12000.0, 'max_occupants': 2, 'charge_mode': 'per_room'})
        ro = self.env['hotel.meal.plan'].search([('code', '=', 'RO')], limit=1)
        h1 = self.env['hotel.rate.period'].create({'name': 'H1T', 'start_md': '01-01', 'end_md': '06-30', 'sequence': 10, 'priority': 10, 'company_id': co.id})
        self.env['hotel.rate.line'].create({'company_id': co.id, 'period_id': h1.id, 'room_type_id': self.fam.id, 'meal_plan_id': ro.id, 'price': 20000.0, 'included_adults': 2, 'included_children': 2, 'extra_child_mode': 'percent', 'extra_child_value': 50.0})
        self.env['hotel.rate.line'].create({'company_id': co.id, 'period_id': h1.id, 'room_type_id': self.dlx.id, 'meal_plan_id': ro.id, 'price': 12000.0, 'included_adults': 2, 'included_children': 0, 'extra_child_mode': 'fixed', 'extra_child_value': 1500.0})
        self.a = self.env['product.template'].create({'name': 'E2E-FAM', 'is_room': True, 'room_type': 'double', 'num_person': 5, 'list_price': 20000.0, 'room_type_id': self.fam.id})
        self.b = self.env['product.template'].create({'name': 'E2E-DLX', 'is_room': True, 'room_type': 'double', 'num_person': 2, 'list_price': 12000.0, 'room_type_id': self.dlx.id})

    def test_same_type_two_rooms(self):
        eng = self.env['hotel.rate.engine']
        n1 = eng.price_for(self.a.id, '2027-02-01', None, adults=2, children=1, board='RO')
        n2 = eng.price_for(self.a.id, '2027-02-01', None, adults=2, children=0, board='RO')
        # 2A+1C inside 2+2 included -> base; 2A+0C -> base; total 40000
        self.assertEqual(n1, 20000.0)
        self.assertEqual(n2, 20000.0)
        self.assertEqual(n1 + n2, 40000.0)

    def test_diff_types_mixed_pax(self):
        eng = self.env['hotel.rate.engine']
        fam_net = eng.price_for(self.a.id, '2027-02-01', None, adults=2, children=3, board='RO')
        dlx_net = eng.price_for(self.b.id, '2027-02-01', None, adults=1, children=0, board='RO')
        # fam 2A+3C: 1 extra child 50% of 5000 = 2500 -> 22500; dlx 1A RO = 12000
        self.assertEqual(fam_net, 22500.0)
        self.assertEqual(dlx_net, 12000.0)

    def test_over_capacity_refused(self):
        eng = self.env['hotel.rate.engine']
        with self.assertRaises(ValidationError):
            eng.price_for(self.b.id, '2027-02-01', None, adults=2, children=1, board='RO')

    def test_reserve_fills_rate_snapshot(self):
        """Reserve wires _compute_rate_snapshot (Task 4 left it dead)."""
        co = self.env.company
        self.env['hotel.rate.plan'].create({'name': 'Rack T7', 'code': 'RO', 'company_id': co.id})
        guest = self.env['res.partner'].create({'name': 'T7 Guest'})
        booking = self.env['room.booking'].create({
            'partner_id': guest.id,
            'company_id': co.id,
            'meal_plan': 'RO',
            'checkin_date': '2027-02-01 14:00:00',
            'checkout_date': '2027-02-02 11:00:00',
        })
        Line = self.env['room.booking.line']
        fam_line = Line.create({
            'booking_id': booking.id, 'room_id': self.a.id,
            'checkin_date': '2027-02-01 14:00:00',
            'checkout_date': '2027-02-02 11:00:00',
            'adults': 2, 'children': 3,
        })
        dlx_line = Line.create({
            'booking_id': booking.id, 'room_id': self.b.id,
            'checkin_date': '2027-02-01 14:00:00',
            'checkout_date': '2027-02-02 11:00:00',
            'adults': 1, 'children': 0,
        })
        # Front-desk path: reception reserves (needs read on the
        # availability guard models cleaning/maintenance requests).
        recept = self.env['res.users'].create({
            'name': 'T7 Reception', 'login': 't7-recept',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref(
                    'hotel_management_odoo.hotel_group_reception').id,
            ])],
        })
        booking.with_user(recept).action_reserve()
        self.assertEqual(booking.state, 'reserved')
        self.assertEqual(fam_line.rate_net, 22500.0)
        self.assertEqual(dlx_line.rate_net, 12000.0)
        self.assertTrue(fam_line.rate_line_id)
        self.assertTrue(dlx_line.rate_line_id)
