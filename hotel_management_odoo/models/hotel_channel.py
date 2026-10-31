# -*- coding: utf-8 -*-
"""Channel manager / booking-engine sync (Task 8).

Idempotent OTA ingest queue + room mapping + read-only availability.
Builds on folio (ledger per OTA booking), rates (stay validation +
pricing) and rack (overlap + availability). No POS/sales core changes:
sync never creates pos.order records (covered by test).
"""
import json
from datetime import datetime

from odoo import api, fields, models
from odoo.exceptions import ValidationError

try:
    from psycopg2 import IntegrityError
except ImportError:  # pragma: no cover - psycopg3 fallback
    from psycopg import IntegrityError

from .hotel_business_date import _to_date

CHANNELS = ('expedia', 'booking_com', 'airbnb', 'direct', 'other')

REQUIRED_KEYS = ('guest_name', 'checkin_date', 'checkout_date', 'room_code')


def normalize_ota_payload(payload):
    """Validate a raw OTA dict into a normalized booking dict.

    Raises ValidationError on missing/bad fields. Pure function so the
    HTTP controller and the queue model share one mapping.
    """
    if not isinstance(payload, dict):
        raise ValidationError("OTA payload must be a JSON object.")
    for key in REQUIRED_KEYS:
        if not payload.get(key):
            raise ValidationError("OTA payload missing required key: %s."
                                  % key)
    try:
        start = _to_date(payload.get('checkin_date'))
        end = _to_date(payload.get('checkout_date'))
    except (TypeError, ValueError):
        raise ValidationError("OTA dates must be YYYY-MM-DD.")
    if end <= start:
        raise ValidationError("Checkout must be after check-in.")
    pax = payload.get('pax') or 1
    try:
        pax = int(pax)
    except (TypeError, ValueError):
        raise ValidationError("OTA pax must be a positive number.")
    if pax < 1:
        raise ValidationError("OTA pax must be a positive number.")
    return {
        'guest_name': str(payload.get('guest_name')).strip(),
        'checkin_date': start,
        'checkout_date': end,
        'nights': (end - start).days,
        'room_code': str(payload.get('room_code')).strip(),
        'pax': pax,
        'rate_plan': (str(payload.get('rate_plan')).strip()
                      if payload.get('rate_plan') else False),
    }


