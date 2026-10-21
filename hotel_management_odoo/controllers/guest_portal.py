# -*- coding: utf-8 -*-
from odoo import http


class GuestPortal(http.Controller):
    """Guest self-service portal: folio balances + ID documents.

    Thin HTTP layer: all logic lives on res.partner / hotel.document
    (shared with tests, no HTTP stack needed). Read-only; portal user
    only ever sees their own commercial partner records.
    """

    @staticmethod
    def _portal_partner():
        partner = http.request.env.user.partner_id
        return partner

    @staticmethod
    def _folio_balances(partner):
        # sudo: portal users hold no folio ACL of their own; scope stays
        # tight because get_portal_folios only returns this partner's
        # folios in the allowed companies.
        return partner.sudo().get_portal_folios()

    @staticmethod
    def _guest_documents(partner):
        allowed = set(partner.env.companies.ids)
        docs = partner.sudo().document_ids.filtered(
            lambda d: not d.company_id or d.company_id.id in allowed)
        return [{
            'id': doc.id,
            'type': doc.type_id.display_name,
            'number': doc.number,
            'expiry_date': doc.expiry_date,
            'state': doc.state,
        } for doc in docs]

    @http.route('/my/hotel/folios', type='json', auth='user',
                methods=['POST'], csrf=False)
    def portal_folios(self):
        """Folio balances for the logged-in portal guest."""
        partner = self._portal_partner()
        return {'folios': self._folio_balances(partner)}

    @http.route('/my/hotel/documents', type='json', auth='user',
                methods=['POST'], csrf=False)
    def portal_documents(self):
        """ID documents for the logged-in portal guest."""
        partner = self._portal_partner()
        return {'documents': self._guest_documents(partner)}
