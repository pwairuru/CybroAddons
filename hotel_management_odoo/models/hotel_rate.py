# -*- coding: utf-8 -*-
from datetime import date, timedelta
from math import ceil

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
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string="Name", required=True, tracking=True)
    code = fields.Char(string="Code", tracking=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 required=True, index=True,
                                 default=lambda self: self.env.company)
    pricelist_id = fields.Many2one('product.pricelist', string="Pricelist",
                                   help="Base prices come from this "
                                   "pricelist when set; else room list price.",
                                   ondelete="set null", tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    rule_ids = fields.One2many('hotel.rate.rule', 'plan_id',
                               string="Seasonal Rules")
    restriction_ids = fields.One2many('hotel.rate.restriction', 'plan_id',
                                      string="Restrictions")

    @api.model
    def _default_plan(self, company=False):
        """Company default → Rack by name → lowest id.

        All candidates company-scoped; a default pointing at another
        company (e.g. set before the constraint existed) is ignored.
        """
        company = company or self.env.company
        default = company.default_rate_plan_id
        if default and default.exists() \
                and default.company_id.id == company.id:
            return default
        rack = self.search(
            [('company_id', '=', company.id),
             ('name', '=ilike', 'rack')], order='id', limit=1)
        if rack:
            return rack
        return self.search(
            [('company_id', '=', company.id)], order='id', limit=1)

    @api.model
    def _plan_for_booking(self, booking):
        """Plan matching the booking's board, else the company default.

        ``room.booking.meal_plan`` stores BB/HB/FB (or RO when no board
        was sold), so the code lookup keeps plans interchangeable across
        companies while still falling back to a usable plan.
        """
        company = booking.company_id or self.env.company
        code = (booking.meal_plan or '').strip()
        plan = self.browse()
        if code:
            plan = self.search(
                [('company_id', '=', company.id), ('code', '=', code)],
                order='id', limit=1)
        return plan or self._default_plan(company)


class HotelRateRule(models.Model):
    """Seasonal adjustment window for a plan.

    Type-keyed rates win by rank: highest priority wins, then most
    specific (room beats type beats generic), then shortest window,
    then latest date_from, then latest id. room_template_id stays as
    a legacy per-room exception path (nullable).

    Overlap scoping (deliberate): the conflicting-rate guard below
    only fires for the same plan + same room_type + same priority +
    same room_template (both-empty counts as same). Same-type /
    same-priority overlaps on DIFFERENT rooms are allowed — move the
    exception priority up instead of duplicating the window.
    """
    _name = 'hotel.rate.rule'
    _description = "Hotel Rate Rule"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc'

    plan_id = fields.Many2one('hotel.rate.plan', string="Plan",
                              required=True, ondelete="cascade", index=True,
                              tracking=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 related='plan_id.company_id',
                                 store=True, readonly=True, index=True)
    room_type_id = fields.Many2one('hotel.room.type', string="Room Type",
                                   help="Room type this rule applies to; "
                                   "empty = all types.",
                                   ondelete="cascade", index=True,
                                   tracking=True)
    rate_type = fields.Selection([('percent', 'Percent'),
                                  ('fixed', 'Fixed')],
                                 string="Rate Type", default='percent',
                                 required=True, tracking=True)
    fixed_price = fields.Float(string="Fixed Price", tracking=True)
    priority = fields.Integer(string="Priority", default=10, tracking=True)
    room_template_id = fields.Many2one(
        'product.template', string="Room",
        domain=[('is_room', '=', True)],
        help="Room this rule applies to; empty = all rooms.",
        ondelete="cascade", index=True, tracking=True)
    date_from = fields.Date(string="From", required=True, tracking=True)
    date_to = fields.Date(string="To", required=True, tracking=True)
    adjustment_pct = fields.Float(string="Adjustment %", default=0.0,
                                  help="e.g. 50 = +50%, -20 = -20%.",
                                  tracking=True)
    min_stay = fields.Integer(string="Min Stay (nights)", default=1,
                              tracking=True)
    meal_line_ids = fields.One2many('hotel.rate.rule.meal.line', 'rule_id',
                                    string="Meal Lines")
    period_id = fields.Many2one('hotel.rate.period', string="Period",
                                help="Picking a period fills date_from/to "
                                "for the chosen year; dates stay the "
                                "source of truth for matching.",
                                ondelete="set null", index=True,
                                tracking=True)
    period_year = fields.Integer(string="Period Year",
                                 default=lambda self: fields.Date.today().year,
                                 tracking=True)

    @api.model
    def _dates_from_period(self, period, year):
        """Concrete (date_from, date_to) for a period + year.

        Year-end wraps roll the end date into the next year
        (e.g. 12-20 -> 01-05 + 2026 = 2026-12-20 -> 2027-01-05).
        """
        start = tuple(int(x) for x in period.start_md.split('-'))
        end = tuple(int(x) for x in period.end_md.split('-'))
        date_from = date(int(year), start[0], start[1])
        if end < start:
            date_to = date(int(year) + 1, end[0], end[1])
        else:
            date_to = date(int(year), end[0], end[1])
        return date_from, date_to

    @api.onchange('period_id', 'period_year')
    def _onchange_period_fill_dates(self):
        for rule in self:
            if rule.period_id and rule.period_year:
                date_from, date_to = self._dates_from_period(
                    rule.period_id, rule.period_year)
                rule.date_from = date_from
                rule.date_to = date_to

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('period_id') and vals.get('period_year') \
                    and (not vals.get('date_from')
                         or not vals.get('date_to')):
                period = self.env['hotel.rate.period'].browse(
                    vals['period_id'])
                if period.exists():
                    date_from, date_to = self._dates_from_period(
                        period, vals['period_year'])
                    vals['date_from'] = fields.Date.to_string(date_from)
                    vals['date_to'] = fields.Date.to_string(date_to)
        records = super().create(vals_list)
        plans = self.env['hotel.meal.plan'].search(
            [('active', '=', True)])
        line_model = self.env['hotel.rate.rule.meal.line']
        for rule in records:
            have = set(rule.meal_line_ids.mapped('meal_plan_id.id'))
            for plan in plans:
                if plan.id not in have:
                    line_model.create({
                        'rule_id': rule.id,
                        'meal_plan_id': plan.id,
                        'rate_type': 'percent',
                        'value': 0.0,
                    })
        return records

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

    @api.constrains('period_year')
    def _check_period_year(self):
        for rule in self:
            if rule.period_year and rule.period_year < 2000:
                raise ValidationError(
                    "Period year must be 2000 or later.")

    def _effective_rate(self):
        self.ensure_one()
        if self.rate_type == 'fixed':
            return ('fixed', self.fixed_price or 0.0)
        return ('percent', self.adjustment_pct or 0.0)

    @api.constrains('plan_id', 'room_type_id', 'room_template_id',
                    'priority', 'date_from', 'date_to',
                    'rate_type', 'fixed_price', 'adjustment_pct')
    def _check_type_priority_overlap(self):
        for rule in self:
            if not rule.room_type_id:
                continue
            if not rule.date_from or not rule.date_to:
                continue
            overlapping = self.search([
                ('id', '!=', rule.id),
                ('plan_id', '=', rule.plan_id.id),
                ('room_type_id', '=', rule.room_type_id.id),
                ('room_template_id', '=',
                 rule.room_template_id.id or False),
                ('priority', '=', rule.priority or 0),
                ('date_from', '<=', rule.date_to),
                ('date_to', '>=', rule.date_from),
            ])
            for other in overlapping:
                if rule._effective_rate() != other._effective_rate():
                    raise ValidationError(
                        "Overlapping rules for plan %s, type %s, "
                        "priority %s have conflicting rates."
                        % (rule.plan_id.display_name,
                           rule.room_type_id.display_name,
                           rule.priority))


class HotelRateRestriction(models.Model):
    """Closed / min-stay restriction window for a plan."""
    _name = 'hotel.rate.restriction'
    _description = "Hotel Rate Restriction"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc'

    plan_id = fields.Many2one('hotel.rate.plan', string="Plan",
                              required=True, ondelete="cascade", index=True,
                              tracking=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 related='plan_id.company_id',
                                 store=True, readonly=True, index=True)
    room_template_id = fields.Many2one(
        'product.template', string="Room",
        domain=[('is_room', '=', True)],
        help="Room this restriction applies to; empty = all rooms.",
        ondelete="cascade", index=True, tracking=True)
    date_from = fields.Date(string="From", required=True, tracking=True)
    date_to = fields.Date(string="To", required=True, tracking=True)
    closed = fields.Boolean(string="Closed", default=False,
                            help="When set, no arrival/stay may cover "
                            "these dates.", tracking=True)
    min_stay = fields.Integer(string="Min Stay (nights)", default=1,
                              tracking=True)

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

    #: Rate calendar window cap (Task 6): matrix() never spans more.
    MATRIX_MAX_DAYS = 42

    @api.model
    def matrix(self, type_ids, date_from, date_to, plan_id=None,
               board='RO'):
        """Rate calendar grid for room types x dates.

        Per type/date calls the ``price_for`` float path on the type's
        first room, then derives ``delta_pct`` against the type BAR
        (``base_rate``), the max overlapping ``min_stay``, the
        ``closed`` flag (plan restrictions + business-day closed),
        and ``available`` (type rooms minus overlapping bookings/OOO).

        ``board`` selects a board basis: the matching board supplement
        is added as ``board`` with ``total`` = price + supplement
        (``RO`` adds nothing). Window capped at 42 days.
        Company-scoped: types, plan, rooms and business days all
        resolve under ``env.company``.
        Returns ``{dates[], plan_id, rows[{type_id, name,
        cells[]}]}`` where each cell holds ``{date, price, base,
        delta_pct, rule_id, min_stay, closed, available, board,
        total}``.
        """
        start = _to_date(date_from)
        end = _to_date(date_to)
        if end < start:
            raise ValidationError(
                "Rate calendar end date must be on/after start.")
        if (end - start).days >= self.MATRIX_MAX_DAYS:
            end = start + timedelta(days=self.MATRIX_MAX_DAYS - 1)
        company = self.env.company
        if plan_id:
            plan = self.env['hotel.rate.plan'].browse(plan_id)
            if not plan.exists():
                raise ValidationError(
                    "Rate plan %s does not exist." % plan_id)
            if plan.company_id.id != company.id:
                raise ValidationError(
                    "Rate plan belongs to other company %s."
                    % plan.company_id.display_name)
        else:
            plan = self.env['hotel.rate.plan']._default_plan(company)
        types = self.env['hotel.room.type'].search(
            [('id', 'in', list(type_ids or [])),
             ('company_id', '=', company.id)], order='name')
        days = [start + timedelta(days=offset)
                for offset in range((end - start).days + 1)]
        biz = self.env['hotel.business.date']
        board_match = self.env['hotel.board.rule']._match \
            if board and board != 'RO' else None
        ooo_ids = set()
        for req in self.env['maintenance.request'].search([
                ('type', '=', 'room'),
                ('company_id', '=', company.id),
                ('state', 'not in', ('done', 'cancel'))]):
            ooo_ids.update(req.room_maintenance_ids.ids)
        lines = self.env['room.booking.line'].search([
            ('booking_id.company_id', '=', company.id),
            ('booking_id.state', 'in', ('reserved', 'check_in')),
            ('checkin_date', '<', fields.Datetime.to_string(
                end + timedelta(days=1))),
            ('checkout_date', '>', fields.Datetime.to_string(start)),
        ])
        rows = []
        for rtype in types:
            rooms = self.env['product.template'].search(
                [('is_room', '=', True),
                 ('room_type_id', '=', rtype.id),
                 '|', ('company_id', '=', False),
                 ('company_id', '=', company.id)], order='name')
            room_ids = set(rooms.ids)
            rep = rooms[:1]
            base = float(rtype.base_rate or 0.0)
            rules = self.env['hotel.rate.rule'].search([
                ('plan_id', '=', plan.id),
                ('date_from', '<=', fields.Date.to_string(end)),
                ('date_to', '>=', fields.Date.to_string(start)),
            ]) if plan else self.env['hotel.rate.rule'].browse()
            restrictions = self.env['hotel.rate.restriction'].search([
                ('plan_id', '=', plan.id),
                ('date_from', '<=', fields.Date.to_string(end)),
                ('date_to', '>=', fields.Date.to_string(start)),
            ]) if plan else self.env['hotel.rate.restriction'].browse()
            cells = []
            for day in days:
                day_str = fields.Date.to_string(day)
                price = float(self.price_for(rep.id, day, plan.id)) \
                    if plan and rep else base
                delta = round((price - base) / base * 100.0, 2) \
                    if base else 0.0
                rule = self._matching_rule(plan, rep.id, day) \
                    if plan and rep else None
                required = 1
                for rec in rules:
                    if rec.date_from <= day <= rec.date_to and (
                            not rec.room_type_id
                            or rec.room_type_id.id == rtype.id) and (
                            not rec.room_template_id
                            or rec.room_template_id.id in room_ids):
                        required = max(required, rec.min_stay or 1)
                closed = biz.is_day_closed(day)
                for rec in restrictions:
                    if not (rec.date_from <= day <= rec.date_to):
                        continue
                    if rec.room_template_id and \
                            rec.room_template_id.id not in room_ids:
                        continue
                    required = max(required, rec.min_stay or 1)
                    if rec.closed:
                        closed = True
                booked = 0
                for line in lines:
                    if line.room_id.id not in room_ids:
                        continue
                    ci = _to_date(line.checkin_date)
                    co = _to_date(line.checkout_date)
                    if ci and co and ci <= day < co:
                        booked += 1
                ooo_count = len([rid for rid in room_ids
                                 if rid in ooo_ids])
                supplement = 0.0
                if board_match:
                    hit = board_match(
                        rtype.id, board, day,
                        plan.id if plan else None, company.id)
                    supplement = float(hit.supplement) if hit else 0.0
                cells.append({
                    'date': day_str, 'price': price, 'base': base,
                    'delta_pct': delta,
                    'rule_id': rule.id if rule else False,
                    'min_stay': required, 'closed': bool(closed),
                    'available': max(len(room_ids) - booked - ooo_count, 0),
                    'board': supplement,
                    'total': float(price + supplement),
                })
            rows.append({'type_id': rtype.id, 'name': rtype.name,
                         'cells': cells})
        return {
            'dates': [fields.Date.to_string(day) for day in days],
            'plan_id': plan.id if plan else False,
            'rows': rows,
        }

    @api.model
    def _base_price(self, room, plan):
        if plan.pricelist_id:
            variant = room.product_variant_id or room
            return plan.pricelist_id._get_product_price(variant, 1.0)
        return room.list_price

    @api.model
    def _matching_rule(self, plan, room_id, day):
        room = self.env['product.template'].browse(room_id)
        room_type_id = (room.room_type_id.id
                        if room.exists() and room.room_type_id else False)
        rules = self.env['hotel.rate.rule'].search([
            ('plan_id', '=', plan.id),
            ('date_from', '<=', day),
            ('date_to', '>=', day),
        ])
        candidates = []
        for rule in rules:
            type_ok = (not rule.room_type_id
                       or (room_type_id
                           and rule.room_type_id.id == room_type_id))
            tmpl_ok = (not rule.room_template_id
                       or rule.room_template_id.id == room_id)
            if type_ok and tmpl_ok:
                candidates.append(rule)
        if not candidates:
            return None

        def _rank(rule):
            specificity = ((2 if rule.room_template_id else 0)
                           + (1 if rule.room_type_id else 0))
            if rule.date_from and rule.date_to:
                window = (rule.date_to - rule.date_from).days
            else:
                window = 0
            return (rule.priority or 0, specificity, -window,
                    rule.date_from, rule.id)

        return max(candidates, key=_rank)

    @api.model
    def _resolve_counts(self, pax=1, adults=None, children=0, toddlers=0):
        """Effective (adults, children, toddlers, total) for pricing.

        Legacy callers pass only pax (adults None): adults = pax.
        New callers pass adults/children/toddlers explicitly; pax is
        ignored then except as the adults fallback."""
        eff_adults = pax if adults is None else adults
        eff_children = children or 0
        eff_toddlers = toddlers or 0
        try:
            eff_adults = int(eff_adults or 0)
        except (TypeError, ValueError):
            eff_adults = 0
        try:
            eff_children = int(eff_children or 0)
        except (TypeError, ValueError):
            eff_children = 0
        try:
            eff_toddlers = int(eff_toddlers or 0)
        except (TypeError, ValueError):
            eff_toddlers = 0
        if eff_adults < 0 or eff_children < 0 or eff_toddlers < 0:
            raise ValidationError("Occupant counts cannot be negative.")
        return eff_adults, eff_children, eff_toddlers, \
            eff_adults + eff_children + eff_toddlers

    @api.model
    def _validate_price_inputs(self, room_template_id, date, plan_id):
        day = _to_date(date)
        room = self.env['product.template'].browse(room_template_id)
        if not room.exists() or not room.is_room:
            raise ValidationError("Room %s does not exist." % room_template_id)
        plan = self.env['hotel.rate.plan'].browse(plan_id)
        if not plan.exists():
            raise ValidationError("Rate plan %s does not exist." % plan_id)
        if plan.company_id.id != self.env.company.id:
            raise ValidationError(
                "Rate plan belongs to other company %s."
                % plan.company_id.display_name)
        return day, room, plan

    @api.model
    def _occupancy_record(self, room_type, plan, band):
        if not room_type:
            return None
        recs = self.env['hotel.rate.occupancy'].search([
            ('room_type_id', '=', room_type.id),
            ('band', '=', band),
            '|', ('plan_id', '=', plan.id),
            ('plan_id', '=', False),
        ])
        for rec in recs:
            if rec.plan_id and rec.plan_id.id == plan.id:
                return rec
        for rec in recs:
            if not rec.plan_id:
                return rec
        return None

    @api.model
    def _board_supplement(self, room_type, plan, board, day, booking=None):
        """Nightly per-person board supplement.

        Returns (supplement, False); the caller assigns reason codes
        (e.g. 'no-board-price' only applies to board-basis bands, set
        in price_detailed, never here)."""
        if board and board != 'RO':
            rule = self.env['hotel.board.rule']._match(
                room_type.id if room_type else False, board, day,
                plan.id if plan else None,
                company_id=self.env.company.id)
            if rule:
                return float(rule.supplement or 0.0), False
        if booking and hasattr(booking, 'meal_plan_supplement'):
            try:
                fallback = float(booking.meal_plan_supplement() or 0.0)
            except Exception:
                fallback = 0.0
            if fallback:
                return fallback, False
        return 0.0, False

    @api.model
    def _meal_plan_price(self, room_type, board):
        """Phase-1 type x plan price for the booking board.

        Returns False for RO (legacy base path) or when no usable
        table price exists, so legacy behavior stays untouched.
        """
        code = board.strip() if isinstance(board, str) else 'RO'
        # RO stays on the legacy path intentionally: RO has no meal
        # component and the phase-1 RO table price duplicates
        # base_rate authority, so routing it through meal lines
        # would change live RO pricing.
        if not room_type or not code or code == 'RO':
            return False
        line = room_type.meal_price_ids.filtered(
            lambda l: l.meal_plan_id.code == code)[:1]
        if not line or not line.price:
            return False
        return float(line.price)

    @api.model
    def _matching_meal_line(self, rule, board):
        """The matching rule's line for the booking board."""
        code = board.strip() if isinstance(board, str) else 'RO'
        if not rule or not code or code == 'RO':
            return False
        return rule.meal_line_ids.filtered(
            lambda l: l.meal_plan_id.code == code)[:1]

    @api.model
    def price_detailed(self, room_template_id, date, plan_id, pax=1,
                       adults=None, children=0, toddlers=0,
                       board='RO', booking=None):
        """Full nightly breakdown: {net, base, resolved, adjustment,
        occupancy, board, rule_id, lines[], basis}.

        lines[0] is the resolved stay line; following lines are one
        per extra-occupant band beyond included. Percent extras use
        ``basis``: resolved_rate => % of resolved, bar => % of the
        type BAR (type base_rate), board => % of the nightly
        per-person board supplement for the passed ``board`` (0.0
        with reason 'no-board-price' when no board rule matches).
        Each band line carries ``supplement`` (the nightly board
        supplement used as reference, 0.0 for non-board bases) and
        ``reason`` (False when priced, e.g. 'no-board-price' when the
        band prices at zero).
        """
        day, room, plan = self._validate_price_inputs(
            room_template_id, date, plan_id)
        eff_adults, eff_children, eff_toddlers, total = \
            self._resolve_counts(pax=pax, adults=adults,
                                 children=children, toddlers=toddlers)
        if total and room.num_person and total > room.num_person:
            raise ValidationError(
                "Room %s fits %d; requested %d pax."
                % (room.display_name, room.num_person, total))
        room_type = room.room_type_id or False
        if room_type and room_type.max_occupants \
                and total > room_type.max_occupants:
            raise ValidationError(
                "Room type %s fits %d; requested %d pax."
                % (room_type.display_name, room_type.max_occupants,
                   total))
        base = self._base_price(room, plan)
        rule = self._matching_rule(plan, room.id, day)
        plan_price = self._meal_plan_price(room_type, board)
        meal_line = self._matching_meal_line(rule, board) \
            if plan_price else False
        if plan_price:
            if meal_line and meal_line.rate_type == 'fixed':
                resolved = float(round(meal_line.value or 0.0, 2))
            elif meal_line:
                resolved = float(round(
                    plan_price * (1.0 + (meal_line.value or 0.0) / 100.0),
                    2))
            else:
                resolved = float(plan_price)
            adjustment = float(resolved - base)
            rule_id = rule.id if rule else False
            rule_basis = 'resolved_rate'
        elif not rule:
            resolved = float(base)
            adjustment = 0.0
            rule_id = False
            rule_basis = 'bar'
        elif rule.rate_type == 'fixed':
            resolved = float(rule.fixed_price or 0.0)
            adjustment = float(resolved - base)
            rule_id = rule.id
            rule_basis = 'resolved_rate'
        else:
            resolved = float(
                base * (1.0 + (rule.adjustment_pct or 0.0) / 100.0))
            adjustment = float(resolved - base)
            rule_id = rule.id
            rule_basis = 'resolved_rate'
        type_bar = float(room_type.base_rate) \
            if room_type else float(base)
        lines = [{
            'band': 'base', 'qty': 1, 'amount': float(resolved),
            'total': float(resolved), 'basis': rule_basis,
            'mode': (rule.rate_type if rule else 'bar'),
            'value': (rule.fixed_price if rule
                      and rule.rate_type == 'fixed'
                      else (rule.adjustment_pct if rule else 0.0)),
            'rule_id': rule_id,
        }]
        occupancy_total = 0.0
        for band, requested in (('adult', eff_adults),
                                ('child', eff_children),
                                ('toddler', eff_toddlers)):
            rec = self._occupancy_record(room_type, plan, band)
            if not rec:
                continue
            if rec.max_count and requested > rec.max_count:
                raise ValidationError(
                    "Band %s allows max %d; requested %d."
                    % (band, rec.max_count, requested))
            extra = max(0, requested - (rec.included_count or 0))
            if not extra:
                continue
            qty = extra if (rec.per or 'per_guest') == 'per_guest' \
                else ceil(extra / (rec.unit_capacity or 1))
            supplement, reason = self._board_supplement(
                room_type, plan, board, day, booking)
            if rec.mode == 'fixed':
                unit = float(rec.value or 0.0)
            else:
                if rec.basis == 'bar':
                    ref = type_bar
                elif rec.basis == 'board':
                    ref = supplement
                else:
                    ref = resolved
                unit = float(ref * (rec.value or 0.0) / 100.0)
            if rec.basis == 'board' and not supplement:
                reason = 'no-board-price'
                unit = 0.0
            lines.append({
                'band': band, 'qty': qty, 'amount': unit,
                'total': float(unit * qty), 'basis': rec.basis,
                'mode': rec.mode, 'value': rec.value,
                'supplement': supplement, 'reason': reason,
                'occupancy_id': rec.id,
            })
            occupancy_total += unit * qty
        net = float(resolved + occupancy_total)
        return {
            'net': net, 'base': float(base),
            'resolved': float(resolved),
            'adjustment': float(adjustment),
            'occupancy': float(occupancy_total), 'board': 0.0,
            'rule_id': rule_id, 'lines': lines, 'basis': rule_basis,
        }

    @api.model
    def price_for(self, room_template_id, date, plan_id, pax=1,
                  adults=None, children=0, toddlers=0, board='RO'):
        """Nightly price for a room template on a date under a plan.

        KEEPS float return (Task 4 adds nothing here). For the full
        breakdown use price_detailed(). pax stays as the legacy
        positional guest count (mapped to adults); pass adults /
        children / toddlers explicitly for occupancy pricing.
        ``board`` selects the phase-1 type x plan price as the base
        (with the matching rule's meal line applied); RO keeps the
        legacy base path."""
        detailed = self.price_detailed(
            room_template_id, date, plan_id, pax=pax, adults=adults,
            children=children, toddlers=toddlers, board=board)
        return float(detailed['net'])

    @api.model
    def check_stay(self, room_template_id, date_from, date_to,
                   plan_id, pax=1, adults=None, children=0, toddlers=0):
        """Validate closed + min-stay for a stay window.

        Min-stay is the max over any rule/restriction overlapping the
        window (conservative: a 3-night rule touching 1 night requires
        3). Type-keyed rules only apply to rooms of that type (same
        candidate logic as the price matcher: no-type matches all,
        typed matches its own type); template scoping is unchanged.
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
                "Rate plan belongs to other company %s."
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
        rules = self.env['hotel.rate.rule'].search([
            ('plan_id', '=', plan.id),
            ('date_from', '<', end),
            ('date_to', '>=', start),
            '|', ('room_template_id', '=', room.id),
            ('room_template_id', '=', False),
        ])
        for rec in rules:
            type_ok = (not rec.room_type_id
                       or (room.room_type_id
                           and rec.room_type_id.id == room.room_type_id.id))
            if not type_ok:
                continue
            required = max(required, rec.min_stay or 1)
        restrictions = self.env['hotel.rate.restriction'].search([
            ('plan_id', '=', plan.id),
            ('date_from', '<', end),
            ('date_to', '>=', start),
            '|', ('room_template_id', '=', room.id),
            ('room_template_id', '=', False),
        ])
        for rec in restrictions:
            required = max(required, rec.min_stay or 1)
        if nights < required:
            raise ValidationError(
                "Minimum stay is %d night(s); requested %d."
                % (required, nights))
        _, _, _, total = self._resolve_counts(
            pax=pax, adults=adults, children=children, toddlers=toddlers)
        if total and room.num_person and total > room.num_person:
            raise ValidationError(
                "Room %s fits %d; requested %d pax."
                % (room.display_name, room.num_person, total))
        if room.room_type_id and room.room_type_id.max_occupants \
                and total > room.room_type_id.max_occupants:
            raise ValidationError(
                "Room type %s fits %d; requested %d pax."
                % (room.room_type_id.display_name,
                   room.room_type_id.max_occupants, total))
        return nights

    @api.model
    def post_stay_nights(self, folio_id, room_template_id,
                         date_from, date_to, plan_id, pax=1,
                         adults=None, children=0, toddlers=0):
        """Post one folio line per night + one rate snapshot per night.

        Pre-validates ALL nights are open and resolves + validates every
        night's band products before the first post_charge (no partial
        stays: a band failure leaves zero lines), and dedups on folio +
        product + hotel date + room so two rooms sharing one product
        never collapse. Business-day guard enforced per night inside
        post_charge. Snapshots are immutable: an existing snapshot for
        the same folio + room + date + line is kept, never rewritten,
        except a folded pre-upgrade base line (price holds the old net
        incl occupancy) which is repriced to resolved with a folio note.
        """
        nights = self.check_stay(room_template_id, date_from, date_to,
                                 plan_id, pax=pax, adults=adults,
                                 children=children, toddlers=toddlers)
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
        snapshots = self.env['hotel.rate.snapshot']
        booking = folio.booking_id or False
        board = (booking.meal_plan or 'RO') if booking else 'RO'
        days = [start + timedelta(days=offset) for offset in range(nights)]
        detailed_by_day = {}
        bands_by_day = {}
        for day in days:
            charge._check_open_day(day, folio_company)
            detailed = self.price_detailed(
                room.id, day, plan.id, pax=pax, adults=adults,
                children=children, toddlers=toddlers,
                board=board, booking=booking)
            detailed_by_day[day] = detailed
            # Resolve + validate every night's band products up front:
            # a missing or duplicate service product raises before the
            # first post_charge, so a failed stay posts zero lines.
            seen = {}
            resolved_bands = []
            for bline in detailed['lines'][1:]:
                if not bline['total']:
                    continue
                occ = self.env['hotel.rate.occupancy'].browse(
                    bline['occupancy_id'])
                bproduct = occ.service_product_id \
                    if occ.service_product_id else False
                if not bproduct:
                    shared = [l2 for l2 in detailed['lines'][1:]
                              if l2['total']]
                    if len(shared) > 1:
                        raise ValidationError(
                            "Band %s needs a service product for "
                            "itemized posting (booking %s)."
                            % (bline['band'],
                               folio.booking_id.name or folio.id))
                    bproduct = product
                if bproduct.id in seen:
                    raise ValidationError(
                        "Bands %s and %s share service product %s for "
                        "itemized posting (booking %s)."
                        % (seen[bproduct.id], bline['band'],
                           bproduct.display_name,
                           folio.booking_id.name or folio.id))
                seen[bproduct.id] = bline['band']
                resolved_bands.append((bline, bproduct))
            bands_by_day[day] = resolved_bands
        lines = self.env['hotel.folio.line']
        for day in days:
            detailed = detailed_by_day[day]
            dup = self.env['hotel.folio.line'].search([
                ('folio_id', '=', folio.id),
                ('product_id', '=', product.id),
                ('hotel_date', '=', day),
                ('room_template_id', '=', room.id),
            ], limit=1)
            if dup:
                lines |= dup
                line = dup
                if bands_by_day[day] and \
                        float(line.price_unit or 0.0) != \
                        float(detailed['resolved']):
                    if (not line.locked) and (not line.invoiced_qty) \
                            and folio.state == 'open':
                        old_price = float(line.price_unit or 0.0)
                        line.write(
                            {'price_unit': detailed['resolved']})
                        bsnap = snapshots.search([
                            ('folio_line_id', '=', line.id),
                        ], limit=1)
                        if bsnap:
                            bsnap.write({
                                'base': detailed['base'],
                                'adjustment': detailed['adjustment'],
                                'occupancy': 0.0,
                                'board': detailed.get('board', 0.0),
                                'net': detailed['resolved'],
                                'tax': line.price_tax or 0.0,
                                'source_rule_id':
                                    detailed['rule_id'] or False,
                            })
                        folio.message_post(body=(
                            "Base charge repriced %.2f -> %.2f on %s "
                            "(itemized repost)."
                            % (old_price, detailed['resolved'], day)))
                    else:
                        raise ValidationError(
                            "Folio %s line %s is locked/invoiced/settled; "
                            "cannot reprice folded base charge for "
                            "itemized repost." % (folio.id, line.id))
            else:
                line = charge.post_charge(
                    folio.id, product.id, 1, detailed['resolved'],
                    'to_guest', hotel_date=day,
                    room_template_id=room.id,
                    booking_line_id=False)
                lines |= line
            existing = snapshots.search([
                ('folio_id', '=', folio.id),
                ('room_template_id', '=', room.id),
                ('hotel_date', '=', day),
                ('folio_line_id', '=', line.id),
            ], limit=1)
            if not existing:
                snapshots.create({
                    'company_id': folio_company.id,
                    'hotel_date': day,
                    'room_template_id': room.id,
                    'plan_id': plan.id,
                    'folio_id': folio.id,
                    'folio_line_id': line.id,
                    'base': detailed['base'],
                    'adjustment': detailed['adjustment'],
                    'occupancy': 0.0,
                    'board': detailed.get('board', 0.0),
                    'net': detailed['resolved'],
                    'tax': line.price_tax or 0.0,
                    'source_rule_id': detailed['rule_id'] or False,
                    'override': False,
                })
            for bline, bproduct in bands_by_day[day]:
                dup_band = self.env['hotel.folio.line'].search([
                    ('folio_id', '=', folio.id),
                    ('product_id', '=', bproduct.id),
                    ('hotel_date', '=', day),
                    ('room_template_id', '=', room.id),
                ], limit=1)
                if dup_band:
                    lines |= dup_band
                    band_line = dup_band
                else:
                    band_line = charge.post_charge(
                        folio.id, bproduct.id, bline['qty'],
                        bline['amount'], 'to_guest', hotel_date=day,
                        room_template_id=room.id, source='rate')
                    lines |= band_line
                if not snapshots.search([
                        ('folio_id', '=', folio.id),
                        ('room_template_id', '=', room.id),
                        ('hotel_date', '=', day),
                        ('folio_line_id', '=', band_line.id),
                ], limit=1):
                    snapshots.create({
                        'company_id': folio_company.id,
                        'hotel_date': day,
                        'room_template_id': room.id,
                        'plan_id': plan.id,
                        'folio_id': folio.id,
                        'folio_line_id': band_line.id,
                        'base': 0.0, 'adjustment': 0.0,
                        'occupancy': bline['total'],
                        'board': 0.0, 'net': bline['total'],
                        'tax': band_line.price_tax or 0.0,
                        'source_rule_id': False, 'override': False,
                    })
        return lines
