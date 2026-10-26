# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HotelPostStay(models.TransientModel):
    """Front-desk wizard posting stay nights through the rate engine.

    Prefills room/dates/pax from the picked room line (first line
    when none picked) and resolves the open folio (creating it for
    reserved/checked-in bookings). Posting itself just calls
    ``hotel.rate.engine.post_stay_nights`` so folio-open and
    company guards stay in one place.
    """
    _name = 'hotel.post.stay'
    _description = 'Post Stay Nights to Folio'

    booking_id = fields.Many2one('room.booking', string='Booking')
    booking_line_id = fields.Many2one(
        'room.booking.line', string='Room Line',
        domain="[('booking_id', '=', booking_id)]")
    folio_id = fields.Many2one('hotel.folio', string='Folio',
                               required=True)
    room_template_id = fields.Many2one(
        'product.template', string='Room', required=True,
        domain=[('is_room', '=', True)])
    date_from = fields.Date(string='From', required=True)
    date_to = fields.Date(string='To', required=True)
    plan_id = fields.Many2one('hotel.rate.plan', string='Rate Plan',
                              required=True)
    adults = fields.Integer(string='Adults', default=1)
    children = fields.Integer(string='Children', default=0)
    toddlers = fields.Integer(string='Toddlers', default=0)

    @api.constrains('adults', 'children', 'toddlers')
    def _check_pax(self):
        for wiz in self:
            if wiz.adults < 0 or wiz.children < 0 \
                    or wiz.toddlers < 0:
                raise ValidationError(
                    _("Guest counts cannot be negative."))

    @api.model
    def _booking_from_context(self):
        booking_id = self.env.context.get('default_booking_id')
        if not booking_id \
                and self.env.context.get('active_model') == 'room.booking':
            booking_id = self.env.context.get('active_id')
        booking = self.env['room.booking'].browse(booking_id) \
            if booking_id else self.env['room.booking'].browse()
        return booking if booking.exists() else False

    @api.model
    def _default_folio(self, booking):
        folio = self.env['hotel.folio'].search(
            [('booking_id', '=', booking.id),
             ('state', '=', 'open')], limit=1)
        if folio:
            return folio
        if booking.state in ('reserved', 'check_in'):
            return booking._ensure_folio()
        raise ValidationError(
            "Booking %s has no open folio; reserve or check in first."
            % booking.display_name)

    @api.model
    def _line_defaults(self, line):
        """Room/dates/pax prefill from one booking line (no writes)."""
        vals = {}
        if not line:
            return vals
        vals['booking_line_id'] = line.id
        vals['room_template_id'] = line.room_id.id
        if line.checkin_date:
            vals['date_from'] = line.checkin_date.date()
        if line.checkout_date:
            vals['date_to'] = line.checkout_date.date()
        vals['adults'] = line.adults
        vals['children'] = line.children
        vals['toddlers'] = line.toddlers
        return vals

    @api.model
    def _booking_defaults(self, booking, line=None):
        """Prefill values from booking + room line (no writes).

        Uses the passed line when given, else the booking's first
        room line (existing behavior preserved).
        """
        vals = {'booking_id': booking.id,
                'folio_id': self._default_folio(booking).id}
        line = line or booking.room_line_ids[:1]
        vals.update(self._line_defaults(line))
        plan = self.env['hotel.rate.plan']._plan_for_booking(booking)
        if plan:
            vals['plan_id'] = plan.id
        return vals

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        booking = self._booking_from_context()
        line = self.env['room.booking.line'].browse(
            self.env.context.get('default_booking_line_id')) \
            if self.env.context.get('default_booking_line_id') \
            else self.env['room.booking.line'].browse()
        if line.exists():
            if not booking or line.booking_id != booking:
                booking = line.booking_id
        if not booking:
            return res
        if not line.exists():
            line = False
        for key, value in self._booking_defaults(
                booking, line=line).items():
            if key in fields_list:
                res[key] = value
        return res

    @api.onchange('booking_id')
    def _onchange_booking_id(self):
        if not self.booking_id:
            return
        line = self.booking_line_id \
            if self.booking_line_id \
            and self.booking_line_id.booking_id == self.booking_id \
            else self.booking_id.room_line_ids[:1]
        for key, value in self._booking_defaults(
                self.booking_id, line=line).items():
            if key != 'booking_id':
                self[key] = value

    @api.onchange('booking_line_id')
    def _onchange_booking_line_id(self):
        if not self.booking_line_id:
            return
        line = self.booking_line_id
        if line.booking_id and line.booking_id != self.booking_id:
            self.booking_id = line.booking_id
        booking = self.booking_id or line.booking_id
        if booking:
            for key, value in self._booking_defaults(
                    booking, line=line).items():
                if key not in ('booking_id', 'booking_line_id'):
                    self[key] = value
        else:
            for key, value in self._line_defaults(line).items():
                if key != 'booking_line_id':
                    self[key] = value

    def action_post(self):
        """Post the stay nights; returns the folio lines created/found."""
        self.ensure_one()
        return self.env['hotel.rate.engine'].post_stay_nights(
            self.folio_id.id, self.room_template_id.id,
            self.date_from, self.date_to, self.plan_id.id,
            adults=self.adults, children=self.children,
            toddlers=self.toddlers)
