# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2026-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
############################################################################
from odoo import api, fields, models
from datetime import datetime, time

import pytz

EAT = pytz.timezone('Africa/Nairobi')


class KitchenScreen(models.Model):
    """Kitchen Screen model for the cook"""
    _name = 'kitchen.screen'
    _description = 'Pos Kitchen Screen'
    _rec_name = 'sequence'

    def _pos_shop_id(self):
        """Domain for the Pos Shop"""
        kitchen = self.search([])
        if kitchen:
            return [('module_pos_restaurant', '=', True),
                    (
                    'id', 'not in', [rec.id for rec in kitchen.pos_config_id])]
        else:
            return [('module_pos_restaurant', '=', True)]

    sequence = fields.Char(readonly=True, default='New',
                           copy=False, tracking=True, help="Sequence of items")
    pos_config_id = fields.Many2one('pos.config', string='Allowed POS',
                                    domain=_pos_shop_id,
                                    help="Allowed POS for kitchen")
    pos_categ_ids = fields.Many2many('pos.category',
                                     string='Allowed POS Category',
                                     help="Allowed POS Category"
                                          "for the corresponding Pos")
    shop_number = fields.Integer(related='pos_config_id.id', string='Customer',
                                 help="Id of the POS")

    is_preparation_complete = fields.Boolean(
        string='Change Stage',
        default=False,
        help='Change the cooking stage when completing the preparation time',
    )

    cooking_count = fields.Integer(
        compute='_compute_order_counts', string='Cooking',
        help="Today's (EAT) kitchen orders still cooking (draft)")
    ready_count = fields.Integer(
        compute='_compute_order_counts', string='Ready',
        help="Today's (EAT) kitchen orders ready for pickup (waiting)")
    completed_count = fields.Integer(
        compute='_compute_order_counts', string='Completed',
        help="Today's (EAT) completed kitchen orders (ready)")

    def kitchen_screen(self):
        """Redirect to corresponding kitchen screen for the cook"""
        return {
            'type': 'ir.actions.act_url',
            'target': 'new',
            'url': '/pos/kitchen?pos_config_id= %s' % self.pos_config_id.id,
        }

    @api.depends('pos_config_id')
    def _compute_order_counts(self):
        """Today's (EAT) status counts for kanban cards. Same base
        domain as the dashboard (get_details) plus a start-of-today
        EAT cutoff so Completed never accumulates history. No stored
        fields, no schema change."""
        Order = self.env['pos.order'].sudo()
        today_eat = datetime.now(EAT).date()
        day_start_utc = EAT.localize(
            datetime.combine(today_eat, time.min)).astimezone(
            pytz.utc).replace(tzinfo=None)
        for rec in self:
            if not rec.pos_config_id:
                rec.cooking_count = 0
                rec.ready_count = 0
                rec.completed_count = 0
                continue
            base = [
                ('is_cooking', '=', True),
                ('config_id', '=', rec.pos_config_id.id),
                ('state', 'not in', ['cancel']),
                ('date_order', '>=', day_start_utc),
            ]
            rec.cooking_count = Order.search_count(
                base + [('order_status', '=', 'draft')])
            rec.ready_count = Order.search_count(
                base + [('order_status', '=', 'waiting')])
            rec.completed_count = Order.search_count(
                base + [('order_status', '=', 'ready')])

    @api.model_create_multi
    def create(self, vals_list):
        """Used to create sequence"""
        for vals in vals_list:
            if vals.get('sequence', "New") == "New":
                vals['sequence'] = self.env['ir.sequence'].next_by_code(
                    'kitchen.screen') or "New"
        return super().create(vals_list)
