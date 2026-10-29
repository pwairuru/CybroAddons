# -*- coding: utf-8 -*-
import calendar

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HotelRatePeriod(models.Model):
    _name = 'hotel.rate.period'
    _description = "Hotel Rate Period"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence'

    name = fields.Char(required=True, tracking=True,
                        help="Season name, e.g. H1, H2, Easter Promo. Shown on the rate calendar.")
    start_md = fields.Char(string="Start (MM-DD)", required=True,
                           tracking=True,
                           help="Season start as month-day, e.g. 01-01. Repeats every year unless Applies Year pins a single year.")
    end_md = fields.Char(string="End (MM-DD)", required=True, tracking=True,
                         help="Season end as month-day, e.g. 06-30. May wrap New Year (12-20 to 01-05).")
    sequence = fields.Integer(default=10, tracking=True,
                              help="Order when several periods cover the same day and priorities tie. Checked in this order.")
    active = fields.Boolean(default=True, tracking=True,
                            help="Inactive periods are ignored everywhere, as if the season did not exist.")
    meal_line_ids = fields.One2many('hotel.rate.period.meal.line',
                                    'period_id', string="Meal Lines",
                                    help="Legacy per-board uplifts, no longer used for pricing. Kept for history only.")
    priority = fields.Integer(default=10, tracking=True,
                              help="When periods overlap, the highest-priority period wins. Use a higher number for the exception, e.g. a holiday promo beating the base season.")
    applies_year = fields.Integer(string="Applies Year", tracking=True,
                                  help="Set for one-off promos; empty = "
                                  "recurs every year.")
    company_id = fields.Many2one('res.company', required=True, index=True, default=lambda self: self.env.company, tracking=True,
                                  help="Hotel this season belongs to. Periods never apply across companies.")
    rate_line_ids = fields.One2many('hotel.rate.line', 'period_id', string='Rates',
                                    help="One row per room type and board priced in this season. Combinations with no row fall through to the next lower-priority period.")

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        if 'meal_line_ids' in fields_list \
                and not defaults.get('meal_line_ids'):
            plans = self.env['hotel.meal.plan'].search(
                [('active', '=', True)], order='sequence')
            defaults['meal_line_ids'] = [
                (0, 0, {
                    'meal_plan_id': plan.id,
                    'rate_type': 'percent',
                    'value': 0.0,
                }) for plan in plans
            ]
        return defaults

    @api.model_create_multi
    def create(self, vals_list):
        periods = super().create(vals_list)
        periods.ensure_meal_lines()
        return periods

    def ensure_meal_lines(self):
        plans = self.env['hotel.meal.plan'].search(
            [('active', '=', True)])
        if plans and self:
            line_model = self.env['hotel.rate.period.meal.line']
            have = {
                (line.period_id.id, line.meal_plan_id.id)
                for line in line_model.search([
                    ('period_id', 'in', self.ids),
                    ('meal_plan_id', 'in', plans.ids),
                ])
            }
            missing = [{
                'period_id': period.id,
                'meal_plan_id': plan.id,
                'rate_type': 'percent',
                'value': 0.0,
            } for period in self for plan in plans
                if (period.id, plan.id) not in have]
            if missing:
                line_model.create(missing)

    @api.constrains('start_md', 'end_md')
    def _check_md(self):
        for rec in self:
            for val in (rec.start_md, rec.end_md):
                try:
                    m, d = (int(x) for x in val.split('-'))
                except (ValueError, AttributeError):
                    raise ValidationError(
                        "Bad month-day %r; use MM-DD." % (val,))
                if not 1 <= m <= 12 or not 1 <= d <= 31:
                    raise ValidationError(
                        "Bad month-day %r; use MM-DD." % (val,))
                if d > calendar.monthrange(2024, m)[1]:
                    raise ValidationError(
                        "Bad month-day %r; use MM-DD." % (val,))

    def covers(self, month, day):
        self.ensure_one()
        try:
            point = (int(month), int(day))
        except (TypeError, ValueError):
            raise ValidationError(
                "Bad month-day %r-%r; use MM-DD ints." % (month, day))
        if not 1 <= point[0] <= 12 or not 1 <= point[1] <= 31:
            raise ValidationError(
                "Bad month-day %r-%r; use MM-DD ints." % (month, day))
        start = tuple(int(x) for x in self.start_md.split('-'))
        end = tuple(int(x) for x in self.end_md.split('-'))
        if start <= end:
            return start <= point <= end
        return point >= start or point <= end

    @api.model
    def _find_applicable(self, stay_date, company_id=None):
        from datetime import date as _date
        day = stay_date if hasattr(stay_date,'month') else fields.Date.from_string(stay_date)
        company_id = company_id or self.env.company.id
        cands = self.search([('active','=',True),('company_id','in',[False,company_id])], order='priority desc, sequence, id')
        out = []
        for p in cands:
            if p.applies_year and int(p.applies_year) != day.year:
                continue
            if p.covers(day.month, day.day):
                out.append(p)
        return out
