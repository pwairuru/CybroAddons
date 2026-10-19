# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

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

    def post_meal_supplement(self, folio_id, product_id, nights=1):
        """Post the meal-plan supplement to an open folio; hook for HB/FB.

        Returns the created folio line, or False when the plan is RO
        (zero supplement). Company-safe: folio company must match the
        booking company. Night-audit guard stays inside post_charge.
        """
        self.ensure_one()
        supplement = self.meal_plan_supplement()
        if not supplement:
            return False
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
        line = self.env['hotel.charge.service'].post_charge(
            folio.id, product_id, nights, supplement, 'to_guest')
        return line

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
