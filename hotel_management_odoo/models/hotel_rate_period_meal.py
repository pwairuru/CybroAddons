# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HotelRatePeriodMealLine(models.Model):
    """Fixed per-plan board supplement on one rate period.

    One line per active meal plan, auto-created at 0% on period
    create; lines are never added or removed afterwards (same
    pattern as ``hotel.room.type.meal.price``). Percent adjusts
    the type x plan price (x(1+v/100)); fixed replaces it.
    """
    _name = 'hotel.rate.period.meal.line'
    _description = "Hotel Rate Period Meal Line"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'period_id, meal_plan_id'

    period_id = fields.Many2one('hotel.rate.period',
                                string="Rate Period",
                                required=True, ondelete="cascade",
                                index=True, tracking=True)
    meal_plan_id = fields.Many2one('hotel.meal.plan', string="Meal Plan",
                                   required=True, ondelete="restrict",
                                   index=True, tracking=True)
    rate_type = fields.Selection([('percent', 'Percent'),
                                  ('fixed', 'Fixed')],
                                 string="Rate Type", default='percent',
                                 required=True, tracking=True)
    value = fields.Float(string="Value", default=0.0, tracking=True,
                         help="Percent: adjustment over the type x plan "
                         "price (e.g. 10 = +10%). Fixed: replaces it.")

    @api.constrains('value')
    def _check_value(self):
        for rec in self:
            if rec.rate_type == 'fixed' and rec.value < 0:
                raise ValidationError(
                    "Fixed meal value cannot be negative.")

    @api.constrains('period_id', 'meal_plan_id')
    def _check_unique_period_plan(self):
        for rec in self:
            dup = self.search([
                ('id', '!=', rec.id),
                ('period_id', '=', rec.period_id.id),
                ('meal_plan_id', '=', rec.meal_plan_id.id),
            ], limit=1)
            if dup:
                raise ValidationError(
                    "Meal line already set for period %s, plan %s."
                    % (rec.period_id.display_name,
                       rec.meal_plan_id.display_name))

    def unlink(self):
        raise ValidationError(
            "Period meal lines cannot be deleted; every period "
            "keeps every meal plan. Set the value instead.")
