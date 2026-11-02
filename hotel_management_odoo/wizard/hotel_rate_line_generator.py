# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

RO_MEAL_CODE = 'RO'


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
    copy_mode = fields.Selection(
        [('blank', 'Blank'), ('copy-ro', 'Copy RO + formula')],
        string='Copy Mode', default='blank', required=True)
    uplift_mode = fields.Selection(
        [('fixed', 'Fixed'), ('percent', 'Percent')],
        string='Uplift Mode', default='percent', required=True)
    uplift_value = fields.Float(string='Uplift Value', default=0.0)
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
        if self.uplift_value < 0:
            raise ValidationError("Uplift value cannot be negative.")
        line_model = self.env['hotel.rate.line']
        created = 0
        # RO-first ordering: non-RO combos copy the RO line, including an RO
        # line created earlier in this same run. Sorting guarantees RO combos
        # exist before any dependent lookup runs.
        meals_sorted = self.meal_ids.sorted(
            key=lambda m: (m.code != RO_MEAL_CODE, m.code or '', m.id))
        for period in self.period_ids:
            for room_type in self.type_ids:
                for meal in meals_sorted:
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
                        'price': self._price_for(period, room_type, meal),
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

    def _price_for(self, period, room_type, meal):
        """Price for one combo: RO-based formula in copy-ro mode, else blank."""
        if self.copy_mode != 'copy-ro' or meal.code == RO_MEAL_CODE:
            return self.price
        ro_line = self.env['hotel.rate.line'].find_line(
            period.id, room_type.id, RO_MEAL_CODE, company_id=self.company_id.id)
        if not ro_line:
            return self.price
        base = ro_line.price
        if self.uplift_mode == 'percent':
            return base * (1.0 + (self.uplift_value or 0.0) / 100.0)
        return base + (self.uplift_value or 0.0)
