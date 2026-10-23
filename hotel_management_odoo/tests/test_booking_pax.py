# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestBookingPax(TransactionCase):
    def test_pax_defaults_and_negative_rejected(self):
        guest = self.env['res.partner'].create({'name': 'Pax Guest'})
        room = self.env['product.template'].search(
            [('is_room', '=', True)], limit=1)
        bk = self.env['room.booking'].create({
            'partner_id': guest.id,
            'room_line_ids': [(0, 0, {'room_id': room.id,
                                      'checkin_date': '2026-11-01 14:00:00',
                                      'checkout_date': '2026-11-02 11:00:00'})]})
        line = bk.room_line_ids[:1]
        self.assertEqual((line.adults, line.children, line.toddlers),
                         (1, 0, 0))
        with self.assertRaises(ValidationError):
            line.write({'adults': -1})
