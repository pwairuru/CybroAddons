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

import logging

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    """Extend POS order to link with hotel bookings."""
    _inherit = 'pos.order'

    booking_id = fields.Many2one('room.booking', string='Hotel Booking', help='Hotel booking associated with this POS order.')
    hotel_pos_status = fields.Selection([
        ('draft', 'New'),
        ('cancel', 'Cancelled'),
        ('paid', 'Paid'),
        ('done', 'Posted'),
        ('invoiced', 'Posted'),
    ], string='Status', compute='_compute_hotel_pos_status')

    @api.depends('state', 'account_move.payment_state')
    def _compute_hotel_pos_status(self):
        """Compute hotel POS order status."""
        for order in self:
            if order.state == 'invoiced' and order.account_move:
                if order.account_move.payment_state == 'paid':
                    order.hotel_pos_status = 'paid'
                else:
                    order.hotel_pos_status = 'invoiced'
            else:
                order.hotel_pos_status = order.state


    def _is_fully_hotel_charge(self):
        self.ensure_one()
        pays = self.payment_ids.filtered(lambda p: not p.is_change)
        if pays:
            return all(
                p.payment_method_id.is_hotel_charge for p in pays)
        # Zero-total room orders validate with no payment lines: core
        # strips zero-amount payments before sync, so booking linkage
        # is the hotel intent. Treat them as fully hotel-charged so the
        # folio stays the sole bill and the order posts/links like paid.
        if self.booking_id and self.currency_id.is_zero(self.amount_total or 0.0):
            return True
        return False

    def _ensure_hotel_invoice_flag(self):
        """Folio is the sole bill for fully room-charged orders.

        Early write-path hint (to_invoice=False) only when every
        payment is a hotel-charge and the order is booking-linked.
        Split tenders keep normal POS invoicing and are never
        auto-posted (allocation ambiguous) — see
        _post_hotel_folio_lines. The deterministic enforcement lives
        in _generate_order_invoice (order-sync races this flag).
        """
        for order in self:
            if order.booking_id and order._is_fully_hotel_charge():
                if order.to_invoice:
                    order.with_context(
                        skip_hotel_invoice_flag=True).write(
                            {'to_invoice': False})

    def _ensure_hotel_pos_line(self):
        """Ensure the booking shows the POS order under the 'POS Orders' tab.

        The POS can create an order as draft first and later update/validate it (same uuid),
        adding the hotel-charge payment method afterwards. In that flow, relying only on
        `create()` is not enough.
        """
        HotelPosLine = self.env['hotel.pos.line']
        for order in self:
            if not order.booking_id:
                continue

            link = HotelPosLine.search([('pos_order_id', '=', order.id)], limit=1)
            if link:
                if link.booking_id != order.booking_id:
                    link.booking_id = order.booking_id.id
                continue

            HotelPosLine.create({
                'booking_id': order.booking_id.id,
                'pos_order_id': order.id,
            })

    @api.model
    def _order_fields(self, ui_order):
        """Add booking_id to the order fields"""
        res = super()._order_fields(ui_order)
        res['booking_id'] = ui_order.get('booking_id', False)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        """Create Hotel POS Line if the order is charged to a room"""
        orders = super().create(vals_list)
        orders._ensure_hotel_pos_line()
        orders._ensure_hotel_invoice_flag()
        return orders

    def write(self, vals):
        """Update POS order and ensure booking linkage."""
        res = super().write(vals)
        self._ensure_hotel_pos_line()
        if not self.env.context.get('skip_hotel_invoice_flag'):
            self._ensure_hotel_invoice_flag()
        return res

    @api.model
    def _process_order(self, order, existing_order):
        """Ensure booking linkage survives the POS sync lifecycle.

        In Odoo 19, POS orders can be created/updated in multiple passes. We
        re-apply booking_id after super() and then ensure the hotel POS link.
        """
        booking_id = order.get('booking_id')
        order_id = super()._process_order(order, existing_order)
        pos_order = self.browse(order_id)
        if booking_id and pos_order.booking_id.id != booking_id:
            pos_order.write({'booking_id': booking_id})
        pos_order._ensure_hotel_pos_line()
        return order_id

    def _post_hotel_folio_lines(self):
        """Post this order's lines to the booking folio as source='pos'.

        Returns the created hotel.folio.line recordset (empty when
        nothing to post). Skips orders without a booking, bookings
        outside reserved/check_in, and orders with no hotel-charge
        payment. Per-line dedup on (folio, pos_order_id, product_id)
        makes re-runs idempotent.
        """
        self.ensure_one()
        FolioLine = self.env['hotel.folio.line']
        if not self.booking_id:
            return FolioLine.browse()
        if self.booking_id.state not in ('reserved', 'check_in'):
            return FolioLine.browse()
        pays = self.payment_ids
        if not self._is_fully_hotel_charge():
            if self.booking_id and pays and any(
                    p.payment_method_id.is_hotel_charge for p in pays):
                self.booking_id.message_post(
                    body="POS %s has split tender (part room-charge); "
                         "nothing auto-posted — split the ticket or "
                         "charge the room part manually."
                    % (self.pos_reference or self.name))
            return FolioLine.browse()
        folio = self.booking_id._ensure_folio()
        posted = FolioLine.browse()
        for line in self.lines:
            existing = FolioLine.search([
                ('folio_id', '=', folio.id),
                ('pos_order_id', '=', self.id),
                ('product_id', '=', line.product_id.id),
            ], limit=1)
            if existing:
                continue
            newline = self.env['hotel.charge.service'].post_charge(
                folio.id, line.product_id.id, line.qty, line.price_unit,
                'to_guest', hotel_date=fields.Date.today(),
                source='pos', pos_order_id=self.id)
            if line.tax_ids:
                newline.write(
                    {'tax_ids': [(6, 0, line.tax_ids.ids)]})
            posted |= newline
        if posted:
            folio.message_post(
                body="POS %s posted: %d line(s)."
                % (self.pos_reference or self.name, len(posted)))
        return posted

    def _generate_order_invoice(self):
        """Folio is the sole bill for fully room-charged orders.

        Deterministic suppression (the write-path flag in
        _ensure_hotel_invoice_flag races order-sync: the invoice was
        already generated before the flag flipped). Fully
        hotel-charged + booking-linked orders never get an outlet
        invoice — the folio invoice carries these lines, so a POSS
        invoice would bill the guest twice. Split tenders keep
        normal invoicing. NOTE: the hotel-charge method is
        pay_later-typed so standard forces to_invoice=True; skipping
        super() is the only reliable suppression.
        """
        hotel_only = self.filtered(
            lambda o: o.booking_id and o._is_fully_hotel_charge())
        if hotel_only:
            hotel_only.write({'to_invoice': False})
        rest = self - hotel_only
        if not rest:
            return True
        return super(PosOrder, rest)._generate_order_invoice()

    def action_pos_order_paid(self):
        """Pay the order, then post hotel-charge lines to the folio.

        One bad order never blocks the others: per-order poster
        failures are logged and swallowed (no new exceptions).
        """
        res = super().action_pos_order_paid()
        for order in self:
            try:
                order._post_hotel_folio_lines()
            except Exception:
                _logger.exception(
                    "Hotel folio posting failed for POS order %s",
                    order.name)
        return res

    def _generate_pos_order_invoice(self):
        """Override to forcefully keep the invoice 'Not Paid' for hotel charges.
        We use a context flag that is caught by our AccountMoveLine.reconcile override.
        Hotel links are stamped so the booking's Invoices / Payments /
        Bar-Restaurant buttons stay complete for these outlet bills
        (split tender or any other path that still generates one).
        """
        is_hotel_charge = any(p.payment_method_id.is_hotel_charge for p in self.payment_ids)
        if is_hotel_charge:
            move = super(PosOrder, self.with_context(skip_pos_invoice_reconciliation=True))._generate_pos_order_invoice()

            move.line_ids.sudo().remove_move_reconcile()

            for payment in self.payment_ids:
                if payment.account_move_id:
                    payment.account_move_id.line_ids.sudo().remove_move_reconcile()

            self.env['account.partial.reconcile'].sudo().search([
                '|', ('debit_move_id', 'in', move.line_ids.ids),
                ('credit_move_id', 'in', move.line_ids.ids)
            ]).unlink()

            move.sudo()._compute_amount()
            move._compute_payment_state()
            self._stamp_hotel_invoice_links(move)
            return move

        return super()._generate_pos_order_invoice()

    def _stamp_hotel_invoice_links(self, move):
        """Stamp booking/folio on a hotel-charge outlet invoice.

        Lets the booking pick the invoice (and its payments, via the
        payment backfill) up in its Invoices / Payments totals.
        """
        self.ensure_one()
        if not move or not self.booking_id:
            return
        vals = {'hotel_booking_id': self.booking_id.id}
        folio = self.env['hotel.folio'].search([
            ('booking_id', '=', self.booking_id.id),
            ('state', '=', 'open'),
        ], limit=1)
        if folio:
            vals['hotel_folio_id'] = folio.id
        move.write(vals)

    def _reconcile_invoice_payments(self, invoice, payment_moves):
        """Secondary layer to skip reconciliation for hotel room charges in Odoo 19."""
        is_hotel_charge = any(p.payment_method_id.is_hotel_charge for p in self.payment_ids)
        if self.env.context.get('skip_pos_invoice_reconciliation') or is_hotel_charge:
            return

        return super()._reconcile_invoice_payments(invoice, payment_moves)

class AccountMove(models.Model):
    """Customize payment status for hotel POS invoices."""
    _inherit = 'account.move'

    @api.depends('payment_state', 'state', 'is_move_sent', 'pos_order_ids')
    def _compute_status_in_payment(self):
        """Override to show 'Not Paid' for hotel POS invoices even if they are sent.
        
        This aligns with the hotel workflow where POS charges are only settled at checkout.
        """
        super()._compute_status_in_payment()
        for move in self:
            if move.state == 'posted' and move.payment_state == 'not_paid':
                if move.pos_order_ids.filtered(lambda o: any(p.payment_method_id.is_hotel_charge for p in o.payment_ids)):
                    move.status_in_payment = 'not_paid'
