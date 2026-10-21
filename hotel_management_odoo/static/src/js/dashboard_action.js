/** @odoo-module */
import { registry } from '@web/core/registry';
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";

const today = new Date();
const day = String(today.getDate()).padStart(2, '0');
const month = String(today.getMonth() + 1).padStart(2, '0');
const year = today.getFullYear();
const formattedDate = `${year}-${month}-${day}`;

export class CustomDashBoard extends Component {
    /**
     * Setup method to initialize required services and register event handlers.
     */
    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        
        this.total_room = 0;
        this.available_room = 0;
        this.staff = 0;
        this.check_in = 0;
        this.reservation = 0;
        this.check_out = 0;
        this.total_vehicle = 0;
        this.available_vehicle = 0;
        this.total_event = 0;
        this.today_events = 0;
        this.pending_events = 0;
        this.food_items = 0;
        this.food_order = 0;
        this.total_revenue = '$ 0';
        this.today_revenue = '$ 0';
        this.pending_payment = '$ 0';
        // ── Task 4: rack + tiles (extend, do not replace) ──
        this.occupancy = '0%';
        this.adr = '0';
        this.revpar = '0';
        this.arrivals = 0;
        this.departures = 0;
        this.dirty = 0;
        this.rackDates = [];
        this.rackRows = [];

