# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .hotel_business_date import _to_date

USE_TYPES = ('overnight', 'dayuse', 'hourly')
MEAL_PLANS = ('RO', 'BB', 'HB', 'FB')

# Config-parameter names + install defaults for the per-person
# per-night meal supplements (company currency). No hardcoded money in
# the posting logic: meal_plan_supplement() reads ir.config_parameter.
MEAL_PLAN_PARAMS = {
    'BB': 'hotel.meal.bb',
    'HB': 'hotel.meal.hb',
    'FB': 'hotel.meal.fb',
}
MEAL_PLAN_DEFAULTS = {
    'RO': 0.0,
    'BB': 1500.0,
    'HB': 3500.0,
    'FB': 5000.0,
}
# RO (room only) carries no supplement.

# Same-day stay caps, in hours. Hourly = short block; day-use = full
# working day. Overnight stays have no cap.
MAX_HOURLY_HOURS = 12.0
MAX_DAYUSE_HOURS = 14.0


class RoomBookingFamily(models.Model):
    """Family master + day-use/hourly + meal-plan extension.

    Additive only (no core changes): links child room bookings to a
    master via ``master_id``, tracks the per-room occupant separately
    from the payer (``partner_id``), and guards independent per-room
    checkout — the master stays open until every child is done.
    """
    _inherit = 'room.booking'

    master_id = fields.Many2one(
        'room.booking', string="Master Booking",
        help="Family master this room booking belongs to; empty = master.",
        ondelete="set null", index=True)
    child_ids = fields.One2many('room.booking', 'master_id',
                                string="Linked Rooms")
    is_master = fields.Boolean(string="Is Master",
                               compute='_compute_is_master', store=True)
    occupant_partner_id = fields.Many2one(
        'res.partner', string="Occupant",
        help="Person sleeping in this room; payer stays on Customer.",
        index=True)
    use_type = fields.Selection(
        [('overnight', 'Overnight'), ('dayuse', 'Day Use'),
         ('hourly', 'Hourly')],
        string="Use Type", default='overnight', required=True)
    meal_plan = fields.Selection(
        [('RO', 'Room Only'), ('BB', 'Bed & Breakfast'),
         ('HB', 'Half Board'), ('FB', 'Full Board')],
        string="Meal Plan", default='RO', required=True)

    @api.depends('child_ids')
    def _compute_is_master(self):
        for rec in self:
            rec.is_master = bool(rec.child_ids)

    @api.constrains('master_id')
    def _check_master_link(self):
        for rec in self:
            master = rec.master_id
            if not master:
                continue
            if master.id == rec.id:
                raise ValidationError("A booking cannot master itself.")
            if master.master_id:
                raise ValidationError(
                    "Nested masters not allowed; link to the top master.")
            if master.company_id.id != rec.company_id.id:
                raise ValidationError(
                    "Child belongs to %s; master belongs to %s."
                    % (rec.company_id.display_name,
                       master.company_id.display_name))

    @api.constrains('checkin_date', 'checkout_date')
    def _check_booking_dates(self):
        for rec in self:
            if rec.checkin_date and rec.checkout_date \
                    and rec.checkout_date <= rec.checkin_date:
                raise ValidationError(
                    "Checkout (%s) must be after check-in (%s)."
                    % (rec.checkout_date, rec.checkin_date))

    @api.constrains('use_type', 'room_line_ids', 'checkin_date',
                    'checkout_date')
    def _check_use_type(self):
        hour = self._hour_uom()
        for rec in self:
            span_hours = None
            if rec.checkin_date and rec.checkout_date:
                span_hours = (rec.checkout_date - rec.checkin_date
                              ).total_seconds() / 3600.0
            if rec.use_type == 'hourly':
                if span_hours is not None \
                        and span_hours > MAX_HOURLY_HOURS:
                    raise ValidationError(
                        "Hourly bookings cap at %.0f hours; got %.1f."
                        % (MAX_HOURLY_HOURS, span_hours))
                if not rec.room_line_ids:
                    raise ValidationError(
                        "Hourly bookings need a room line with Hour UoM.")
                for line in rec.room_line_ids:
                    if not hour or line.uom_id.id != hour.id:
                        raise ValidationError(
                            "Hourly bookings must use the Hour unit "
                            "(line %s uses %s)."
                            % (line.room_id.display_name,
                               line.uom_id.display_name))
            elif rec.use_type == 'dayuse':
                if rec.checkin_date and rec.checkout_date \
                        and rec.checkin_date.date() \
                        != rec.checkout_date.date():
                    raise ValidationError(
                        "Day-use checkout must fall on the check-in date.")
                if span_hours is not None \
                        and span_hours > MAX_DAYUSE_HOURS:
                    raise ValidationError(
                        "Day-use bookings cap at %.0f hours; got %.1f."
                        % (MAX_DAYUSE_HOURS, span_hours))

    @api.constrains('meal_plan')
    def _check_meal_plan(self):
        for rec in self:
            if rec.meal_plan not in MEAL_PLANS:
                raise ValidationError("Unknown meal plan %s." % rec.meal_plan)

    @api.model
    def _hour_uom(self):
        try:
            return self.env.ref('uom.product_uom_hour')
        except ValueError:
            return None

    def meal_plan_supplement(self):
        """Per-person per-night meal supplement for this booking.

        Read from ir.config_parameter (hotel.meal.bb/hb/fb, install
        defaults 1500/3500/5000); RO always 0.
        """
        self.ensure_one()
        if self.meal_plan not in MEAL_PLANS:
            raise ValidationError("Unknown meal plan %s." % self.meal_plan)
        if self.meal_plan == 'RO':
            return 0.0
        get_param = self.env['ir.config_parameter'].sudo().get_str
        raw = get_param(MEAL_PLAN_PARAMS[self.meal_plan],
                        MEAL_PLAN_DEFAULTS[self.meal_plan])
        try:
            return float(raw)
        except (TypeError, ValueError):
            raise ValidationError(
                "Bad meal supplement for %s: %r."
                % (self.meal_plan, raw))

    def _meal_rooms(self, room_template_id=None):
        """Rooms this meal supplement belongs to (dedup key source)."""
        self.ensure_one()
        if room_template_id:
            room = self.env['product.template'].browse(room_template_id)
            if not room.exists() or not room.is_room:
                raise ValidationError(
                    "Room %s does not exist." % room_template_id)
            return room
        rooms = self.room_line_ids.mapped('room_id')
        rooms = rooms.filtered(lambda r: r and r.is_room)
        if rooms:
            return rooms
        return self.env['product.template']

    def _meal_pax(self, rooms, pax=None):
        """Total persons per night: explicit pax wins, else sum of
        room capacities (num_person, min 1 each)."""
        if pax is not None:
            if pax < 1:
                raise ValidationError("Pax must be at least 1.")
            return int(pax)
        total = 0
        for room in rooms:
            total += room.num_person or 1
        return total or 1

    def _meal_start_day(self, hotel_date=None):
        self.ensure_one()
        if hotel_date:
            return _to_date(hotel_date)
        if self.checkin_date:
            return _to_date(self.checkin_date)
        if self.room_line_ids and self.room_line_ids[0].checkin_date:
            return _to_date(self.room_line_ids[0].checkin_date)
        return _to_date(None)

    def post_meal_supplement(self, folio_id, product_id, nights=1,
                             pax=None, hotel_date=None,
                             room_template_id=None, plan_id=None):
        """Post the meal-plan supplement per night; hook for HB/FB.

        qty = nights x pax (pax explicit, else sum of room
        capacities; single-room postings carry the full pax each
        night, multi-room postings split per room capacity). Posts one
        line per room per night with hotel_date + room_template_id so
        the stay-night dedup key holds, at the board-rule supplement
        for that night/room when a rule matches (else the
        config-param fallback). Returns the posted lines recordset,
        or False when the plan is RO with no board rule.
        Company-safe: folio company must match the booking company.
        Night-audit guard stays inside post_charge.
        """
        self.ensure_one()
        if nights < 1:
            raise ValidationError("Nights must be at least 1.")
        folio = self.env['hotel.folio'].browse(folio_id)
        if not folio.exists():
            raise ValidationError("Folio %s does not exist." % folio_id)
        if folio.company_id.id != self.company_id.id:
            raise ValidationError(
                "Folio belongs to %s; booking belongs to %s."
                % (folio.company_id.display_name,
                   self.company_id.display_name))
        product = self.env['product.product'].browse(product_id)
        if not product.exists():
            raise ValidationError("Product %s does not exist." % product_id)
        rooms = self._meal_rooms(room_template_id)
        if not rooms:
            raise ValidationError(
                "Meal supplement needs a room: add a room line or "
                "pass room_template_id.")
        board_rules = self.env['hotel.board.rule']
        start = self._meal_start_day(hotel_date)
        charge = self.env['hotel.charge.service']
        folio_company = folio.company_id or self.env.company
        for offset in range(nights):
            charge._check_open_day(
                start + timedelta(days=offset), folio_company)
        total_pax = self._meal_pax(rooms, pax)
        single = len(rooms) == 1
        lines = self.env['hotel.folio.line']
        for offset in range(nights):
            day = start + timedelta(days=offset)
            for room in rooms:
                per_pax = total_pax if single else (room.num_person or 1)
                rule = board_rules._match(
                    room.room_type_id.id if room.room_type_id else False,
                    self.meal_plan, day, plan_id)
                unit = float(rule.supplement) if rule \
                    else self.meal_plan_supplement()
                if not unit:
                    continue
                dup = self.env['hotel.folio.line'].search([
                    ('folio_id', '=', folio.id),
                    ('product_id', '=', product.id),
                    ('hotel_date', '=', day),
                    ('room_template_id', '=', room.id),
                ], limit=1)
                if dup:
                    lines |= dup
                    continue
                lines |= charge.post_charge(
                    folio.id, product.id, per_pax, unit, 'to_guest',
                    hotel_date=day, room_template_id=room.id)
        if not lines:
            return False
        return lines

    def _open_children(self):
        self.ensure_one()
        return self.child_ids.filtered(
            lambda c: c.state not in ('check_out', 'done', 'cancel'))

    def action_checkout(self):
        for rec in self:
            if rec.child_ids and rec._open_children():
                raise ValidationError(
                    "Master %s still has open rooms; "
                    "check out each room first." % rec.name)
        return super().action_checkout()

    def action_done(self):
        for rec in self:
            if rec.child_ids and rec._open_children():
                raise ValidationError(
                    "Master %s still has open rooms; "
                    "close each room first." % rec.name)
        return super().action_done()

    def action_cancel(self):
        for rec in self:
            if rec.child_ids and rec._open_children():
                raise ValidationError(
                    "Master %s still has open rooms; "
                    "cancel each room first." % rec.name)
        return super().action_cancel()
