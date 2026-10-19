# -*- coding: utf-8 -*-
"""Task 11: config-menu hiding + full security matrix + 27-report pack foundation.

Failing tests (RED before implementation):
- reception user cannot see Configuration menu
- auditor group member can close the day (night audit action_close)
- each of the 8 core reports renders PDF + XLSX with demo data
"""
from odoo.tests.common import TransactionCase


CORE_REPORTS = [
    'hotel_occupancy',
    'hotel_inhouse',
    'hotel_arrivals_departures',
    'hotel_cashier_shifts',
    'hotel_housekeeping_status',
    'hotel_flash',
    'hotel_adr_revpar',
    'hotel_asset_register',
]


class TestTask11SecurityReports(TransactionCase):

    def test_reception_cannot_see_configuration(self):
        config = self.env.ref('hotel_management_odoo.hotel_config_menu')
        reception = self.env.ref('hotel_management_odoo.hotel_group_reception')
        self.assertNotIn(reception, config.group_ids,
                         "Reception must not see Hotel > Configuration")
        manager = self.env.ref('hotel_management_odoo.hotel_group_manager')
        self.assertIn(manager, config.group_ids,
                      "Manager must see Hotel > Configuration")

    def test_auditor_can_close_day(self):
        auditor_group = self.env.ref('hotel_management_odoo.hotel_group_auditor')
        user = self.env['res.users'].create({
            'name': 'Night Auditor',
            'login': 'night_auditor_task11',
            'group_ids': [(6, 0, [auditor_group.id])],
        })
        self.assertTrue(user.has_group(
            'hotel_management_odoo.hotel_group_auditor'))
        audit = self.env['hotel.night.audit'].with_user(user).create({
            'date': '2026-10-19',
        })
        audit.with_user(user).action_close()
        self.assertEqual(audit.state, 'done')
        self.assertTrue(
            self.env['hotel.business.date'].is_day_closed('2026-10-19'))

    def test_company_scope_rules_exist(self):
        scoped = ['room.booking', 'hotel.folio', 'hotel.folio.line',
                  'hotel.cashier.shift',
                  'hotel.night.audit', 'hotel.business.date',
                  'cleaning.request', 'cleaning.team',
                  'hotel.conference', 'hotel.venue',
                  'hotel.rate.plan', 'hotel.document', 'hotel.loyalty.entry']
        for model in scoped:
            rules = self.env['ir.access'].search(
                [('model_id.model', '=', model)])
            self.assertTrue(
                rules.filtered(lambda r: 'company_ids' in (r.domain or '')),
                "Missing company-scoped rule for %s" % model)

    def test_core_reports_render_pdf_xlsx(self):
        wizard_model = self.env['hotel.report.pack']
        for report_key in CORE_REPORTS:
            action = self.env.ref(
                'hotel_management_odoo.action_report_%s' % report_key,
                raise_if_not_found=False)
            self.assertTrue(action,
                            "Missing report action for %s" % report_key)
            wizard = wizard_model.create({
                'report_type': report_key,
                'date_from': '2026-10-19',
                'date_to': '2026-10-20',
            })
            pdf = self.env['ir.actions.report']._render_qweb_pdf(
                'hotel_management_odoo.report_%s' % report_key,
                wizard.ids, data=wizard._pack_data())[0]
            self.assertTrue(pdf, "Empty PDF for %s" % report_key)
            xlsx = wizard._render_xlsx()
            self.assertTrue(xlsx, "Empty XLSX for %s" % report_key)

    def test_base_group_user_read_only_on_sensitive_models(self):
        """base.group_user keeps crud on master data but only read on
        money/movement models (folio, deposits, ledger, shifts, audits,
        business dates, channel queue, docs, loyalty); role groups own
        the write paths."""
        import csv
        import os

        import odoo.addons.hotel_management_odoo as addon

        sensitive = {
            'hotel.folio', 'hotel.folio.line', 'hotel.deposit',
            'hotel.city.ledger', 'hotel.cashier.shift',
            'hotel.business.date', 'hotel.night.audit',
            'hotel.channel.message', 'hotel.document.type',
            'hotel.document', 'hotel.loyalty.program',
            'hotel.loyalty.entry',
        }
        path = os.path.join(os.path.dirname(addon.__file__), 'security',
                             'ir.access.csv')
        with open(path, newline='') as handle:
            rows = list(csv.DictReader(handle))
        base_rows = [r for r in rows
                     if r['group_id:id'] == 'base.group_user']
        by_model = {}
        for row in base_rows:
            by_model.setdefault(row['model_id:id'], set()).add(
                row['operation'])
        for model in sensitive:
            xmlid = 'model_' + model.replace('.', '_')
            self.assertIn(
                xmlid, by_model,
                "base.group_user needs an explicit row for %s" % model)
            self.assertEqual(
                by_model[xmlid], {'r'},
                "base.group_user must be read-only on %s (role groups "
                "keep crud)" % model)