class HotelChannelMessage(models.Model):
    """Sync queue: one row per OTA reservation, unique per channel key.

    Same (channel, external_id, company) twice = same row, one booking.
    """
    _name = 'hotel.channel.message'
    _description = "Hotel Channel Sync Message"
    _order = 'id desc'

    name = fields.Char(string="Reference", readonly=True, index=True,
                       default="New")
    channel = fields.Selection(
        [('expedia', 'Expedia'), ('booking_com', 'Booking.com'),
         ('airbnb', 'Airbnb'), ('direct', 'Direct / Booking Engine'),
         ('other', 'Other')],
        string="Channel", required=True, index=True, default='direct')
    external_id = fields.Char(string="OTA Reservation ID", required=True,
                              index=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)
    payload = fields.Text(string="Raw OTA Payload")
    state = fields.Selection([('queued', 'Queued'), ('done', 'Done'),
                              ('error', 'Error')],
                             default='queued', required=True, index=True)
    error = fields.Text(string="Last Error", readonly=True)
    booking_id = fields.Many2one('room.booking', string="Booking",
                                 readonly=True, ondelete="set null")

    _unique_channel_ref = models.Constraint(
        'unique(channel, external_id, company_id)',
        'OTA reservation already synced for this channel/company.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'hotel.channel.message') or vals.get('external_id')
        return super().create(vals_list)

    @api.model
    def enqueue_ota(self, channel, external_id, payload):
        """Queue + process one OTA payload, idempotently.

        Returns the (possibly pre-existing) queue record. Re-raises
        ValidationError from mapping/availability while recording it.
        The create runs in a savepoint: a concurrent duplicate insert
        hitting the unique key re-fetches the winner instead of
        double-booking.
        """
        if channel not in CHANNELS:
            raise ValidationError("Unknown channel %s." % channel)
        if not external_id:
            raise ValidationError("OTA payload needs an external ID.")
        norm = normalize_ota_payload(payload)
        company = self.env.company
        if isinstance(payload, dict) and payload.get('company_id'):
            if int(payload['company_id']) != company.id:
                raise ValidationError(
                    "OTA company belongs elsewhere; sync from that company.")
        domain = [
            ('channel', '=', channel),
            ('external_id', '=', str(external_id)),
            ('company_id', '=', company.id),
        ]
        existing = self.search(domain, limit=1)
        if existing:
            return self._reuse(existing, payload)
        try:
            with self.env.cr.savepoint():
                msg = self.create({
                    'channel': channel,
                    'external_id': str(external_id),
                    'company_id': company.id,
                    'payload': json.dumps(payload),
                })
        except IntegrityError:
            winner = self.search(domain, limit=1)
            if not winner:
                raise ValidationError(
                    "OTA reservation %s is already syncing; retry."
                    % external_id)
            return self._reuse(winner, payload)
        msg.action_process()
        return msg

    @api.model
    def _reuse(self, existing, payload):
        """Return a queued/error row (reprocessing it), or a done one."""
        if existing.state == 'done' and existing.booking_id:
            return existing
        existing.write({'payload': json.dumps(payload),
                        'state': 'queued', 'error': False})
        existing.action_process()
        return existing

    def action_process(self):
        """Map payload -> room.booking (reserved) + hotel.folio."""
        self.ensure_one()
        norm = normalize_ota_payload(json.loads(self.payload or '{}'))
        company = self.company_id
        room = self.env['product.template'].search([
            ('is_room', '=', True),
            ('name', '=', norm['room_code']),
            '|', ('company_id', '=', False),
            ('company_id', '=', company.id),
        ], limit=1)
        if not room:
            return self._fail("Unknown room code %s." % norm['room_code'])
        if room.num_person and norm['pax'] > room.num_person:
            return self._fail(
                "Room %s fits %d; requested %d pax."
                % (room.display_name, room.num_person, norm['pax']))
        ooo_ids = self.env['hotel.daily.inventory']._ooo_room_ids()
        if room.id in ooo_ids:
            return self._fail(
                "Room %s is out of order for these dates."
                % room.display_name)
        plan = False
        if norm['rate_plan']:
            plan = self.env['hotel.rate.plan'].search([
                ('name', '=', norm['rate_plan']),
                ('company_id', '=', company.id),
            ], limit=1)
            if not plan:
                return self._fail("Unknown rate plan %s."
                                  % norm['rate_plan'])
        else:
            plan = self.env['hotel.rate.plan'].search([
                ('company_id', '=', company.id),
            ], order='id', limit=1)
        if plan:
            try:
                self.env['hotel.rate.engine'].check_stay(
                    room.id, norm['checkin_date'], norm['checkout_date'],
                    plan.id, norm['pax'])
            except ValidationError as err:
                return self._fail(str(err))
        start, end = norm['checkin_date'], norm['checkout_date']
        checkin_dt = fields.Datetime.to_string(
            datetime(start.year, start.month, start.day, 14, 0, 0))
        checkout_dt = fields.Datetime.to_string(
            datetime(end.year, end.month, end.day, 11, 0, 0))
        clash = self.env['room.booking.line'].search_count([
            ('room_id', '=', room.id),
            ('booking_id.state', 'in', ('reserved', 'check_in')),
            ('checkin_date', '<', checkout_dt),
            ('checkout_date', '>', checkin_dt),
        ])
        if clash:
            return self._fail(
                "Room %s already booked for %s to %s."
                % (room.display_name, start.isoformat(), end.isoformat()))
        partner = self.env['res.partner'].search([
            ('name', '=', norm['guest_name']),
            '|', ('company_id', '=', False),
            ('company_id', '=', company.id),
        ], limit=1)
        if not partner:
            partner = self.env['res.partner'].create({
                'name': norm['guest_name'],
                'company_id': company.id,
            })
        booking = self.env['room.booking'].create({
            'partner_id': partner.id,
            'company_id': company.id,
            'checkin_date': checkin_dt,
            'checkout_date': checkout_dt,
        })
        self.env['room.booking.line'].create({
            'booking_id': booking.id,
            'company_id': company.id,
            'room_id': room.id,
            'checkin_date': checkin_dt,
            'checkout_date': checkout_dt,
            'uom_qty': norm['nights'],
        })
        booking.action_reserve()
        # action_reserve already find-or-creates the booking folio;
        # reuse it instead of double-creating.
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id)], limit=1)
        if not folio:
            self.env['hotel.folio'].create({
                'partner_id': partner.id,
                'booking_id': booking.id,
                'company_id': company.id,
                'policy_snapshot': booking.hotel_policy or False,
            })
        self.write({'state': 'done', 'error': False,
                    'booking_id': booking.id})
        return self

    def _fail(self, message):
        self.write({'state': 'error', 'error': message})
        raise ValidationError(message)

    @api.model
    def get_availability(self, date_from, date_to, plan_id=None):
        """Read-only availability + nightly price per room/date.

        Wraps hotel.daily.inventory rack cells; attaches rate-engine
        prices for available cells when a plan is given. Never writes.
        """
        try:
            start = _to_date(date_from)
            end = _to_date(date_to)
        except (TypeError, ValueError):
            raise ValidationError("Availability dates must be YYYY-MM-DD.")
        if end < start:
            raise ValidationError("Availability end must be on/after start.")
        plan = False
        if plan_id:
            plan = self.env['hotel.rate.plan'].browse(plan_id)
            if not plan.exists():
                raise ValidationError("Rate plan %s does not exist."
                                      % plan_id)
            if plan.company_id.id != self.env.company.id:
                raise ValidationError(
                    "Rate plan belongs to %s; query from that company."
                    % plan.company_id.display_name)
        rack = self.env['hotel.daily.inventory'].get_rack(
            fields.Date.to_string(start), fields.Date.to_string(end))
        engine = self.env['hotel.rate.engine']
        cells = []
        for cell in rack['cells']:
            price = False
            if plan and cell['status'] == 'available':
                room = self.env['product.template'].browse(cell['room_id'])
                price = engine.price_for(
                    room.id, cell['date'], plan.id,
                    room.num_person or 1)
            cells.append({
                'room_id': cell['room_id'],
                'room_name': cell['room_name'],
                'date': cell['date'],
                'status': cell['status'],
                'display': cell['display'],
                'booking_id': cell['booking_id'],
                'price': price,
            })
        return {
            'date_from': rack['date_from'],
            'date_to': rack['date_to'],
            'plan_id': plan.id if plan else False,
            'plan_name': plan.display_name if plan else False,
            'cells': cells,
        }
