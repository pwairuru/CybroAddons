# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestPostStayWizard(TransactionCase):
    def _available_room(self):
        for room in self.env['product.template'].search(
                [('is_room', '=', True), ('num_person', '>=', 3),
                 ('room_type_id.max_occupants', '>=', 3)]):
            try:
                self.env['room.booking']._check_room_available(
                    room, '2026-11-01 14:00:00', '2026-11-03 11:00:00')
            except Exception:
                continue
            return room
        self.fail('no available room for 2026-11-01..03')

    def _two_available_rooms(self):
        found = []
        for room in self.env['product.template'].search(
                [('is_room', '=', True), ('num_person', '>=', 3),
                 ('room_type_id.max_occupants', '>=', 3)]):
            try:
                self.env['room.booking']._check_room_available(
                    room, '2026-11-01 14:00:00', '2026-11-03 11:00:00')
            except Exception:
                continue
            found.append(room)
            if len(found) == 2:
                return found
        self.fail('no two available rooms for 2026-11-01..03')

    def test_line_picker_prefills_second_room(self):
        guest = self.env['res.partner'].create({'name': 'Stay Wiz Line Guest'})
        room1, room2 = self._two_available_rooms()
        bk = self.env['room.booking'].create({
            'partner_id': guest.id,
            'room_line_ids': [
                (0, 0, {'room_id': room1.id,
                        'checkin_date': '2026-11-01 14:00:00',
                        'checkout_date': '2026-11-03 11:00:00',
                        'adults': 1, 'children': 0, 'toddlers': 0}),
                (0, 0, {'room_id': room2.id,
                        'checkin_date': '2026-11-01 14:00:00',
                        'checkout_date': '2026-11-03 11:00:00',
                        'adults': 2, 'children': 1, 'toddlers': 1}),
            ]})
        bk.action_reserve()
        lines = bk.room_line_ids.sorted('id')
        second = lines[1]
        wiz = self.env['hotel.post.stay'].with_context(
            default_booking_id=bk.id,
            default_booking_line_id=second.id).create({})
        self.assertEqual(wiz.booking_line_id, second)
        self.assertEqual(wiz.room_template_id, second.room_id)
        self.assertEqual((wiz.adults, wiz.children, wiz.toddlers),
                         (second.adults, second.children, second.toddlers))

    def test_wizard_posts_two_nights(self):
        guest = self.env['res.partner'].create({'name': 'Stay Wiz Guest'})
        room = self._available_room()
        plan = self.env['hotel.rate.plan'].search(
            [('company_id', '=', self.env.company.id)], limit=1)
        self.assertTrue(plan, 'a company rate plan must exist')
        bk = self.env['room.booking'].create({
            'partner_id': guest.id,
            'room_line_ids': [(0, 0, {'room_id': room.id,
                                      'checkin_date': '2026-11-01 14:00:00',
                                      'checkout_date': '2026-11-03 11:00:00'})]})
        bk.action_reserve()
        bk.room_line_ids[:1].write({'adults': 2, 'children': 1})
        wiz = self.env['hotel.post.stay'].with_context(
            default_booking_id=bk.id).create({})
        self.assertTrue(wiz.folio_id)
        self.assertEqual((wiz.adults, wiz.children, wiz.toddlers),
                         (2, 1, 0))
        lines = wiz.with_context(active_id=bk.id).action_post()
        self.assertEqual(len(lines), 2)
