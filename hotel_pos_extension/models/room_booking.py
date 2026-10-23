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
#############################################################################
from odoo import api, fields, models
        
class RoomBooking(models.Model):
    """Extend room booking to include POS order tracking."""
    _inherit = 'room.booking'

    pos_order_line_ids = fields.One2many('hotel.pos.line', 'booking_id', string='POS Orders')
    amount_total_pos = fields.Monetary(string="Total POS Amount", compute='_compute_amount_total_pos', store=False)
    amount_total_combined = fields.Monetary(
        string="Combined Total (Rooms + Services + POS)",
        compute='_compute_amount_total_combined', store=False,
        help="Room/food/service/fleet/event total plus settled POS orders. "
             "The stored Total stays room-and-services only.")

    @api.depends('pos_order_line_ids')
    def _compute_has_pos_orders(self):
        """Compute if booking has linked POS orders."""
        for rec in self:
            rec.has_pos_orders = bool(rec.pos_order_line_ids)

    @api.depends(
        'room_line_ids.price_subtotal', 'room_line_ids.price_tax', 'room_line_ids.price_total',
        'food_order_line_ids.price_subtotal', 'food_order_line_ids.price_tax', 'food_order_line_ids.price_total',
        'service_line_ids.price_subtotal', 'service_line_ids.price_tax', 'service_line_ids.price_total',
        'vehicle_line_ids.price_subtotal', 'vehicle_line_ids.price_tax', 'vehicle_line_ids.price_total',
        'event_line_ids.price_subtotal', 'event_line_ids.price_tax', 'event_line_ids.price_total',
        'pos_order_line_ids.pos_order_id.amount_total',
        'pos_order_line_ids.pos_order_id.currency_id',
        'pos_order_line_ids.pos_order_id.state',
    )
    def _calculate_amounts(self, flag=False):
        """Extended calculation to include POS charges and add to invoice list"""
        if hasattr(super(), '_calculate_amounts'):
            res = super()._calculate_amounts(flag=flag)
        else:
            res_list = []
            for rec in self:
                vals = {
                    'amount_untaxed': rec.amount_untaxed,
                    'amount_tax': rec.amount_tax,
                    'amount_total': rec.amount_total,
                }
                booking_list = []
                if flag:
                    # Parent exposes uninvoiced lines via _to_invoice_lines
                    # (pure totals live in _compute_amount_untaxed).
                    booking_list = rec._to_invoice_lines()
                res_list.append((vals, booking_list))
            res = res_list[0] if len(self) == 1 else res_list
        
        is_single = len(self) == 1
        res_list = [res] if is_single else res
        
        final_res = []
        for rec, (vals, booking_list) in zip(self, res_list):
            # Only settled POS orders count: draft/cancelled ghost links
            # (created at order-draft time) must not inflate totals.
            valid_pos_lines = rec.pos_order_line_ids.filtered(
                lambda l: l.state in ('paid', 'done', 'invoiced'))
            amount_total_pos = sum(valid_pos_lines.mapped('amount_total'))
            
            vals['amount_total_pos'] = amount_total_pos
            vals['amount_total'] += amount_total_pos
            vals['amount_untaxed'] += amount_total_pos 
            
            if flag:
                for line in valid_pos_lines:
                    for pos_line in line.pos_order_id.lines:
                        booking_list.append({
                            'name': f"POS: {pos_line.full_product_name or pos_line.product_id.name} (Ref: {line.pos_reference or ''})",
                            'quantity': pos_line.qty,
                            'price_unit': pos_line.price_unit,
                            'product_type': 'pos'
                        })
            final_res.append((vals, booking_list))
            
        return final_res[0] if is_single else final_res

    @api.depends('pos_order_line_ids.pos_order_id.amount_total',
                 'pos_order_line_ids.pos_order_id.state')
    def _compute_amount_total_pos(self):
        """Compute POS amount total from calculated values."""
        for record in self:
            vals, _ = record._calculate_amounts()
            record.amount_total_pos = vals.get('amount_total_pos', 0.0)

    @api.depends('amount_total', 'amount_total_pos')
    def _compute_amount_total_combined(self):
        for record in self:
            record.amount_total_combined = (
                (record.amount_total or 0.0)
                + (record.amount_total_pos or 0.0))

    def get_bill_summary_lines(self):
        """Returns a list of summary lines for the bill report:
        [
          {'ref': '', 'order_no': 'S00048', 'date': '...', 'total': 123.45},
          {'ref': '', 'order_no': 'New/0011', 'date': '...', 'total': 456.78},
        ]
        Matches the 1st image layout.
        """
        self.ensure_one()
        lines = []

        folio_total = sum(self.room_line_ids.mapped('price_total')) + \
                      sum(self.food_order_line_ids.mapped('price_total')) + \
                      sum(self.service_line_ids.mapped('price_total')) + \
                      sum(self.vehicle_line_ids.mapped('price_total')) + \
                      sum(self.event_line_ids.mapped('price_total'))
                      
        lines.append({
            'reference': self.name,
            'order_no': self.name,
            'date': self.date_order,
            'total': folio_total,
        })
        
        for pos_link in self.pos_order_line_ids.filtered(
                lambda l: l.state in ('paid', 'done', 'invoiced')):
            lines.append({
                'reference': pos_link.pos_order_id.name,
                'order_no': pos_link.pos_order_id.pos_reference,
                'date': pos_link.pos_order_id.date_order,
                'total': pos_link.pos_order_id.amount_total,
            })

        return lines

    def get_bill_summary_total(self):
        """Grand total matching get_bill_summary_lines (folio incl. tax
        plus settled POS). Used by the combined bill so its subtotal can
        never drift from the rows above it."""
        self.ensure_one()
        return sum(l['total'] for l in self.get_bill_summary_lines())

    def get_bill_grouped_lines(self):
        """Itemized bill groups for the printed bill:
        [{'label', 'rows': [{'description', 'detail', 'date', 'qty',
        'total'}], 'subtotal'}]. Only non-empty groups, in guest-facing
        order. POS rows carry the counter name so the guest can tell
        restaurant/bar charges apart from room and service charges.
        Group subtotals sum to get_bill_summary_total().
        """
        self.ensure_one()
        groups = []

        def _add(label, rows):
            rows = list(rows)
            if rows:
                groups.append({
                    'label': label,
                    'rows': rows,
                    'subtotal': sum(r['total'] for r in rows),
                })

        _add('Rooms', [{
            'description': l.room_id.display_name or l.room_id.name,
            'detail': '%d night(s)' % int(l.uom_qty),
            'date': l.checkin_date,
            'qty': l.uom_qty,
            'unit': l.price_unit,
            'total': l.price_total,
        } for l in self.room_line_ids])
        _add('Food', [{
            'description': l.food_id.display_name,
            'detail': '',
            'date': self.date_order,
            'qty': l.uom_qty,
            'unit': l.price_unit,
            'total': l.price_total,
        } for l in self.food_order_line_ids])
        _add('Services', [{
            'description': l.service_id.display_name,
            'detail': '',
            'date': self.date_order,
            'qty': l.uom_qty,
            'unit': l.price_unit,
            'total': l.price_total,
        } for l in self.service_line_ids])
        _add('Fleet', [{
            'description': l.fleet_id.display_name,
            'detail': '',
            'date': self.date_order,
            'qty': l.uom_qty,
            'unit': l.price_unit,
            'total': l.price_total,
        } for l in self.vehicle_line_ids])
        _add('Events', [{
            'description': l.event_id.display_name,
            'detail': '',
            'date': self.date_order,
            'qty': l.uom_qty,
            'unit': l.price_unit,
            'total': l.price_total,
        } for l in self.event_line_ids])

        pos_rows = []
        for link in self.pos_order_line_ids.filtered(
                lambda l: l.state in ('paid', 'done', 'invoiced')):
            order = link.pos_order_id
            session = order.session_id
            config = session.config_id if session else False
            counter = (config.name if config else False) \
                or (session.name if session else False) or 'POS'
            pos_rows.append({
                'description': order.pos_reference or order.name,
                'detail': counter,
                'date': order.date_order,
                'qty': 1,
                'unit': order.amount_total,
                'total': order.amount_total,
                'counter': counter,
            })
        _add('POS Orders', pos_rows)
        return groups

    pos_invoice_count = fields.Integer(compute='_compute_pos_invoice_count', string='POS Invoice Count')

    def _compute_pos_invoice_count(self):
        """Compute number of valid POS invoices linked to the record."""
        for rec in self:
            invoices = rec.pos_order_line_ids.mapped('pos_order_id.account_move')
            rec.pos_invoice_count = len(invoices.filtered(lambda x: x.state != 'cancel'))

    def action_view_pos_invoices(self):
        """Open POS invoices related to the record."""
        self.ensure_one()
        invoices = self.pos_order_line_ids.mapped('pos_order_id.account_move').filtered(lambda x: x.state != 'cancel')
        action = self.env["ir.actions.actions"]._for_xml_id("account.action_move_out_invoice_type")
        if len(invoices) > 1:
            action['domain'] = [('id', 'in', invoices.ids)]
        elif len(invoices) == 1:
            form_view = [(self.env.ref('account.view_move_form').id, 'form')]
            if 'views' in action:
                action['views'] = form_view + [(state,view) for state,view in action['views'] if view != 'form']
            else:
                action['views'] = form_view
            action['res_id'] = invoices.id
        else:
            action = {'type': 'ir.actions.act_window_close'}
        return action
