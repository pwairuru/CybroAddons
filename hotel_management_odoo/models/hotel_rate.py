# -*- coding: utf-8 -*-
import calendar
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
    date_from = fields.Date(string="From", compute='_compute_dates_from_period',
                              store=True, readonly=True, tracking=True)
    date_to = fields.Date(string="To", compute='_compute_dates_from_period',
                          store=True, readonly=True, tracking=True)
    adjustment_pct = fields.Float(string="Adjustment %", default=0.0,
                                  help="e.g. 50 = +50%, -20 = -20%.",
                                  tracking=True)
    min_stay = fields.Integer(string="Min Stay (nights)", default=1,
                              tracking=True)
    mon = fields.Boolean(string="Mon", default=True, tracking=True)
    tue = fields.Boolean(string="Tue", default=True, tracking=True)
    wed = fields.Boolean(string="Wed", default=True, tracking=True)
    thu = fields.Boolean(string="Thu", default=True, tracking=True)
    fri = fields.Boolean(string="Fri", default=True, tracking=True)
    sat = fields.Boolean(string="Sat", default=True, tracking=True)
    sun = fields.Boolean(string="Sun", default=True, tracking=True)
    period_id = fields.Many2one('hotel.rate.period', string="Period",
                                required=True,
                                help="Dates derive from this period and year.",
                                ondelete="restrict", index=True,
                                tracking=True)
    period_year = fields.Integer(string="Period Year", required=True,
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
        year = int(year)
        date_from = date(year, start[0],
                         min(start[1], calendar.monthrange(year, start[0])[1]))
        end_year = year + 1 if end < start else year
        date_to = date(end_year, end[0],
                       min(end[1], calendar.monthrange(end_year, end[0])[1]))
        return date_from, date_to

    @api.depends('period_id', 'period_year')
    def _compute_dates_from_period(self):
        for rule in self:
            if rule.period_id and rule.period_year:
                date_from, date_to = self._dates_from_period(
                    rule.period_id, rule.period_year)
                rule.date_from = date_from
                rule.date_to = date_to
            else:
                rule.date_from = False
                rule.date_to = False

    @api.constrains('period_id', 'period_year')
    def _check_period_year_match(self):
        for rule in self:
            if rule.period_id.applies_year and rule.period_year \
                    != rule.period_id.applies_year:
                raise ValidationError(
                    "Rule year %s does not match period %s "
                    "applies-year %s."
                    % (rule.period_year,
                       rule.period_id.display_name,
                       rule.period_id.applies_year))

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        if 'period_id' in fields_list \
                and not defaults.get('period_id'):
            today = fields.Date.today()
            period = self.env['hotel.rate.period'].search(
                [('active', '=', True)], order='sequence')
            defaults['period_id'] = next(
                (p.id for p in period
                 if p.covers(today.month, today.day)), False)
        return defaults

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
                    'rate_type', 'fixed_price', 'adjustment_pct',
                    'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
    def _check_type_priority_overlap(self):
        weekdays = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
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
                if not any(rule[day] and other[day] for day in weekdays):
                    continue
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

    #: Rate calendar window cap: matrix() never spans more.
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

        ``board`` selects a board basis: ``price`` is the ``price_for``
        value for that board (period-line uplift applied; ``RO`` keeps
        the legacy base path) and the matching board supplement
        is added as ``board`` with ``total`` = price + supplement
        (``RO`` adds nothing). ``board=False`` means all plans: each
        cell also carries ``plans`` (per meal-plan code price via the
        plan-price resolver; ``RO`` stays the legacy price) and every
        date carries a ``period`` label (first active
        ``hotel.rate.period`` covering the month-day by sequence,
        else False). Window capped at 42 days.
        Company-scoped: types, plan, rooms and business days all
        resolve under ``env.company``.
        Returns ``{dates[], periods[], plan_id, rows[{type_id, name,
        cells[]}]}`` where each cell holds ``{date, price, base,
        delta_pct, rule_id, min_stay, closed, available, board,
        total[, plans, period]}`` (``plans`` only in all-plans mode).
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
        show_all = board is False
        meal_codes = []
        if show_all:
            meal_codes = self.env['hotel.meal.plan'].search(
                [('active', '=', True)], order='code').mapped('code')
        periods = self.env['hotel.rate.period'].search(
            [('active', '=', True)], order='sequence')
        period_labels = []
        for day in days:
            label = False
            for period in periods:
                if period.covers(day.month, day.day):
                    label = period.name
                    break
            period_labels.append(label)
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
            for day_idx, day in enumerate(days):
                day_str = fields.Date.to_string(day)
                price = float(self.price_for(
                    rep.id, day, plan.id,
                    board=board if board else 'RO')) \
                    if plan and rep else base
                delta = round((price - base) / base * 100.0, 2) \
                    if base else 0.0
                rule = self._matching_rule(plan, rep.id, day) \
                    if plan and rep else None
                required = 1
                weekday = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat',
                           'sun'][day.weekday()]
                for rec in rules:
                    if not rec[weekday]:
                        continue
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
                cell = {
                    'date': day_str, 'price': price, 'base': base,
                    'delta_pct': delta,
                    'rule_id': rule.id if rule else False,
                    'min_stay': required, 'closed': bool(closed),
                    'available': max(len(room_ids) - booked - ooo_count, 0),
                    'board': supplement,
                    'total': float(price + supplement),
                    'period': period_labels[day_idx],
                }
                if show_all:
                    # Per meal-plan price via the plan-price resolver.
                    # RO stays on the legacy path intentionally (Ruling 4):
                    # assigned explicitly from the cell price so it can
                    # never drift through the resolver.
                    if plan and rep:
                        plans_cell = {}
                        for code in meal_codes:
                            if code == 'RO':
                                plans_cell[code] = float(price)
                            else:
                                plans_cell[code] = float(self.price_for(
                                    rep.id, day, plan.id, board=code))
                        cell['plans'] = plans_cell
                    else:
                        cell['plans'] = {}
                cells.append(cell)
            rows.append({'type_id': rtype.id, 'name': rtype.name,
                         'cells': cells})
        return {
            'dates': [fields.Date.to_string(day) for day in days],
            'periods': period_labels,
            'plan_id': plan.id if plan else False,
            'rows': rows,
        }

    @api.model
    def period_matrix(self, year, type_ids, plan_id=None, board='RO'):
        """Rate calendar grid for room types x rate periods.

        One column per active ``hotel.rate.period`` (sequence order) for
        the given year. Each cell carries the min/max nightly ``total``
        across the period's nights (single-board mode only) plus the
        sorted rule ids covering it. Reuses :meth:`matrix` per period
        window (periods stay under its day cap).
        Returns ``{year, periods[{id, name, date_from, date_to}],
        plan_id, rows[{type_id, name, cells[{period_id, min, max,
        rule_ids}]}]}``.
        """
        year = int(year)
        if year < 2000 or year > 2100:
            raise ValidationError("Period matrix year %r out of range."
                                  % (year,))
        periods = self.env['hotel.rate.period'].search(
            [('active', '=', True)], order='sequence')
        rule_model = self.env['hotel.rate.rule']
        windows = []
        for period in periods:
            date_from, date_to = rule_model._dates_from_period(
                period, year)
            windows.append((period, date_from, date_to))
        per_type = {}
        for period, date_from, date_to in windows:
            data = self.matrix(
                type_ids, fields.Date.to_string(date_from),
                fields.Date.to_string(date_to), plan_id, board)
            for row in data['rows']:
                entry = per_type.setdefault(row['type_id'], {
                    'name': row['name'], 'cells': {}})
                totals = [cell['total'] for cell in row['cells']]
                rules = sorted({cell['rule_id'] for cell in row['cells']
                                if cell['rule_id']})
                entry['cells'][period.id] = {
                    'period_id': period.id,
                    'min': min(totals) if totals else 0.0,
                    'max': max(totals) if totals else 0.0,
                    'rule_ids': rules,
                }
        rows = []
        for type_id in sorted(per_type):
            entry = per_type[type_id]
            rows.append({
                'type_id': type_id, 'name': entry['name'],
                'cells': [entry['cells'][period.id] for period, _f, _t
                          in windows],
            })
        return {
            'year': year,
            'periods': [{
                'id': period.id, 'name': period.name,
                'date_from': fields.Date.to_string(date_from),
                'date_to': fields.Date.to_string(date_to),
            } for period, date_from, date_to in windows],
            'plan_id': data.get('plan_id') if windows else False,
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
        day = _to_date(day)
        room = self.env['product.template'].browse(room_id)
        room_type_id = (room.room_type_id.id
                        if room.exists() and room.room_type_id else False)
        rules = self.env['hotel.rate.rule'].search([
            ('plan_id', '=', plan.id),
            ('date_from', '<=', day),
            ('date_to', '>=', day),
        ])
        weekday = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][
            day.weekday()]
        candidates = []
        for rule in rules:
            type_ok = (not rule.room_type_id
                       or (room_type_id
                           and rule.room_type_id.id == room_type_id))
            tmpl_ok = (not rule.room_template_id
                       or rule.room_template_id.id == room_id)
            if type_ok and tmpl_ok and rule[weekday]:
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
    def _matching_line(self, room_id, day, board='RO'):
        room = self.env['product.template'].browse(room_id)
        if not room.exists() or not room.room_type_id:
            return self.env['hotel.rate.line'].browse()
        periods = self.env['hotel.rate.period']._find_applicable(day)
        for p in periods:
            line = self.env['hotel.rate.line'].find_line(
                p.id, room.room_type_id.id, board or 'RO')
            if line.exists():
                return line
        return self.env['hotel.rate.line'].browse()

    @api.model
    def _resolve_counts(self, pax=1, adults=None, children=0):
        """Effective (adults, children, total) for pricing.

        Legacy callers pass only pax (adults None): adults = pax.
        New callers pass adults/children explicitly; pax is
        ignored then except as the adults fallback."""
        eff_adults = pax if adults is None else adults
        eff_children = children or 0
        try:
            eff_adults = int(eff_adults or 0)
        except (TypeError, ValueError):
            eff_adults = 0
        try:
            eff_children = int(eff_children or 0)
        except (TypeError, ValueError):
            eff_children = 0
        if eff_adults < 0 or eff_children < 0:
            raise ValidationError("Occupant counts cannot be negative.")
        return eff_adults, eff_children, \
            eff_adults + eff_children

    @api.model
    def _validate_price_inputs(self, room_template_id, date, plan_id):
        day = _to_date(date)
        room = self.env['product.template'].browse(room_template_id)
        if not room.exists() or not room.is_room:
            raise ValidationError("Room %s does not exist." % room_template_id)
        if not plan_id:
            return day, room, self.env['hotel.rate.plan'].browse()
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
        if not rule.period_id:
            return False
        return rule.period_id.meal_line_ids.filtered(
            lambda l: l.meal_plan_id.code == code)[:1]

    @api.model
    def price_detailed(self, room_template_id, date, plan_id, pax=1,
                       adults=None, children=0,
                       board='RO', booking=None):
        """Rate-line nightly breakdown.

        Prices from ``hotel.rate.line`` via :meth:`_matching_line`
        (period priority fallback) + ``compute_night``. ``plan_id``
        is ignored except for the company check in
        ``_validate_price_inputs``. Legacy ``hotel.rate.rule``
        path kept only as deprecated shim in ``_matching_rule``.
        Returns ``{net, base, resolved, adjustment, occupancy,
        board, rule_id, line_id, lines[], basis}`` with
        ``basis='rate_line'``.
        """
        day, room, plan = self._validate_price_inputs(
            room_template_id, date, plan_id)
        eff_adults, eff_children, total = \
            self._resolve_counts(pax=pax, adults=adults,
                                 children=children)
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
        line = self._matching_line(room.id, day, board)
        if not line.exists():
            raise ValidationError('No rate configured for this stay.')
        calc = line.compute_night(eff_adults, eff_children)
        base_price = float(line.price or 0.0)
        extra_a = float(calc.get('extra_a', 0.0) or 0.0)
        extra_c = float(calc.get('extra_c', 0.0) or 0.0)
        return {
            'net': float(calc['net']),
            'base': base_price,
            'resolved': base_price,
            'adjustment': 0.0,
            'occupancy': float(extra_a + extra_c),
            'board': 0.0,
            'rule_id': line.id,
            'line_id': line.id,
            'lines': [
                {'band': 'base', 'qty': 1,
                 'amount': base_price, 'total': base_price},
                {'band': 'adult',
                 'qty': max(0, eff_adults - (line.included_adults or 0)),
                 'amount': extra_a, 'total': extra_a},
                {'band': 'child',
                 'qty': max(0, eff_children - (line.included_children or 0)),
                 'amount': extra_c, 'total': extra_c},
            ],
            'basis': 'rate_line',
        }

    @api.model
    def price_for(self, room_template_id, date, plan_id, pax=1,
                  adults=None, children=0, board='RO'):
        """Nightly net for a room template on a date under a plan.

        Rate-line path: :meth:`_matching_line` finds the applicable
        ``hotel.rate.line`` (period priority fallback on the room
        type + board meal code) and ``compute_night`` prices the
        occupancy. ``plan_id`` is only company-checked in
        ``_validate_price_inputs``. Keeps float return; for the full
        breakdown use price_detailed(). pax stays as the legacy
        positional guest count (mapped to adults); pass adults /
        children explicitly for occupancy pricing. Raises
        ValidationError when no line covers the stay or capacity is
        exceeded."""
        detailed = self.price_detailed(
            room_template_id, date, plan_id, pax=pax, adults=adults,
            children=children, board=board)
        return float(detailed['net'])

    @api.model
    def check_stay(self, room_template_id, date_from, date_to,
                   plan_id, pax=1, adults=None, children=0):
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
        # Conservative-window semantics: a rule applying to at least one
        # night of the stay requires its min_stay for the whole stay
        # (no per-night rework); rules applying to no night (e.g. a
        # weekend-only rule on a Mon-Fri stay) are skipped so
        # enforcement matches pricing via _matching_rule.
        required = 1
        rules = self.env['hotel.rate.rule'].search([
            ('plan_id', '=', plan.id),
            ('date_from', '<', end),
            ('date_to', '>=', start),
            '|', ('room_template_id', '=', room.id),
            ('room_template_id', '=', False),
        ])
        stay_days = [start + timedelta(days=offset) for offset in range(nights)]
        weekdays = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
        for rec in rules:
            type_ok = (not rec.room_type_id
                       or (room.room_type_id
                           and rec.room_type_id.id == room.room_type_id.id))
            if not type_ok:
                continue
            if not any(rec.date_from <= day <= rec.date_to
                       and rec[weekdays[day.weekday()]]
                       for day in stay_days):
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
        _, _, total = self._resolve_counts(
            pax=pax, adults=adults, children=children)
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
                         adults=None, children=0):
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
                                 children=children)
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
                children=children,
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
                    bline.get('occupancy_id') or False)
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
                                # Rate-line basis: detailed['rule_id']
                                # holds a hotel.rate.line id, not a
                                # hotel.rate.rule id, so leave the
                                # rule link empty (band lines do same).
                                'source_rule_id': False,
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
                    # See above: rule link stays empty on rate-line basis.
                    'source_rule_id': False,
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
