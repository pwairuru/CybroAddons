# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
import hmac

from odoo import http
from odoo.exceptions import ValidationError
from werkzeug.exceptions import Forbidden

TOKEN_PARAM = 'hotel.channel.token'
TOKEN_HEADER = 'X-Channel-Token'


class ChannelWebhook(http.Controller):
    """Channel manager webhook + booking-engine availability.

    Thin HTTP layer: all mapping/validation lives in
    hotel.channel.message (shared with tests). Read-only availability;
    no POS code touched. The webhook ingest route is public and gated
    by a shared channel token (ir.config_parameter hotel.channel.token,
    header X-Channel-Token, constant-time compare, 403 when missing,
    mismatched or unconfigured); availability stays plain auth=user.
    """

    @staticmethod
    def _verify_token(provided, expected):
        """Shared-secret gate: 403 when unconfigured or mismatched."""
        if not expected:
            raise Forbidden('Channel token not configured.')
        if not hmac.compare_digest(
                (provided or '').encode('utf-8'),
                expected.encode('utf-8')):
            raise Forbidden('Bad channel token.')

    @http.route('/hotel/channel/webhook', type='json', auth='public',
                methods=['POST'], csrf=False)
    def channel_webhook(self, channel=None, external_id=None, payload=None):
        """Ingest one OTA reservation idempotently (public + token)."""
        request = http.request
        self._verify_token(
            request.httprequest.headers.get(TOKEN_HEADER, ''),
            request.env['ir.config_parameter'].sudo().get_str(
                TOKEN_PARAM, ''))
        if not channel or not external_id or payload is None:
            raise ValidationError(
                "channel, external_id and payload are required.")
        msg = request.env['hotel.channel.message'].sudo().enqueue_ota(
            channel, external_id, payload)
        return {
            'message_id': msg.id,
            'name': msg.name,
            'state': msg.state,
            'booking_id': msg.booking_id.id or False,
        }

    @http.route('/hotel/channel/availability', type='json', auth='user',
                methods=['POST'], csrf=False)
    def channel_availability(self, date_from=None, date_to=None,
                             plan_id=None):
        """Read-only availability + nightly prices for a date window."""
        if not date_from or not date_to:
            raise ValidationError("date_from and date_to are required.")
        return http.request.env['hotel.channel.message'].get_availability(
            date_from, date_to, plan_id=plan_id)
