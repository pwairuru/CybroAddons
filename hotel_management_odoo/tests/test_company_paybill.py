# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestCompanyPaybill(TransactionCase):
    def test_company_has_paybill_fields(self):
        company = self.env['res.company'].new()
        self.assertIn('mpesa_paybill_number', company._fields)
        self.assertIn('mpesa_paybill_account', company._fields)

    def test_paybill_in_pos_data_fields(self):
        fields_list = self.env['res.company']._load_pos_data_fields(False)
        self.assertIn('mpesa_paybill_number', fields_list)
        self.assertIn('mpesa_paybill_account', fields_list)

    def test_company_form_shows_paybill_fields(self):
        view = self.env.ref('base.view_company_form')
        arch = self.env['res.company'].get_view(view.id)['arch']
        self.assertIn('mpesa_paybill_number', arch)
        self.assertIn('mpesa_paybill_account', arch)

    def _snippet_view(self, key):
        return self.env['ir.ui.view'].search(
            [('key', '=', 'hotel_management_odoo.' + key)], limit=1)

    def test_snippet_templates_exist(self):
        self.assertTrue(self._snippet_view('paybill_block'))
        self.assertTrue(self._snippet_view('served_by_line'))

    def test_snippet_renders_and_hides(self):
        company = self.env.company
        company.write({'mpesa_paybill_number': '999999',
                       'mpesa_paybill_account': 'SNIPPET CO'})
        html = self.env['ir.qweb']._render(
            'hotel_management_odoo.paybill_block',
            {'company': company})
        self.assertIn('999999', html)
        self.assertIn('SNIPPET CO', html)
        company.write({'mpesa_paybill_number': False,
                       'mpesa_paybill_account': False})
        html = self.env['ir.qweb']._render(
            'hotel_management_odoo.paybill_block',
            {'company': company})
        self.assertNotIn('M-PESA', html)

    def test_served_by_first_name_only(self):
        # Contract: call sites pre-trim to first name; snippet renders
        # verbatim and stays silent when empty.
        html = self.env['ir.qweb']._render(
            'hotel_management_odoo.served_by_line',
            {'server_name': 'Pitash Campbell'.split(' ')[0]})
        self.assertIn('Served by: Pitash', html)
        self.assertNotIn('Campbell', html)
        html = self.env['ir.qweb']._render(
            'hotel_management_odoo.served_by_line', {'server_name': False})
        self.assertNotIn('Served by', html)


class TestGuestReportsPaybill(TransactionCase):
    def _arch(self, key):
        view = self.env['ir.ui.view'].search(
            [('key', '=', 'hotel_management_odoo.' + key)], limit=1)
        self.assertTrue(view, key + ' template not installed')
        return view.arch_db or ''

    def test_guest_templates_call_shared_snippet(self):
        for key in ('report_combined_bill', 'report_hotel_folio_statement',
                    'report_room_booking', 'report_sale_order'):
            arch = self._arch(key)
            self.assertIn('paybill_block', arch)
            self.assertIn('served_by_line', arch)

    def test_invoice_inherit_calls_shared_snippet(self):
        arch = self._arch('report_invoice_document_hotel_meal')
        self.assertIn('paybill_block', arch)
        self.assertIn('served_by_line', arch)

    def test_no_hardcoded_paybill_in_reports(self):
        for key in ('report_combined_bill', 'report_hotel_folio_statement',
                    'report_invoice_document_hotel_meal',
                    'report_room_booking', 'report_sale_order',
                    'paybill_block', 'served_by_line'):
            arch = self._arch(key)
            self.assertNotIn('4141717', arch)
            self.assertNotIn('CAMP DAVID UNITED', arch)

    def test_booking_report_renders_paybill_and_served_by(self):
        """End-to-end: params must reach the snippet via t-call
        attributes (body-form t-sets do not propagate in QWeb 20)."""
        booking = self.env['room.booking'].search([], limit=1)
        self.assertTrue(booking, 'no booking to render')
        html = self.env['ir.actions.report'].sudo()._render_qweb_html(
            'hotel_management_odoo.report_room_booking',
            [booking.id])[0].decode()
        company = booking.company_id
        if company.mpesa_paybill_number:
            self.assertIn(company.mpesa_paybill_number, html)
        first = (booking.create_uid.display_name or '').split(' ')[0]
        if first:
            self.assertIn('Served by: %s' % first, html)
