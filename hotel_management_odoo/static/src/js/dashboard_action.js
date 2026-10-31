/** @odoo-module */
import { registry } from '@web/core/registry';
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, onMounted, proxy, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useChart } from "@web/core/utils/chart_hook";
import { HotelTapeChart } from "./tape_chart";

/**
 * POS-style in-card chart (same Chart.js look/interaction as
 * point_of_sale's kanban_dashboard_graph: hidden axes, fill,
 * hover tooltips). One canvas per dashboard card.
 */
export class PosCardChart extends Component {
    static template = "PosCardChart";
    props = useProps({
        values: t.array(Number),
        labels: t.array(String).optional([]),
        values2: t.array(Number).optional(),
        color: t.string().optional("#4371DB"),
        color2: t.string().optional("#f97316"),
        label: t.string().optional(""),
        label2: t.string().optional(""),
        kind: t.string().optional("line"),
    });

    setup() {
        this.chart = useChart(() => this._config());
    }

    _config() {
        const labels = (this.props.labels || []).map(String);
        const color = this.props.color || "#4371DB";
        const datasets = [{
            data: this.props.values || [],
            label: this.props.label || "",
            backgroundColor: this._alpha(color, 0.2),
            borderColor: color,
            pointBackgroundColor: color,
            pointBorderColor: "transparent",
            hoverBackgroundColor: color,
            fill: "start",
            borderWidth: 2,
            tension: 0.000001,
            cubicInterpolationMode: "monotone",
        }];
        if (this.props.values2) {
            const color2 = this.props.color2 || "#f97316";
            datasets.push({
                data: this.props.values2,
                label: this.props.label2 || "",
                backgroundColor: "transparent",
                borderColor: color2,
                pointBackgroundColor: "transparent",
                pointBorderColor: "transparent",
                hoverBackgroundColor: color2,
                fill: false,
                borderWidth: 1.5,
                borderDash: [4, 2],
                tension: 0.000001,
            });
        }
        return {
            type: this.props.kind === "bar" ? "bar" : "line",
            data: {
                labels,
                datasets: this.props.kind === "bar"
                    ? [{ data: this.props.values || [], label: this.props.label || "",
                        backgroundColor: this._alpha(color, 0.75) }]
                    : datasets,
            },
            options: {
                layout: { autoPadding: false },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        intersect: false,
                        mode: "index",
                        position: "average",
                        caretSize: 0,
                        usePointStyle: true,
                    },
                },
                scales: { y: { display: false }, x: { display: false } },
                maintainAspectRatio: false,
                interaction: { intersect: false, mode: "index" },
            },
        };
    }

    _alpha(hex, a) {
        const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
        if (!m) return hex;
        const n = parseInt(m[1], 16);
        return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
    }
}

const today = new Date();
const day = String(today.getDate()).padStart(2, '0');
const month = String(today.getMonth() + 1).padStart(2, '0');
const year = today.getFullYear();
const formattedDate = `${year}-${month}-${day}`;

