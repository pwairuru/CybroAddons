# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HotelRateLineGenerator(models.TransientModel):
    """Bulk-create missing rate lines for period x type x meal combos."""
    _name = 'hotel.rate.line.generator'
    _description = 'Generate Rate Lines'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    period_ids = fields.Many2many(
        'hotel.rate.period', string='Periods', required=True)
    type_ids = fields.Many2many(
        'hotel.room.type', string='Room Types', required=True)
    meal_ids = fields.Many2many(
        'hotel.meal.plan', string='Meal Plans', required=True)
    price = fields.Float(string='Price', required=True, default=0.0)
    included_adults = fields.Integer(default=2)
    included_children = fields.Integer(default=0)
    extra_adult_mode = fields.Selection(
        [('fixed', 'Fixed'), ('percent', 'Percent')],
        default='fixed', required=True)
    extra_adult_value = fields.Float(default=0.0)
    extra_child_mode = fields.Selection(
        [('fixed', 'Fixed'), ('percent', 'Percent')],
        default='percent', required=True)
    extra_child_value = fields.Float(default=50.0)
    extra_bed_price = fields.Float(default=0.0)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'period_ids' in fields_list and not res.get('period_ids') \
                and self.env.context.get('active_model') == 'hotel.rate.period' \
                and self.env.context.get('active_id'):
            res['period_ids'] = [(6, 0, [self.env.context['active_id']])]
        return res

    def action_generate(self):
        """Create lines for every missing combo; skip existing ones."""
        self.ensure_one()
        if self.price < 0:
            raise ValidationError("Price cannot be negative.")
        line_model = self.env['hotel.rate.line']
        created = 0
        for period in self.period_ids:
            for room_type in self.type_ids:
                for meal in self.meal_ids:
                    existing = line_model.find_line(
                        period.id, room_type.id, meal.code,
                        company_id=self.company_id.id)
                    if existing:
                        continue
                    line_model.create({
                        'company_id': self.company_id.id,
                        'period_id': period.id,
                        'room_type_id': room_type.id,
                        'meal_plan_id': meal.id,
                        'price': self.price,
                        'included_adults': self.included_adults,
                        'included_children': self.included_children,
                        'extra_adult_mode': self.extra_adult_mode,
                        'extra_adult_value': self.extra_adult_value,
                        'extra_child_mode': self.extra_child_mode,
                        'extra_child_value': self.extra_child_value,
                        'extra_bed_price': self.extra_bed_price,
                    })
                    created += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Rate Lines',
                'message': '%d line(s) created; existing combos skipped.' % created,
                'type': 'success',
                'sticky': False,
            },
        }
