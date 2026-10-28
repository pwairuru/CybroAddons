# -*- coding: utf-8 -*-
from datetime import datetime

from odoo import api, fields, models
from odoo.exceptions import ValidationError

try:
    from psycopg2 import IntegrityError
except ImportError:  # pragma: no cover - psycopg3 fallback
    from psycopg import IntegrityError


def _to_date(hotel_date):
    """Normalize str/date/datetime input to a date (default today)."""
    if not hotel_date:
        return fields.Date.today()
    if isinstance(hotel_date, str):
        return fields.Date.from_string(hotel_date)
    if isinstance(hotel_date, datetime):
        return hotel_date.date()
    return hotel_date


class HotelBusinessDate(models.Model):
    """One record per company/day tracking whether posting is allowed.

    Closed days reject new charges; corrections post on the open day.
    """
    _name = 'hotel.business.date'
    _description = "Hotel Business Date"
    _order = 'date desc'

    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)
    date = fields.Date(string="Date", required=True, index=True,
                       default=fields.Date.today)
    is_closed = fields.Boolean(string="Closed", default=False)

    _one_day_per_company = models.Constraint(
        'unique(company_id, date)',
        'Business date already exists for this company/day.')

    @api.model
    def is_day_closed(self, hotel_date=None, company=None):
        """True when the given day is closed for the company."""
        day = _to_date(hotel_date)
        company = company or self.env.company
        rec = self.search([('company_id', '=', company.id),
                           ('date', '=', day)], limit=1)
        return bool(rec and rec.is_closed)

    @api.model
    def _ensure_day(self, hotel_date=None):
        day = _to_date(hotel_date)
        company_id = self.env.company.id
        rec = self.search([('company_id', '=', company_id),
                           ('date', '=', day)], limit=1)
        if not rec:
            try:
                rec = self.create({'date': day, 'company_id': company_id})
            except IntegrityError:
                rec = self.search([('company_id', '=', company_id),
                                   ('date', '=', day)], limit=1)
        return rec

    def action_close(self):
        self.write({'is_closed': True})
        return True


