# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .hotel_business_date import _to_date


class HotelRatePlan(models.Model):
    """Rate plan header (e.g. Rack, Peak, Corporate).

    Company-safe: one plan per company. Optional pricelist reuses
    product.pricelist pricing as the base; otherwise room list_price.
    """
    _name = 'hotel.rate.plan'
    _description = "Hotel Rate Plan"
    _order = 'name'

    name = fields.Char(string="Name", required=True)
    code = fields.Char(string="Code")
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)
    pricelist_id = fields.Many2one('product.pricelist', string="Pricelist",
                                   help="Base prices come from this "
                                   "pricelist when set; else room list price.",
                                   ondelete="set null")
    active = fields.Boolean(default=True)
    rule_ids = fields.One2many('hotel.rate.rule', 'plan_id',
                               string="Seasonal Rules")
    restriction_ids = fields.One2many('hotel.rate.restriction', 'plan_id',
                                      string="Restrictions")


class HotelRateRule(models.Model):
    """Seasonal adjustment window for a plan.

    The most specific matching rule wins: room-specific beats generic,
    then the latest date_from wins.
    """
    _name = 'hotel.rate.rule'
    _description = "Hotel Rate Rule"
    _order = 'date_from desc'

    plan_id = fields.Many2one('hotel.rate.plan', string="Plan",
                              required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 related='plan_id.company_id',
                                 store=True, readonly=True, index=True)
    room_template_id = fields.Many2one(
        'product.template', string="Room",
        domain=[('is_room', '=', True)],
        help="Room this rule applies to; empty = all rooms.",
        ondelete="cascade", index=True)
    date_from = fields.Date(string="From", required=True)
    date_to = fields.Date(string="To", required=True)
    adjustment_pct = fields.Float(string="Adjustment %", default=0.0,
                                  help="e.g. 50 = +50%, -20 = -20%.")
    min_stay = fields.Integer(string="Min Stay (nights)", default=1)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rule in self:
            if rule.date_from and rule.date_to \
                    and rule.date_to < rule.date_from:
                raise ValidationError("Rule end date must be on/after start.")

    @api.constrains('min_stay')
    def _check_min_stay(self):
        for rule in self:
            if rule.min_stay < 1:
                raise ValidationError("Min stay must be at least 1 night.")


class HotelRateRestriction(models.Model):
    """Closed / min-stay restriction window for a plan."""
    _name = 'hotel.rate.restriction'
    _description = "Hotel Rate Restriction"
    _order = 'date_from desc'

    plan_id = fields.Many2one('hotel.rate.plan', string="Plan",
                              required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 related='plan_id.company_id',
                                 store=True, readonly=True, index=True)
    room_template_id = fields.Many2one(
        'product.template', string="Room",
        domain=[('is_room', '=', True)],
        help="Room this restriction applies to; empty = all rooms.",
        ondelete="cascade", index=True)
    date_from = fields.Date(string="From", required=True)
    date_to = fields.Date(string="To", required=True)
    closed = fields.Boolean(string="Closed", default=False,
                            help="When set, no arrival/stay may cover "
                            "these dates.")
    min_stay = fields.Integer(string="Min Stay (nights)", default=1)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to \
                    and rec.date_to < rec.date_from:
                raise ValidationError(
                    "Restriction end date must be on/after start.")

    @api.constrains('min_stay')
    def _check_min_stay(self):
        for rec in self:
            if rec.min_stay < 1:
                raise ValidationError("Min stay must be at least 1 night.")


