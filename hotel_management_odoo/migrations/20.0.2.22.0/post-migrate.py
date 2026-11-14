# -*- coding: utf-8 -*-
"""Backfill deposit reversals for money collected before the fix.

Two pre-fix gaps, both leave the invoice residual gross:
1. collected deposits never reversed (folio still open, invoice
   already posted): post the reversal and reconcile at once.
2. reversed at settle but never reconciled: reconcile now.
Uncollected promises are untouched (collect or cancel them first).
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Deposits = env['hotel.deposit']

    pending = Deposits.search([
        ('payment_move_id', '!=', False),
        ('move_id', '=', False),
        ('state', 'in', ('draft', 'applied')),
    ])
    for dep in pending:
        try:
            dep._reverse_against_posted_invoices()
        except Exception as exc:
            dep.folio_id.message_post(
                body="Deposit backfill skipped: %s." % exc)

    reversed_only = Deposits.search([
        ('move_id', '!=', False),
        ('state', '=', 'applied'),
    ])
    for dep in reversed_only:
        folio = dep.folio_id
        invoice = folio.move_id
        if not (invoice and invoice.state == 'posted'
                and invoice.move_type == 'out_invoice'):
            invoice = env['account.move'].search([
                ('hotel_folio_id', '=', folio.id),
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
            ], limit=1, order='id desc')
        if not invoice:
            continue
        try:
            folio._reconcile_reversal(dep.move_id, invoice)
        except Exception as exc:
            folio.message_post(
                body="Reconcile backfill skipped: %s." % exc)