        onWillStart(this.onWillStart.bind(this));
        onMounted(this.onMounted.bind(this));
    }

    async onWillStart() {
        await this.fetch_data();
    }

    async onMounted() {
        // Reserved for post-render logic
    }

    async fetch_data() {
        const result = await this.orm.call('room.booking', 'get_details', []);
        if (result) {
            this.total_room = result['total_room'];
            this.available_room = result['available_room'];
            this.staff = result['staff'];
            this.check_in = result['check_in'];
            this.reservation = result['reservation'];
            this.check_out = result['check_out'];
            this.total_vehicle = result['total_vehicle'];
            this.available_vehicle = result['available_vehicle'];
            this.total_event = result['total_event'];
            this.today_events = result['today_events'];
            this.pending_events = result['pending_events'];
            this.food_items = result['food_items'];
            this.food_order = result['food_order'];
            if (result['currency_position'] === 'before') {
                this.total_revenue = result['currency_symbol'] + ' ' + result['total_revenue'];
                this.today_revenue = result['currency_symbol'] + ' ' + result['today_revenue'];
                this.pending_payment = result['currency_symbol'] + ' ' + result['pending_payment'];
            } else {
                this.total_revenue = result['total_revenue'] + ' ' + result['currency_symbol'];
                this.today_revenue = result['today_revenue'] + ' ' + result['currency_symbol'];
                this.pending_payment = result['pending_payment'] + ' ' + result['currency_symbol'];
            }
        }
        // ── Task 4: tiles + rack (best-effort; dashboard stays up if endpoint missing) ──
        try {
            const tiles = await this.orm.call('hotel.daily.inventory', 'get_tiles', []);
            if (tiles) {
                this.occupancy = tiles['occupancy'] + '%';
                const sym = tiles['currency_symbol'] || '';
                this.adr = sym ? sym + ' ' + tiles['adr'] : String(tiles['adr']);
                this.revpar = sym ? sym + ' ' + tiles['revpar'] : String(tiles['revpar']);
                this.arrivals = tiles['arrivals'];
                this.departures = tiles['departures'];
                this.dirty = tiles['dirty'];
            }
        } catch (e) { /* tiles unavailable (module not upgraded?) — keep defaults */ }
        try {
            const rack = await this.orm.call('hotel.daily.inventory', 'get_rack', []);
            if (rack && rack['cells']) {
                const dates = [];
                const seen = new Set();
                for (const c of rack['cells']) {
                    if (!seen.has(c['date'])) { seen.add(c['date']); dates.push(c['date']); }
                }
                dates.sort();
                this.rackDates = dates;
                // Group by room_id (stable); room_name is display-only.
                const byRoom = {};
                for (const c of rack['cells']) {
                    const key = c['room_id'];
                    (byRoom[key] = byRoom[key] || []).push(c);
                }
                this.rackRows = Object.keys(byRoom).map(Number).sort((a, b) => a - b).map((id) => ({
                    room_id: id,
                    room_name: (byRoom[id][0] && byRoom[id][0]['room_name']) || ('#' + id),
                    cells: dates.map((d) => {
                        const cell = byRoom[id].find((c) => c['date'] === d) || {};
                        return {
                            testid: 'rack-cell-' + id + '-' + d,
                            display: cell['display'] || 'Available',
                            cls: 'rack-cell rack-status-' + (cell['status'] || 'available'),
                            booking_id: cell['booking_id'] || false,
                        };
                    }),
                }));
            }
        } catch (e) { /* rack unavailable — keep empty */ }
    }

    // ── Navigation handlers ──

    total_rooms(e) {
        e.stopPropagation();
        e.preventDefault();
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction({
            name: _t("Rooms"),
            type: 'ir.actions.act_window',
            res_model: 'product.template',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: [['is_room', '=', true]],
            target: 'current',
        }, options);
    }

    check_ins(e) {
        e.stopPropagation();
        e.preventDefault();
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction({
            name: _t("Check-In"),
            type: 'ir.actions.act_window',
            res_model: 'room.booking',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: [['state', '=', 'check_in']],
            target: 'current',
        }, options);
    }

    check_outs(e) {
        e.stopPropagation();
        e.preventDefault();
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction({
            name: _t("Today's Check-Out"),
            type: 'ir.actions.act_window',
            res_model: 'room.booking',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: [
                ['room_line_ids.checkout_date', '>=', formattedDate + ' 00:00:00'],
                ['room_line_ids.checkout_date', '<=', formattedDate + ' 23:59:59'],
            ],
            target: 'current',
        }, options);
    }

    available_rooms(e) {
        e.stopPropagation();
        e.preventDefault();
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction({
            name: _t("Available Rooms"),
            type: 'ir.actions.act_window',
            res_model: 'product.template',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: [['is_room', '=', true], ['status', '=', 'available']],
            target: 'current',
        }, options);
    }

    reservations(e) {
        e.stopPropagation();
        e.preventDefault();
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction({
            name: _t("Total Reservations"),
            type: 'ir.actions.act_window',
            res_model: 'room.booking',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: [['state', '=', 'reserved']],
            target: 'current',
        }, options);
    }

    fetch_total_staff(e) {
        e.stopPropagation();
        e.preventDefault();
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction({
            name: _t("Total Staff"),
            type: 'ir.actions.act_window',
            res_model: 'res.users',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: [['group_ids.name', 'in', [
                'Admin',
                'Cleaning Team User',
                'Cleaning Team Head',
                'Maintenance Team User',
                'Maintenance Team Leader',
            ]]],
            target: 'current',
        }, options);
    }

    fetch_total_vehicle(e) {
        e.stopPropagation();
        e.preventDefault();
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction({
            name: _t("Total Vehicles"),
            type: 'ir.actions.act_window',
            res_model: 'fleet.vehicle.model',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            target: 'current',
        }, options);
    }

    async fetch_available_vehicle(e) {
        const result = await this.orm.call('fleet.booking.line', 'search_available_vehicle', [{}], {});
        e.stopPropagation();
        e.preventDefault();
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction({
            name: _t("Available Vehicle"),
            type: 'ir.actions.act_window',
            res_model: 'fleet.vehicle.model',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: [['id', 'not in', result]],
            target: 'current',
        }, options);
    }

    view_total_events(e) {
        e.stopPropagation();
        e.preventDefault();
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction({
            name: _t("Total Events"),
            type: 'ir.actions.act_window',
            res_model: 'event.event',
            view_mode: 'kanban,list,form',
            views: [[false, 'kanban'], [false, 'list'], [false, 'form']],
            domain: [],
            target: 'current',
        }, options);
    }

    fetch_today_events(e) {
        e.stopPropagation();
        e.preventDefault();
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction({
            name: _t("Today's Events"),
            type: 'ir.actions.act_window',
            res_model: 'event.event',
            view_mode: 'kanban,list,form',
            views: [[false, 'kanban'], [false, 'list'], [false, 'form']],
            domain: [
                ['date_end', '>=', formattedDate + ' 00:00:00'],
                ['date_end', '<=', formattedDate + ' 23:59:59'],
            ],
            target: 'current',
        }, options);
    }

    fetch_pending_events(e) {
        e.stopPropagation();
        e.preventDefault();
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction({
            name: _t("Pending Events"),
            type: 'ir.actions.act_window',
            res_model: 'event.event',
            view_mode: 'kanban,list,form',
            views: [[false, 'kanban'], [false, 'list'], [false, 'form']],
            domain: [['date_end', '>=', formattedDate]],
            target: 'current',
        }, options);
    }

    fetch_food_item(e) {
        e.stopPropagation();
        e.preventDefault();
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction({
            name: _t("Food Items"),
            type: 'ir.actions.act_window',
            res_model: 'lunch.product',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: [],
            target: 'current',
        }, options);
    }

    async fetch_food_order(e) {
        const result = await this.orm.call('food.booking.line', 'search_food_orders', [{}], {});
        e.stopPropagation();
        e.preventDefault();
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction({
            name: _t("Food Orders"),
            type: 'ir.actions.act_window',
            res_model: 'food.booking.line',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: [['id', 'in', result]],
            target: 'current',
        }, options);
    }

    // ── Task 4: tile + rack drill-downs ──

    _tileAction(e, opts) {
        e.stopPropagation();
        e.preventDefault();
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction(Object.assign({
            type: 'ir.actions.act_window',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            target: 'current',
        }, opts), options);
    }

    openOccupancy(e) {
        this._tileAction(e, {
            name: _t("In-House Rooms"),
            res_model: 'room.booking',
            domain: [['state', '=', 'check_in']],
        });
    }

    openArrivals(e) {
        this._tileAction(e, {
            name: _t("Today's Arrivals"),
            res_model: 'room.booking',
            domain: [
                ['room_line_ids.checkin_date', '>=', formattedDate + ' 00:00:00'],
                ['room_line_ids.checkin_date', '<=', formattedDate + ' 23:59:59'],
            ],
        });
    }

    openDepartures(e) {
        this._tileAction(e, {
            name: _t("Today's Departures"),
            res_model: 'room.booking',
            domain: [
                ['room_line_ids.checkout_date', '>=', formattedDate + ' 00:00:00'],
                ['room_line_ids.checkout_date', '<=', formattedDate + ' 23:59:59'],
                ['state', '=', 'check_in'],
            ],
        });
    }

    openDirty(e) {
        this._tileAction(e, {
            name: _t("Dirty Rooms"),
            res_model: 'cleaning.request',
            domain: [['cleaning_type', '=', 'room'], ['state', '!=', 'done']],
        });
    }

    openRackCell(e, booking_id) {
        if (!booking_id) {
            return;
        }
        e.stopPropagation();
        e.preventDefault();
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction({
            name: _t("Booking"),
            type: 'ir.actions.act_window',
            res_model: 'room.booking',
            view_mode: 'form',
            views: [[false, 'form']],
            res_id: booking_id,
            target: 'current',
        }, options);
    }
}

CustomDashBoard.template = "CustomDashBoard";
registry.category("actions").add("custom_dashboard_tags", CustomDashBoard);