class HotelRateEngine(models.AbstractModel):
    """Priced nightly room rates + restriction checks + folio posting.

    Consumes hotel.folio / product.pricelist; produces nightly
    hotel.folio.line records. Business-day guard stays in
    hotel.charge.service.post_charge (single enforcement point).
    """
    _name = 'hotel.rate.engine'
    _description = "Hotel Rate Engine"

    @api.model
    def _base_price(self, room, plan):
        if plan.pricelist_id:
            variant = room.product_variant_id or room
            return plan.pricelist_id._get_product_price(variant, 1.0)
        return room.list_price

    @api.model
    def _matching_rule(self, plan, room_id, day):
        rules = self.env['hotel.rate.rule'].search([
            ('plan_id', '=', plan.id),
            ('date_from', '<=', day),
            ('date_to', '>=', day),
            '|', ('room_template_id', '=', room_id),
            ('room_template_id', '=', False),
        ])
        if not rules:
            return None
        specific = rules.filtered(lambda r: r.room_template_id.id == room_id)
        pool = specific or rules
        return sorted(pool, key=lambda r: (r.date_from, r.id))[-1]

    @api.model
    def price_for(self, room_template_id, date, plan_id, pax=2):
        """Nightly price for a room template on a date under a plan."""
        day = _to_date(date)
        room = self.env['product.template'].browse(room_template_id)
        if not room.exists() or not room.is_room:
            raise ValidationError("Room %s does not exist." % room_template_id)
        plan = self.env['hotel.rate.plan'].browse(plan_id)
        if not plan.exists():
            raise ValidationError("Rate plan %s does not exist." % plan_id)
        if plan.company_id.id != self.env.company.id:
            raise ValidationError(
                "Rate plan belongs to %s; price from that company."
                % plan.company_id.display_name)
        if pax and room.num_person and pax > room.num_person:
            raise ValidationError(
                "Room %s fits %d; requested %d pax."
                % (room.display_name, room.num_person, pax))
        base = self._base_price(room, plan)
        rule = self._matching_rule(plan, room.id, day)
        if not rule:
            return base
        return base * (1.0 + (rule.adjustment_pct or 0.0) / 100.0)

    @api.model
    def check_stay(self, room_template_id, date_from, date_to,
                   plan_id, pax=2):
        """Validate closed + min-stay for a stay window.

        Returns the night count. Raises ValidationError on violation.
        """
        start = _to_date(date_from)
        end = _to_date(date_to)
        if end <= start:
            raise ValidationError("Checkout must be after check-in.")
        nights = (end - start).days
        room = self.env['product.template'].browse(room_template_id)
        if not room.exists() or not room.is_room:
            raise ValidationError("Room %s does not exist." % room_template_id)
        plan = self.env['hotel.rate.plan'].browse(plan_id)
        if not plan.exists():
            raise ValidationError("Rate plan %s does not exist." % plan_id)
        if plan.company_id.id != self.env.company.id:
            raise ValidationError(
                "Rate plan belongs to %s; price from that company."
                % plan.company_id.display_name)
        # Closed restrictions overlapping any night of the stay.
        closed = self.env['hotel.rate.restriction'].search_count([
            ('plan_id', '=', plan.id),
            ('closed', '=', True),
            ('date_from', '<', end),
            ('date_to', '>=', start),
            '|', ('room_template_id', '=', room.id),
            ('room_template_id', '=', False),
        ])
        if closed:
            raise ValidationError("Closed dates cover this stay.")
        # Min stay = max over rules + restrictions overlapping the window.
        required = 1
        for model in ('hotel.rate.rule', 'hotel.rate.restriction'):
            recs = self.env[model].search([
                ('plan_id', '=', plan.id),
                ('date_from', '<', end),
                ('date_to', '>=', start),
                '|', ('room_template_id', '=', room.id),
                ('room_template_id', '=', False),
            ])
            for rec in recs:
                required = max(required, rec.min_stay or 1)
        if nights < required:
            raise ValidationError(
                "Minimum stay is %d night(s); requested %d."
                % (required, nights))
        if pax and room.num_person and pax > room.num_person:
            raise ValidationError(
                "Room %s fits %d; requested %d pax."
                % (room.display_name, room.num_person, pax))
        return nights

    @api.model
    def post_stay_nights(self, folio_id, room_template_id,
                         date_from, date_to, plan_id, pax=2):
        """Post one folio line per night; returns the created lines.

        Pre-validates ALL nights are open before the first post_charge
        (no partial stays), and dedups on folio + product + hotel date
        + room so two rooms sharing one product never collapse.
        Business-day guard enforced per night inside post_charge.
        """
        nights = self.check_stay(room_template_id, date_from, date_to,
                                 plan_id, pax=pax)
        folio = self.env['hotel.folio'].browse(folio_id)
        if not folio.exists():
            raise ValidationError("Folio %s does not exist." % folio_id)
        if folio.state != 'open':
            raise ValidationError("Can only post charges to an open folio.")
        room = self.env['product.template'].browse(room_template_id)
        product = room.product_variant_id
        if not product:
            raise ValidationError("Room %s has no saleable variant."
                                  % room.display_name)
        plan = self.env['hotel.rate.plan'].browse(plan_id)
        start = _to_date(date_from)
        folio_company = folio.booking_id.company_id or self.env.company
        if plan.company_id.id != folio_company.id:
            raise ValidationError(
                "Rate plan belongs to %s; folio belongs to %s."
                % (plan.company_id.display_name,
                   folio_company.display_name))
        charge = self.env['hotel.charge.service']
        days = [start + timedelta(days=offset) for offset in range(nights)]
        for day in days:
            charge._check_open_day(day, folio_company)
        lines = self.env['hotel.folio.line']
        for day in days:
            dup = self.env['hotel.folio.line'].search([
                ('folio_id', '=', folio.id),
                ('product_id', '=', product.id),
                ('hotel_date', '=', day),
                ('room_template_id', '=', room.id),
            ], limit=1)
            if dup:
                lines |= dup
                continue
            price = self.price_for(room.id, day, plan.id, pax)
            lines |= charge.post_charge(
                folio.id, product.id, 1, price, 'to_guest',
                hotel_date=day, room_template_id=room.id)
        return lines
