# -*- coding: utf-8 -*-
"""Post-migration backfill for product-backed hotel services (20.0.1.7.0).

Runs AFTER ``hotel.service.product_id`` exists. Links each service with
``product_id=False`` to a service-type product, search-first by exact
name + type service to stay idempotent, else creates one mirroring the
service (name, unit_price → list_price, taxes, sale_ok, same company).

Idempotent: re-running only processes services still missing a product.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    services = env['hotel.service'].search([('product_id', '=', False)])
    if not services:
        _logger.info("SERVICE_PRODUCT_MIGRATION: no services missing "
                     "products; nothing to do.")
        return
    for svc in services:
        company_id = env.company.id
        product = env['product.product'].search(
            [('name', '=', svc.name), ('type', '=', 'service'),
             ('company_id', '=', company_id)], limit=1)
        if not product:
            product = env['product.product'].create({
                'name': svc.name,
                'type': 'service',
                'list_price': svc.unit_price or 0.0,
                'taxes_id': [(6, 0, svc.taxes_ids.ids)],
                'sale_ok': True,
                'purchase_ok': False,
                'company_id': env.company.id,
            })
            _logger.info("SERVICE_PRODUCT_MIGRATION create: service %s "
                         "(id=%s) -> product %s (id=%s)",
                         svc.name, svc.id, product.name, product.id)
        else:
            _logger.info("SERVICE_PRODUCT_MIGRATION reuse: service %s "
                         "(id=%s) -> product %s (id=%s)",
                         svc.name, svc.id, product.name, product.id)
        svc.product_id = product.id
    _logger.info("SERVICE_PRODUCT_MIGRATION: linked %s service(s).",
                 len(services))
