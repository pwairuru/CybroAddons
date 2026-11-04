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
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .hotel_business_date import _nights

_logger = logging.getLogger(__name__)


class RoomBookingLine(models.Model):
    """Model that handles the room booking form"""
    _name = "room.booking.line"
    _description = "Hotel Folio Line"
    _rec_name = 'room_id'
    _inherit = ['hotel.booking.line.mixin']

    @api.model
    def _set_default_uom_id(self):
        return self.env.ref('uom.product_uom_day', raise_if_not_found=False)
    checkin_date = fields.Datetime(string="Check In",
                                   help="You can choose the date,"
                                        " Otherwise sets to current Date",
                                   required=True)
    checkout_date = fields.Datetime(string="Check Out",
                                    help="You can choose the date,"
                                         " Otherwise sets to current Date",
                                    required=True)
    room_id = fields.Many2one('product.template', string="Room",
                               domain=[('is_room', '=', True)],
                               help="Indicates the Room. Availability for "
                                    "the stay dates is enforced server-side "
                                    "(overlap check), not by room status.",
                               required=True)
    uom_qty = fields.Float(string="Duration",
                           compute='_compute_uom_qty', store=True,
                           readonly=True,
                           help="Nights between check-in and check-out "
                                "(minimum 1).")
    uom_id = fields.Many2one('uom.uom',
                             default=_set_default_uom_id,
                             string="Unit of Measure",
                             help="This will set the unit of measure used",
                             readonly=True)
    price_unit = fields.Float(string='Rent', digits='Product Price',
                              compute='_compute_price_unit', store=True,
                              readonly=False, tracking=True,
                              help="The rent price of the selected room.")
    tax_ids = fields.Many2many('account.tax',
                               'hotel_room_order_line_taxes_rel',
                               'room_id', 'tax_id',
                               compute='_compute_tax_ids', store=True,
                               readonly=False, precompute=True, tracking=True,
                               string='Taxes',
                               help="Default taxes used when selling the room."
                               , domain=[('type_tax_use', '=', 'sale')])
    company_id = fields.Many2one('res.company', string="Company",
                                 help="Choose the Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)
    adults = fields.Integer(string="Adults", default=1,
                            help="Adult guests occupying this room line.")
    children = fields.Integer(string="Children", default=0,
                              help="Child guests occupying this room line.")
    toddlers = fields.Integer(string="Toddlers", default=0,
                               help="Toddler guests occupying this room line.")
    meal_plan = fields.Selection(
        [('RO', 'Room Only'), ('BB', 'Bed & Breakfast'),
         ('HB', 'Half Board'), ('FB', 'Full Board')],
        string="Meal Plan", compute='_compute_meal_plan', store=True,
        readonly=False, required=True, precompute=True, tracking=True,
        help="Board priced for this room line. New lines inherit the "
             "booking's meal plan; changing the booking later does not "
             "overwrite lines that already have a value.")
    over_capacity = fields.Boolean(
        string="Over Capacity", compute='_compute_over_capacity',
        help="Adults + children exceed the room capacity (toddlers "
             "never count). Saving is blocked or allowed per the "
             "company over-capacity policy.")
    rate_line_id = fields.Many2one('hotel.rate.line', string="Rate Line", copy=False, readonly=True,
                                     help="Rate line this night was priced from. Frozen at reserve so later price edits never change this booking.")
    rate_net = fields.Float(string="Rate Net", copy=False, readonly=True,
                            help="Quoted total for one night: rent plus extra-guest charges. The night audit posts exactly this to the folio.")
    rate_breakdown = fields.Text(string="Rate Breakdown", copy=False, readonly=True,
                                 help="How the net was built: base rent plus each extra-guest line. Read-only pricing trail for disputes.")

    @api.constrains('adults', 'children', 'room_id', 'meal_plan')
    def _check_capacity_line(self):
        for line in self:
            if not line._is_over_capacity():
                continue
            policy = (line.company_id.hotel_capacity_policy
                      if line.company_id
                      else line.booking_id.company_id.hotel_capacity_policy
                      if line.booking_id and line.booking_id.company_id
                      else self.env.company.hotel_capacity_policy)
            if policy == 'warn':
                continue
            total = (line.adults or 0) + (line.children or 0)
            if line.room_id.num_person and total > line.room_id.num_person:
                raise ValidationError("Room %s fits %d; requested %d." % (line.room_id.display_name, line.room_id.num_person, total))
            rt = line.room_id.room_type_id
            if rt and rt.max_occupants and total > rt.max_occupants:
                raise ValidationError("Room type %s fits %d; requested %d." % (rt.display_name, rt.max_occupants, total))

    def _is_over_capacity(self):
        self.ensure_one()
        total = (self.adults or 0) + (self.children or 0)
        if self.room_id.num_person and total > self.room_id.num_person:
            return True
        rt = self.room_id.room_type_id
        if rt and rt.max_occupants and total > rt.max_occupants:
            return True
        return False

    @api.depends('adults', 'children', 'room_id')
    def _compute_over_capacity(self):
        for line in self:
            if not line.room_id:
                line.over_capacity = False
                continue
            line.over_capacity = line._is_over_capacity()

    @api.depends('booking_id.meal_plan', 'meal_plan')
    def _compute_meal_plan(self):
        for line in self:
            if not line.meal_plan and line.booking_id:
                line.meal_plan = line.booking_id.meal_plan or False

    @api.onchange('adults', 'children', 'room_id')
    def _onchange_capacity_warn(self):
        if not self.room_id or not self._is_over_capacity():
            return
        policy = (self.company_id.hotel_capacity_policy
                  if self.company_id
                  else self.booking_id.company_id.hotel_capacity_policy
                  if self.booking_id and self.booking_id.company_id
                  else self.env.company.hotel_capacity_policy)
        if policy != 'warn':
            return
        total = (self.adults or 0) + (self.children or 0)
        return {
            'warning': {
                'title': _("Over capacity"),
                'message': _(
                    "Room %s fits %d; requested %d (toddlers exempt). "
                    "Saving is allowed under the Warn-only policy.")
                % (self.room_id.display_name,
                   self.room_id.num_person or 0, total),
            }
        }

    @api.model
    def _detailed_price(self, line, reraise=False):
        """Engine quote for a room line ({} when unpriceable).

        Wraps plan lookup + price_detailed. With reraise=False every
        miss (no plan, engine error) returns {}; with reraise=True
        engine errors propagate so callers keep their raise/log/skip
        policy. Missing check-in falls back to today (estimate path).
        """
        booking = line.booking_id
        if not booking or not line.room_id:
            return {}
        plan = self.env['hotel.rate.plan']._plan_for_booking(booking)
        if not plan:
            return {}
        if line.checkin_date:
            day = fields.Date.to_string(
                fields.Datetime.context_timestamp(
                    line, line.checkin_date).date())
        else:
            day = fields.Date.today()
        try:
            return self.env['hotel.rate.engine'].price_detailed(
                line.room_id.id, day, plan.id,
                adults=line.adults or 0, children=line.children or 0,
                board=line.meal_plan or booking.meal_plan or 'RO',
                booking=booking) or {}
        except ValidationError:
            if reraise:
                raise
            return {}
        except Exception:
            if reraise:
                raise
            return {}

    def _compute_rate_snapshot(self):
        for line in self:
            if line.locked:
                continue
            if not line.room_id or not line.checkin_date:
                continue
            booking = line.booking_id
            if not booking:
                continue
            try:
                d = self._detailed_price(line, reraise=True)
            except ValidationError:
                raise
            except Exception as exc:
                _logger.warning(
                    "Rate snapshot skipped for room %s on %s: %r",
                    line.room_id.display_name, line.checkin_date, exc)
                continue
            if not d:
                continue
            line.rate_line_id = d.get('line_id') or d.get('rule_id') or False
            line.rate_net = d.get('net', 0.0)
            line.rate_breakdown = str(d.get('lines', []))
            # Advisory quote only: fill an unpriced line, never wipe a
            # manual edit. Checkout/date changes requote through
            # _compute_price_unit instead.
            if not line.price_unit:
                # Quote carries the full nightly net (base + occupancy extras); posting still itemizes base via 'resolved' + band lines.
                line.price_unit = d.get('net', line.price_unit)

    @api.constrains('adults', 'children', 'toddlers')
    def _check_pax(self):
        for line in self:
            if line.adults < 0 or line.children < 0 \
                    or line.toddlers < 0:
                raise ValidationError(
                    _("Guest counts cannot be negative."))


    @api.depends('checkin_date', 'checkout_date')
    def _compute_uom_qty(self):
        """Nights between line dates (minimum 1). Server-side so direct
        RPC creates get a quantity even without the UI onchange.
        Locked (invoiced) lines keep their frozen quantity."""
        for line in self:
            if line.locked:
                continue
            line.uom_qty = _nights(line.checkin_date, line.checkout_date)

    @api.constrains('uom_qty', 'checkin_date', 'checkout_date')
    def _check_uom_qty(self):
        for line in self:
            if line.checkin_date and line.checkout_date \
                    and line.uom_qty <= 0:
                raise ValidationError(
                    _("Line duration must be positive: check-out must be "
                      "after check-in."))

    @api.constrains('room_id', 'checkin_date', 'checkout_date',
                     'booking_id')
    def _check_no_overlap(self):
        """No two active bookings hold the same room over the same night.

        Within-booking duplicates are rejected by room.booking; this
        covers cross-booking double-sells. Cancelled/done/check_out
        bookings release the room. State changes into active states go
        through action_reserve/action_checkin, which run the same
        overlap search explicitly.
        """
        for line in self:
            if not line.room_id or not line.checkin_date \
                    or not line.checkout_date:
                continue
            if line.booking_id.state not in ('draft', 'reserved',
                                             'check_in'):
                continue
            # Single enforcement point: overlap message text matches
            # what callers/tests expect.
            self.env['room.booking']._check_room_available(
                line.room_id, line.checkin_date, line.checkout_date,
                ignore_booking=line.booking_id)

    @api.depends('room_id', 'booking_id.pricelist_id',
                   'booking_id.partner_id', 'booking_id.company_id',
                   'booking_id.meal_plan', 'meal_plan', 'checkin_date', 'adults',
                   'children', 'uom_qty')
    def _compute_price_unit(self):
        """Quick-math default for the rent (first-night anchor price).

        Quote = engine resolved nightly amount for the check-in
        date under the booking's board/pax/plan, applied flat to
        every night (first-night-anchor policy). Manual edits stick
        until a pricing input changes (room, dates/qty, pax, board,
        pricelist); changing checkout dates therefore requotes and
        overwrites a manual price by design — re-edit after dates
        settle. Only invoiced (locked) lines freeze.
        Falls back to the booking pricelist (then room list price)
        when no plan matches or the engine cannot price.
        """
        for line in self:
            if line.locked:
                continue
            if not line.room_id:
                line.price_unit = 0
                continue
            anchor = self._anchor_price(line)
            if anchor is not None:
                line.price_unit = anchor
                continue
            pricelist = line.booking_id.pricelist_id
            if pricelist:
                line.price_unit = pricelist._get_product_price(
                    line.room_id, line.uom_qty or 1.0,
                    partner=line.booking_id.partner_id or False,
                    date=fields.Date.to_string(
                        fields.Date.context_today(line)))
            else:
                line.price_unit = line.room_id.list_price

    @api.model
    def _anchor_price(self, line):
        """Engine resolved price for the line's check-in date.

        Returns None when the engine cannot price (caller falls
        back to pricelist/list price)."""
        if not line.booking_id or not line.checkin_date:
            return None
        detailed = self._detailed_price(line)
        if not detailed:
            return None
        # Quote carries the full nightly net (base + occupancy extras); posting still itemizes base via 'resolved' + band lines.
        return float(detailed.get('net', 0.0))

    @api.onchange("checkin_date", "checkout_date")
    def _onchange_checkin_date(self):
        """When you change checkin_date or checkout_date it will check
        and update the qty of hotel service line
        -----------------------------------------------------------------
        @param self: object pointer"""
        if not self.checkin_date or not self.checkout_date:
            return
        if self.checkout_date <= self.checkin_date:
            # Warn, don't raise: mid-edit states (checkout first, then
            # check-in, or a fresh row's defaults) are transiently
            # inverted. The _check_uom_qty constraint still blocks
            # saving an invalid range.
            return {
                'warning': {
                    'title': _("Invalid dates"),
                    'message': _("Checkout must be after check-in date."),
                }
            }
        self.uom_qty = _nights(self.checkin_date, self.checkout_date)


    @api.depends('uom_qty', 'price_unit', 'tax_ids')
    def _compute_price_subtotal(self):
        """Compute the amounts of the room booking line."""
        self._compute_booking_line_amounts()

    @api.depends('room_id', 'company_id', 'booking_id.company_id')
    def _compute_tax_ids(self):
        """Compute default taxes safely filtering by company.
        Locked (invoiced) lines keep their frozen taxes."""
        for line in self:
            if line.locked:
                continue
            if not line.room_id:
                line.tax_ids = False
                continue
            company = line.company_id or line.booking_id.company_id
            taxes = line.room_id.sudo().taxes_id.filtered(
                lambda t: not t.company_id or t.company_id == company
            )
            line.tax_ids = taxes

    locked = fields.Boolean(
        string="Locked", compute='_compute_locked', store=True,
        help="True once the booking is invoiced; price/tax/qty edits "
             "are then rejected server-side.")
    booking_line_visible = fields.Boolean(default=False,
                                          string="Booking Line Visible",
                                          compute='_compute_locked',
                                          store=True, readonly=True,
                                          help="Kept for view compatibility; "
                                               "mirrors Locked.")

    @api.depends('booking_id.invoice_status')
    def _compute_locked(self):
        for line in self:
            locked = line.booking_id.invoice_status in ('invoiced', 'paid')
            line.locked = locked
            line.booking_line_visible = locked

    @api.constrains('price_unit', 'tax_ids', 'uom_qty')
    def _check_locked(self):
        for line in self:
            if line.locked and not self.env.context.get(
                    'hotel_allow_locked_write'):
                raise ValidationError(
                    _("Invoiced lines cannot be edited (room %s).")
                    % line.room_id.display_name)

    extra_per_night = fields.Float(
        string='Extras / Night', compute='_compute_extra_estimate',
        help="Estimated extra-guest charge per night under the booking's "
             "board plan (quote only; posting is authoritative).")
    extra_stay_total = fields.Float(
        string='Extras Total', compute='_compute_extra_estimate',
        help="Estimated extra-guest charge for the whole line.")

    @api.depends('adults', 'children', 'room_id',
                  'uom_qty', 'checkin_date', 'checkout_date',
                  'meal_plan', 'booking_id.meal_plan', 'booking_id.pricelist_id',
                  'booking_id.company_id')
    def _compute_extra_estimate(self):
        for line in self:
            line.extra_per_night = 0.0
            line.extra_stay_total = 0.0
            if not line.room_id or not line.booking_id:
                continue
            detailed = self._detailed_price(line)
            if not detailed:
                continue
            line.extra_per_night = float(detailed.get('occupancy', 0.0))
            line.extra_stay_total = float(
                detailed.get('occupancy', 0.0)) * (line.uom_qty or 0.0)
