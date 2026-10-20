# -*- coding: utf-8 -*-
"""Task 9 RED: guest profile, ID/police, portal, loyalty, messaging.

Failing-first: repeat-guest history follows partner, expired ID blocks
check-in (configurable), portal shows folio balance. Plus document
catalogue/expiry/police export, loyalty bridge, SMS/WhatsApp templates.
"""
from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.hotel_management_odoo.controllers.guest_portal import (
    GuestPortal,
)


class TestGuestProfile(TransactionCase):
    def setUp(self):
        super().setUp()
        self.guest = self.env['res.partner'].create({
            'name': 'Repeat Guest',
            'is_hotel_guest': True,
            'nationality': 'KE',
        })
        self.room = self.env['product.template'].create({
            'name': 'G9-Room',
            'is_room': True,
            'room_type': 'single',
            'num_person': 1,
            'list_price': 10000.0,
        })
        self.doc_type = self.env['hotel.document.type'].create({
            'name': 'Passport',
            'code': 'PP',
            'company_id': self.env.company.id,
        })
        self.program = self.env['hotel.loyalty.program'].create({
            'name': 'Test Miles',
            'points_per_1000': 10.0,
            'company_id': self.env.company.id,
        })

    def _booking(self, checkin='2026-12-10 14:00:00',
                 checkout='2026-12-12 12:00:00'):
        booking = self.env['room.booking'].create({
            'partner_id': self.guest.id,
            'checkin_date': checkin,
            'checkout_date': checkout,
            'company_id': self.env.company.id,
        })
        self.env['room.booking.line'].create({
            'booking_id': booking.id,
            'room_id': self.room.id,
            'checkin_date': checkin,
            'checkout_date': checkout,
        })
        booking.action_reserve()
        return booking

    def _folio(self, total=20000.0):
        folio = self.env['hotel.folio'].create({
            'partner_id': self.guest.id,
            'company_id': self.env.company.id,
        })
        product = self.env['product.product'].search(
            [('product_tmpl_id', '=', self.room.id)], limit=1)
        self.env['hotel.folio.line'].create({
            'folio_id': folio.id,
            'product_id': product.id,
            'quantity': 1,
            'price_unit': total,
        })
        return folio

    def test_repeat_guest_history_follows_partner(self):
        b1 = self._booking()
        b2 = self._booking(checkin='2026-12-15 14:00:00',
                           checkout='2026-12-16 12:00:00')
        history = self.guest.get_stay_history()
        self.assertEqual(len(history['bookings']), 2)
        self.assertIn(b1.id, history['booking_ids'])
        self.assertIn(b2.id, history['booking_ids'])
        self.assertEqual(self.guest.stay_count, 2)

    def test_expired_id_blocks_checkin_when_enabled(self):
        self.env['ir.config_parameter'].sudo().set_str(
            'hotel.checkin.block_expired_id', '1')
        self.env['hotel.document'].create({
            'partner_id': self.guest.id,
            'type_id': self.doc_type.id,
            'number': 'EXP-1',
            'expiry_date': fields.Date.today(),
            'company_id': self.env.company.id,
        })
        # force expiry into the past (create allows any date; guard is
        # on check-in so front-desk can record what the guest showed)
        self.guest.document_ids.write(
            {'expiry_date': '2020-01-01'})
        booking = self._booking()
        with self.assertRaises(ValidationError):
            booking.action_checkin()

    def test_expired_id_allowed_when_disabled(self):
        self.env['ir.config_parameter'].sudo().set_str(
            'hotel.checkin.block_expired_id', '0')
        self.env['hotel.document'].create({
            'partner_id': self.guest.id,
            'type_id': self.doc_type.id,
            'number': 'EXP-2',
            'expiry_date': '2020-01-01',
            'company_id': self.env.company.id,
        })
        booking = self._booking()
        booking.action_checkin()
        self.assertEqual(booking.state, 'check_in')

    def test_portal_shows_folio_balance(self):
        folio = self._folio(total=20000.0)
        rows = self.guest.get_portal_folios()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['folio_id'], folio.id)
        self.assertEqual(rows[0]['balance'], 20000.0)

    def test_police_export_rows(self):
        booking = self._booking()
        booking.action_checkin()
        self.env['hotel.document'].create({
            'partner_id': self.guest.id,
            'type_id': self.doc_type.id,
            'number': 'P123',
            'expiry_date': '2030-01-01',
            'company_id': self.env.company.id,
        })
        rows = self.env['hotel.document'].export_police_report(
            self.env.company.id, '2026-12-01', '2026-12-31')
        self.assertTrue(
            any(r['guest'] == 'Repeat Guest' and r['doc_number'] == 'P123'
                for r in rows))

    def test_loyalty_earn_and_redeem(self):
        folio = self._folio(total=20000.0)
        entry = self.program.accrue_for_folio(folio)
        self.assertEqual(entry.points, 200.0)
        self.guest.invalidate_recordset(['loyalty_points'])
        self.assertEqual(self.guest.loyalty_points, 200.0)
        self.program.redeem(self.guest, 50.0)
        self.guest.invalidate_recordset(['loyalty_points'])
        self.assertEqual(self.guest.loyalty_points, 150.0)
        with self.assertRaises(ValidationError):
            self.program.redeem(self.guest, 9999.0)

    def test_loyalty_accrue_is_idempotent_per_folio(self):
        folio = self._folio(total=20000.0)
        first = self.program.accrue_for_folio(folio)
        second = self.program.accrue_for_folio(folio)
        self.assertEqual(first.id, second.id,
                         "second accrue must return the existing entry")
        self.assertEqual(self.env['hotel.loyalty.entry'].search_count([
            ('program_id', '=', self.program.id),
            ('folio_id', '=', folio.id)]), 1)

    def test_loyalty_company_mismatch_rejected(self):
        other = self.env['res.company'].create({'name': 'Other Co'})
        other_program = self.program.copy({'company_id': other.id})
        folio = self._folio()
        with self.assertRaises(ValidationError):
            other_program.accrue_for_folio(folio)

    def test_document_requires_number(self):
        with self.assertRaises(ValidationError):
            self.env['hotel.document'].create({
                'partner_id': self.guest.id,
                'type_id': self.doc_type.id,
                'number': '',
                'company_id': self.env.company.id,
            })

    def test_message_template_renders(self):
        booking = self._booking()
        text = self.env['hotel.document'].format_guest_message(
            'Hi {guest}, room {room} check-in {checkin}. Balance {balance}.',
            booking.id)
        self.assertIn('Repeat Guest', text)
        self.assertIn('G9-Room', text)

    def test_portal_controller_helpers(self):
        folio = self._folio(total=5000.0)
        rows = GuestPortal._folio_balances(self.guest)
        self.assertEqual(rows[0]['folio_id'], folio.id)
        docs = GuestPortal._guest_documents(self.guest)
        self.assertEqual(docs, [])

    def test_history_and_portal_scoped_to_allowed_companies(self):
        other = self.env['res.company'].create({'name': 'Other Co 9'})
        user = self.env['res.users'].create({
            'name': 'Desk 9',
            'login': 'desk9',
            'company_id': self.env.company.id,
            'company_ids': [(6, 0, [self.env.company.id])],
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        uenv = self.env(user=user)
        other_booking = self.env['room.booking'].create({
            'partner_id': self.guest.id,
            'checkin_date': '2026-12-10 14:00:00',
            'checkout_date': '2026-12-12 12:00:00',
            'company_id': other.id,
        })
        other_folio = self.env['hotel.folio'].create({
            'partner_id': self.guest.id,
            'company_id': other.id,
        })
        guest_u = self.guest.with_env(uenv)
        history = guest_u.get_stay_history()
        self.assertNotIn(other_booking.id, history['booking_ids'])
        self.assertNotIn(other_folio.id, history['folio_ids'])
        portal_rows = guest_u.get_portal_folios()
        self.assertEqual(
            [r['folio_id'] for r in portal_rows], [],
            "other-company folios must not leak into the portal")
        self.assertNotIn(other_folio.total, [r['total'] for r in portal_rows])

    def test_total_spent_uses_folio_total(self):
        folio = self._folio(total=20000.0)
        folio.invalidate_recordset(['total', 'amount_due'])
        self.guest.invalidate_recordset(['total_spent'])
        self.assertEqual(self.guest.total_spent, folio.total)

    def test_redeem_balance_is_company_scoped(self):
        other = self.env['res.company'].create({'name': 'Other Co L'})
        self.env['hotel.loyalty.entry'].create({
            'program_id': self.program.id,
            'partner_id': self.guest.id,
            'points': 5000.0,
            'company_id': other.id,
        })
        with self.assertRaises(ValidationError):
            self.program.redeem(self.guest, 1000.0)

    def test_id_flag_off_variants(self):
        self.env['hotel.document'].create({
            'partner_id': self.guest.id,
            'type_id': self.doc_type.id,
            'number': 'EXP-OFF',
            'expiry_date': '2020-01-01',
            'company_id': self.env.company.id,
        })
        for off in ('0', 'False', 'FALSE', 'no', 'NO', 'off', 'OFF'):
            with self.subTest(flag=off):
                self.env['ir.config_parameter'].sudo().set_str(
                    'hotel.checkin.block_expired_id', off)
                self.assertTrue(self.guest.check_documents_valid())

    def test_company_record_rules_exist(self):
        for model in ('hotel.document', 'hotel.loyalty.entry'):
            rules = self.env['ir.access'].search(
                [('model_id.model', '=', model)])
            self.assertTrue(
                rules.ids,
                "company record rule missing for %s (Task 11 owns the "
                "full matrix)" % model)

    def test_portal_cross_partner_folio_hidden(self):
        folio = self._folio(total=20000.0)
        user = self.env['res.users'].create({
            'name': 'Other Portal',
            'login': 'otherportal',
            'company_id': self.env.company.id,
            'company_ids': [(6, 0, [self.env.company.id])],
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        rows = user.partner_id.with_user(user).get_portal_folios()
        self.assertEqual(rows, [],
                         "second user must not see first user's folio")
        self.assertNotIn(folio.id, [r['folio_id'] for r in rows])

    def test_portal_documents_exclude_other_company(self):
        other = self.env['res.company'].create({'name': 'Other Co Docs'})
        self.env['hotel.document'].create({
            'partner_id': self.guest.id,
            'type_id': self.doc_type.id,
            'number': 'FOREIGN-1',
            'expiry_date': '2030-01-01',
            'company_id': other.id,
        })
        self.env['hotel.document'].create({
            'partner_id': self.guest.id,
            'type_id': self.doc_type.id,
            'number': 'HOME-1',
            'expiry_date': '2030-01-01',
            'company_id': self.env.company.id,
        })
        user = self.env['res.users'].create({
            'name': 'Desk Docs',
            'login': 'deskdocs',
            'company_id': self.env.company.id,
            'company_ids': [(6, 0, [self.env.company.id])],
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        guest_u = self.guest.with_env(self.env(user=user))
        numbers = [d['number']
                   for d in GuestPortal._guest_documents(guest_u)]
        self.assertIn('HOME-1', numbers)
        self.assertNotIn('FOREIGN-1', numbers)
