# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestDefaultRatePlan(TransactionCase):
    def setUp(self):
        super().setUp()
        # Full control over plan ordering: drop any pre-seeded
        # company plans (rolled back with the test transaction).
        self.env['hotel.rate.plan'].search(
            [('company_id', '=', self.env.company.id)]).unlink()
        self.env.company.default_rate_plan_id = False

    def _make_plan(self, name):
        return self.env['hotel.rate.plan'].create({
            'name': name, 'company_id': self.env.company.id})

    def _make_booking(self):
        guest = self.env['res.partner'].create({'name': 'Default Plan Guest'})
        room = self.env['product.template'].create({
            'name': 'Default Plan Room', 'is_room': True,
            'num_person': 4, 'list_price': 20000.0})
        bk = self.env['room.booking'].create({
            'partner_id': guest.id,
            'room_line_ids': [(0, 0, {'room_id': room.id,
                                      'checkin_date': '2026-11-01 14:00:00',
                                      'checkout_date': '2026-11-02 11:00:00',
                                      'adults': 2})]})
        bk.action_reserve()
        return bk

    def test_company_default_wins(self):
        first = self._make_plan('AAA Other Plan')
        rack = self._make_plan('Rack')
        self.env.company.default_rate_plan_id = first
        bk = self._make_booking()
        wiz = self.env['hotel.post.stay'].with_context(
            default_booking_id=bk.id).create({})
        self.assertEqual(wiz.plan_id, first)
        self.assertNotEqual(first, rack)

    def test_rack_fallback_without_company_default(self):
        self._make_plan('AAA Other Plan')
        rack = self._make_plan('Rack')
        bk = self._make_booking()
        wiz = self.env['hotel.post.stay'].with_context(
            default_booking_id=bk.id).create({})
        self.assertEqual(wiz.plan_id, rack)

    def test_first_plan_fallback_without_rack(self):
        first = self._make_plan('AAA Other Plan')
        self._make_plan('ZZZ Another Plan')
        bk = self._make_booking()
        wiz = self.env['hotel.post.stay'].with_context(
            default_booking_id=bk.id).create({})
        self.assertEqual(wiz.plan_id, first)

    def test_other_company_default_rejected(self):
        other_co = self.env['res.company'].create({'name': 'Other Co Plan'})
        foreign = self.env['hotel.rate.plan'].create({
            'name': 'Foreign Plan', 'company_id': other_co.id})
        with self.assertRaises(ValidationError):
            self.env.company.default_rate_plan_id = foreign

    def test_legacy_foreign_default_ignored(self):
        other_co = self.env['res.company'].create({'name': 'Other Co Legacy'})
        foreign = self.env['hotel.rate.plan'].create({
            'name': 'Foreign Plan', 'company_id': other_co.id})
        own = self._make_plan('Own Plan')
        # Legacy state predating the constraint: bypass the ORM.
        self.env.cr.execute(
            'UPDATE res_company SET default_rate_plan_id=%s WHERE id=%s',
            (foreign.id, self.env.company.id))
        self.env.company.invalidate_recordset(['default_rate_plan_id'])
        bk = self._make_booking()
        wiz = self.env['hotel.post.stay'].with_context(
            default_booking_id=bk.id).create({})
        self.assertEqual(wiz.plan_id, own)