export class CustomDashBoard extends Component {
    static components = { HotelTapeChart, PosCardChart };
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
        // ── Task 4: tiles (extend, do not replace) ──
        this.occupancy = '0%';
        this.adr = '0';
        this.revpar = '0';
        this.arrivals = 0;
        this.departures = 0;
        this.dirty = 0;
        // ── POS cards: drill state + 14-day sparkline series ──
        this.occupied = 0;
        this.sellable = 0;
        this.openFolios = 0;
        this.reservedCount = 0;
        this.oooCount = 0;
        this.roomRevenueToday = '0';
        this.ui = proxy({menu: null});
        this.seriesDates = [];
        this.seriesOccupancy = [];
        this.seriesRevpar = [];
        this.seriesArrivals = [];
        this.seriesDepartures = [];
        this.seriesAvailable = [];
        this.seriesRevenue = [];
        this.seriesFood = [];

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
            this.food_items = result['food_items'] || 0;
            this.food_order = result['food_order'] || 0;
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
        // ── Task 4: tiles (best-effort; dashboard stays up if endpoint missing) ──
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
                this.occupied = tiles['occupied'] || 0;
                this.sellable = tiles['sellable_rooms'] || 0;
                this.openFolios = tiles['open_folios'] || 0;
                this.reservedCount = tiles['reserved'] || 0;
                this.oooCount = tiles['ooo'] || 0;
                this.roomRevenueToday = sym
                    ? sym + ' ' + (tiles['room_revenue'] || 0)
                    : String(tiles['room_revenue'] || 0);
            }
        } catch (e) { /* tiles unavailable (module not upgraded?) — keep defaults */ }
        // ── POS sparklines (best-effort) ──
        try {
            const series = await this.orm.call(
                'hotel.daily.inventory', 'get_dashboard_series', [], {days: 14});
            if (series) {
                this.seriesDates = series['dates'] || [];
                this.seriesOccupancy = series['occupancy'] || [];
                this.seriesRevpar = series['revpar'] || [];
                this.seriesArrivals = series['arrivals'] || [];
                this.seriesDepartures = series['departures'] || [];
                this.seriesAvailable = series['available'] || [];
                this.seriesRevenue = series['room_revenue'] || [];
                this.seriesFood = series['food_orders'] || [];
            }
        } catch (e) { /* keep empty series — cards still render */ }
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

    // ── Task 4: tile drill-downs ──

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
                ['state', 'in', ['reserved', 'check_in', 'check_out', 'done']],
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
                ['state', 'in', ['check_in', 'check_out']],
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

    toggleMenu(e, name) {
        e.stopPropagation();
        e.preventDefault();
        this.ui.menu = this.ui.menu === name ? null : name;
    }

    spark(values) {
        const vals = (values || []).map(Number).filter((v) => !isNaN(v));
        if (!vals.length) return '';
        const w = 120, h = 36, pad = 3;
        const min = Math.min(...vals), max = Math.max(...vals);
        const span = (max - min) || 1;
        return vals.map((v, i) => {
            const x = vals.length === 1 ? w / 2
                : pad + (i * (w - 2 * pad)) / (vals.length - 1);
            const y = h - pad - ((v - min) / span) * (h - 2 * pad);
            return x.toFixed(1) + ',' + y.toFixed(1);
        }).join(' ');
    }

    _reportAction(e, opts) {
        e.stopPropagation();
        e.preventDefault();
        this.ui.menu = null;
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction(Object.assign({
            type: 'ir.actions.act_window',
            target: 'current',
        }, opts), options);
    }

    openBookingPivot(e) {
        this._reportAction(e, {
            name: _t("Reservations Analysis"),
            res_model: 'room.booking',
            view_mode: 'pivot',
            views: [[false, 'pivot']],
        });
    }

    openBookingGraph(e) {
        this._reportAction(e, {
            name: _t("Reservations Analysis"),
            res_model: 'room.booking',
            view_mode: 'graph',
            views: [[false, 'graph']],
        });
    }

    openLinePivot(e) {
        this._reportAction(e, {
            name: _t("Room Nights Analysis"),
            res_model: 'room.booking.line',
            view_mode: 'pivot',
            views: [[false, 'pivot']],
        });
    }

    openLineGraph(e) {
        this._reportAction(e, {
            name: _t("Room Nights Analysis"),
            res_model: 'room.booking.line',
            view_mode: 'graph',
            views: [[false, 'graph']],
        });
    }

    openFolioList(e) {
        this._reportAction(e, {
            name: _t("Open Folios"),
            res_model: 'hotel.folio',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: [['state', '=', 'open']],
        });
    }

    openFolioPivot(e) {
        this._reportAction(e, {
            name: _t("Folio Analysis"),
            res_model: 'hotel.folio',
            view_mode: 'pivot',
            views: [[false, 'pivot']],
        });
    }

    openFolioGraph(e) {
        this._reportAction(e, {
            name: _t("Folio Analysis"),
            res_model: 'hotel.folio',
            view_mode: 'graph',
            views: [[false, 'graph']],
        });
    }

    openTapeFull(e) {
        e.stopPropagation();
        e.preventDefault();
        var options = { on_reverse_breadcrum: this.on_reverse_breadcrum };
        this.action.doAction({
            type: 'ir.actions.client',
            tag: 'hotel_tape_chart',
            name: _t("Tape Chart"),
            target: 'current',
        }, options);
    }
}

CustomDashBoard.template = "CustomDashBoard";
registry.category("actions").add("custom_dashboard_tags", CustomDashBoard);