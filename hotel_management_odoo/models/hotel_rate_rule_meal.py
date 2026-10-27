# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HotelRateRuleMealLine(models.Model):
    """Fixed per-plan adjustment on one rate rule.

    One line per active meal plan, auto-created at 0% on rule
    create; lines are never added or removed afterwards (same
    pattern as ``hotel.room.type.meal.price``). Percent adjusts
    the phase-1 type x plan price (x(1+v/100)); fixed replaces it.
    """
    _name = 'hotel.rate.rule.meal.line'
    _description = "Hotel Rate Rule Meal Line"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'rule_id, meal_plan_id'

    rule_id = fields.Many2one('hotel.rate.rule', string="Rate Rule",
                              required=True, ondelete="cascade",
                              index=True, tracking=True)
    company_id = fields.Many2one('res.company', string="Company",
                                 related='rule_id.company_id',
                                 store=True, readonly=True, index=True)
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

    @api.constrains('rule_id', 'meal_plan_id')
    def _check_unique_rule_plan(self):
        for rec in self:
            dup = self.search([
                ('id', '!=', rec.id),
                ('rule_id', '=', rec.rule_id.id),
                ('meal_plan_id', '=', rec.meal_plan_id.id),
            ], limit=1)
            if dup:
                raise ValidationError(
                    "Meal line already set for rule %s, plan %s."
                    % (rec.rule_id.display_name,
                       rec.meal_plan_id.display_name))

    def unlink(self):
        raise ValidationError(
            "Rule meal lines cannot be deleted; every rule "
            "keeps every meal plan. Set the value instead.")