class HotelNightAudit(models.Model):
    """Night audit: posts room nights, clears no-shows, locks the day."""
    _name = 'hotel.night.audit'
    _description = "Hotel Night Audit"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc'

    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)
    date = fields.Date(string="Audit Date", required=True, index=True,
                       default=fields.Date.today, tracking=True)
    state = fields.Selection([('draft', 'Draft'), ('done', 'Done')],
                             default='draft', required=True, tracking=True)
    room_nights_posted = fields.Integer(string="Room Nights", default=0,
                                        tracking=True)
    no_show_count = fields.Integer(string="No-Shows", default=0,
                                   tracking=True)

    _one_audit_per_day = models.Constraint(
        'unique(company_id, date)',
        'Night already closed')

    def action_close(self):
        """Lock the day without posting (manual close path)."""
        self.ensure_one()
        self.env['hotel.business.date']._ensure_day(self.date).write(
            {'is_closed': True})
        self.write({'state': 'done'})
        return True

    @api.model
    def run(self, hotel_date=None):
        """Post room nights, cancel no-shows, close day, send flash.

        Idempotent: a second run(date) with nothing pending returns the
        recorded flash. A run on a closed audit/business day with
        unposted nights raises instead of skipping silently.
        Returns an ir.actions.client flash dict.
        """
        day = _to_date(hotel_date)
        company = self.env.company
        audit = self.search([('company_id', '=', company.id),
                             ('date', '=', day)], limit=1)
        if not audit:
            audit = self.create({'date': day, 'company_id': company.id})
        if audit.state == 'done':
            if audit._pending_count(day):
                raise ValidationError(
                    "Night audit %s is closed with unposted room "
                    "nights: post adjustments on the open day." % day)
            return audit._flash(audit.room_nights_posted,
                                audit.no_show_count)
        if self.env['hotel.business.date'].is_day_closed(day):
            raise ValidationError(
                "Business day %s is closed: post adjustments on the "
                "open day." % day)
        posted = audit._post_room_nights(day)
        noshows = audit._handle_no_shows(day)
        self.env['hotel.business.date']._ensure_day(day).write(
            {'is_closed': True})
        audit.write({'state': 'done', 'room_nights_posted': posted,
                     'no_show_count': noshows})
        return audit._flash(posted, noshows)

    def _flash(self, posted, noshows):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': ("Night audit %s: %d room night(s), "
                            "%d no-show(s)." % (self.date, posted, noshows)),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _pending_count(self, day):
        """Room-night postings still missing for day (no writes)."""
        count = 0
        bookings = self.env['room.booking'].search(
            [('company_id', '=', self.company_id.id),
             ('state', '=', 'check_in')])
        for booking in bookings:
            if not self._covers(booking, day):
                continue
            folio = self.env['hotel.folio'].search(
                [('booking_id', '=', booking.id),
                 ('state', '=', 'open')], limit=1)
            for line in booking.room_line_ids:
                product = line.room_id.product_variant_id
                if not product:
                    continue
                if folio and self.env['hotel.folio.line'].search_count([
                        ('folio_id', '=', folio.id),
                        ('product_id', '=', product.id),
                        ('hotel_date', '=', day),
                        ('room_template_id', '=', line.room_id.id)]):
                    continue
                count += 1
        return count

    def _post_room_nights(self, day):
        """Post one room-night charge per in-house booking line.

        Nights are priced through the rate engine
        (``price_detailed`` net, with the line's pax) under the plan
        matching each booking's board; without a plan the booking
        line rent is used. Pre-validates the day is open before the
        first post_charge (no partial audit), and dedups on folio +
        product + hotel date + room so two lines sharing one
        product never collapse.
        """
        charge = self.env['hotel.charge.service']
        company = self.company_id or self.env.company
        charge._check_open_day(day, company)
        plan_model = self.env['hotel.rate.plan']
        engine = self.env['hotel.rate.engine']
        bookings = self.env['room.booking'].search(
            [('company_id', '=', company.id),
             ('state', '=', 'check_in')])
        posted = 0
        for booking in bookings:
            if not self._covers(booking, day):
                continue
            plan = plan_model._plan_for_booking(booking)
            folio = self.env['hotel.folio'].search(
                [('booking_id', '=', booking.id),
                 ('state', '=', 'open')], limit=1)
            if not folio:
                folio = self.env['hotel.folio'].create({
                    'partner_id': booking.partner_id.id,
                    'booking_id': booking.id,
                    'policy_snapshot': booking.hotel_policy or False,
                })
            for line in booking.room_line_ids:
                product = line.room_id.product_variant_id
                if not product:
                    continue
                dup = self.env['hotel.folio.line'].search_count([
                    ('folio_id', '=', folio.id),
                    ('product_id', '=', product.id),
                    ('hotel_date', '=', day),
                    ('room_template_id', '=', line.room_id.id),
                ])
                if dup:
                    continue
                if plan:
                    # First-night anchor: every night posts the
                    # check-in date price so folio matches the quote.
                    # Restrictions/min-stay above still use the
                    # actual day.
                    anchor = line.checkin_date.date() \
                        if line.checkin_date else day
                    price = engine.price_detailed(
                        line.room_id.id, anchor, plan.id,
                        adults=line.adults, children=line.children,
                        board=booking.meal_plan or 'RO',
                        booking=booking)['net']
                else:
                    price = line.price_unit or 0.0
                charge.post_charge(folio.id, product.id, 1,
                                   price, 'to_guest',
                                   hotel_date=day,
                                   room_template_id=line.room_id.id,
                                   booking_line_id=line.id)
                posted += 1
        return posted

    def _covers(self, booking, day):
        """True when the audit day falls inside the stay."""
        start = booking.checkin_date.date() if booking.checkin_date else day
        end = (booking.checkout_date.date() if booking.checkout_date
               else day)
        if end <= start:
            return start <= day
        return start <= day < end

    def _handle_no_shows(self, day):
        """Cancel reserved bookings whose check-in passed unfulfilled."""
        cutoff = fields.Datetime.to_datetime('%s 00:00:00' % day)
        stale = self.env['room.booking'].search(
            [('company_id', '=', self.company_id.id),
             ('state', '=', 'reserved'),
             ('checkin_date', '<', cutoff)])
        count = 0
        for booking in stale:
            cancel = getattr(booking, 'action_cancel', None)
            if not callable(cancel):
                continue
            try:
                cancel()
            except Exception:
                continue
            count += 1
        return count
