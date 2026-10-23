/** @odoo-module */
import { registry } from '@web/core/registry';
import { useService } from '@web/core/utils/hooks';
import { Component, onWillStart, proxy } from '@odoo/owl';

const MAX_DAYS = 42;

// UTC-only day math: local-midnight Date + toISOString() shifts the day
// back in UTC+X zones (e.g. UTC+3), so parse/format via Date.UTC throughout.
function _parseDay(s) {
    const [y, m, d] = s.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d));
}
function _fmtDay(d) {
    const p = (n) => String(n).padStart(2, '0');
    return d.getUTCFullYear() + '-' + p(d.getUTCMonth() + 1)
        + '-' + p(d.getUTCDate());
}
function _todayIso() {
    const now = new Date();
    return _fmtDay(new Date(Date.UTC(
        now.getFullYear(), now.getMonth(), now.getDate())));
}

export class HotelRateCalendar extends Component {
    setup() {
        this.orm = useService('orm');
        this.action = useService('action');
        this.state = proxy({
            dates: [], rows: [], plans: [], types: [],
            planId: false, board: 'RO',
            days: 14, dateFrom: false, loading: true,
            bulk: false, sel: false, bulkForm: {
                mode: 'percent', value: 0, priority: 10,
            },
            overlapWarning: false, notice: false,
        });
        onWillStart(this.load.bind(this));
    }
    async load() {
        this.state.loading = true;
        this.state.notice = false;
        const [plans, types] = await Promise.all([
            this.orm.searchRead('hotel.rate.plan', [], ['id', 'name']),
            this.orm.searchRead('hotel.room.type', [], ['id', 'name']),
        ]);
        this.state.plans = plans;
        this.state.types = types;
        if (!this.state.planId && plans.length) {
            this.state.planId = plans[0].id;
        }
        await this.reload();
        this.state.loading = false;
    }
    _window() {
        const from = this.state.dateFrom || _todayIso();
        const start = _parseDay(from);
        const days = Math.min(Math.max(this.state.days, 1), MAX_DAYS);
        const end = new Date(start);
        end.setUTCDate(end.getUTCDate() + days - 1);
        return { from: _fmtDay(start), to: _fmtDay(end) };
    }
    async reload() {
        const { from, to } = this._window();
        const typeIds = this.state.types.map((t) => t.id);
        const data = await this.orm.call('hotel.rate.engine', 'matrix',
            [typeIds, from, to, this.state.planId || false, this.state.board]);
        Object.assign(this.state, {
            dates: data.dates, rows: data.rows,
            dateFrom: data.dates.length ? data.dates[0] : from,
            sel: false, overlapWarning: false,
        });
    }
    colFor(date) { return this.state.dates.indexOf(date) + 2; }
    headFor(date) {
        const d = new Date(date + 'T00:00:00Z');
        const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
            'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        return { dow: DOW[d.getUTCDay()], day: d.getUTCDate(),
            mon: MON[d.getUTCMonth()] };
    }
    clsFor(cell) {
        if (cell.closed || this._past(cell.date)) { return 'o_rc_cell o_rc_closed'; }
        if (cell.available <= 0) { return 'o_rc_cell o_rc_soldout'; }
        if (cell.delta_pct > 0) { return 'o_rc_cell o_rc_up'; }
        if (cell.delta_pct < 0) { return 'o_rc_cell o_rc_down'; }
        return 'o_rc_cell o_rc_flat';
    }
    tipFor(row, cell) {
        const why = cell.rule_id
            ? 'rule #' + cell.rule_id
            : 'base rate (no rule)';
        return row.name + ' · ' + cell.date
            + '\nprice ' + cell.price + ' (base ' + cell.base + ')'
            + '\n' + why + ' · min stay ' + cell.min_stay
            + ' · ' + cell.available + ' free'
            + (cell.board ? '\nboard +' + cell.board + ' = ' + cell.total : '')
            + (cell.closed ? '\nCLOSED' : '');
    }
    _past(date) { return date < _todayIso(); }
    _locked(cell) { return !cell || cell.closed || this._past(cell.date); }
    inSel(rowId, date) {
        const sel = this.state.sel;
        return !!(sel && sel.typeId === rowId
            && sel.from <= date && date <= sel.to);
    }
    async onCell(row, cell) {
        if (this.state.bulk) {
            this.pickRange(row, cell);
            return;
        }
        if (this._locked(cell)) { return; }
        if (cell.rule_id) {
            this.action.doAction({
                type: 'ir.actions.act_window', name: 'Rate Rule',
                res_model: 'hotel.rate.rule', res_id: cell.rule_id,
                views: [[false, 'form']], target: 'current',
            });
        } else {
            this.action.doAction({
                type: 'ir.actions.act_window', name: 'Rate Rule',
                res_model: 'hotel.rate.rule', views: [[false, 'form']],
                target: 'current',
                context: {
                    default_plan_id: this.state.planId,
                    default_room_type_id: row.type_id,
                    default_date_from: cell.date,
                    default_date_to: cell.date,
                },
            });
        }
    }
    pickRange(row, cell) {
        if (this._locked(cell)) { return; }
        const sel = this.state.sel;
        if (!sel || sel.typeId !== row.type_id) {
            this.state.sel = {
                typeId: row.type_id, from: cell.date, to: cell.date,
            };
        } else if (cell.date < sel.from) {
            sel.from = cell.date;
        } else {
            sel.to = cell.date;
        }
        this.checkOverlap();
    }
    async checkOverlap() {
        const sel = this.state.sel;
        if (!sel) {
            this.state.overlapWarning = false;
            return;
        }
        const hits = await this.orm.searchRead('hotel.rate.rule', [
            ['plan_id', '=', this.state.planId],
            ['room_type_id', '=', sel.typeId],
            ['priority', '=', this.state.bulkForm.priority],
            ['date_from', '<=', sel.to],
            ['date_to', '>=', sel.from],
        ], ['id', 'rate_type', 'fixed_price', 'adjustment_pct']);
        const mode = this.state.bulkForm.mode === 'fixed'
            ? 'fixed' : 'percent';
        const val = Number(this.state.bulkForm.value) || 0;
        this.state.overlapWarning = hits.some((h) => mode === 'fixed'
            ? h.rate_type !== 'fixed' || (h.fixed_price || 0) !== val
            : h.rate_type !== 'percent' || (h.adjustment_pct || 0) !== val);
    }
    async applyBulk() {
        const sel = this.state.sel;
        if (!sel || !this.state.planId) { return; }
        await this.checkOverlap();
        await this.orm.create('hotel.rate.rule', [{
            plan_id: this.state.planId,
            room_type_id: sel.typeId,
            date_from: sel.from,
            date_to: sel.to,
            rate_type: this.state.bulkForm.mode,
            fixed_price: this.state.bulkForm.mode === 'fixed'
                ? Number(this.state.bulkForm.value) || 0 : 0,
            adjustment_pct: this.state.bulkForm.mode === 'fixed'
                ? 0 : Number(this.state.bulkForm.value) || 0,
            priority: this.state.bulkForm.priority,
        }]);
        this.state.notice = 'Rule applied ' + sel.from + ' → ' + sel.to;
        await this.reload();
    }
    async setDays(days) { this.state.days = days; await this.reload(); }
    onDaysChange(e) { this.setDays(Number(e.target.value)); }
    async onPlanChange(e) {
        this.state.planId = Number(e.target.value) || false;
        await this.reload();
    }
    async onBoardChange(e) {
        this.state.board = e.target.value;
        await this.reload();
    }
    onBulkField(e, field) {
        // t-model cannot bind nested proxy paths (bulkForm.mode), so use
        // value + change handler like the plan/board selects above.
        const raw = e.target.value;
        this.state.bulkForm[field] = field === 'mode'
            ? raw : Number(raw) || 0;
        this.checkOverlap();
    }
    toggleBulk() {
        this.state.bulk = !this.state.bulk;
        this.state.sel = false;
        this.state.overlapWarning = false;
    }
    async goToday() { this.state.dateFrom = false; await this.reload(); }
    async shift(n) {
        const base = this.state.dateFrom || _todayIso();
        const d = _parseDay(base);
        d.setUTCDate(d.getUTCDate() + n * this.state.days);
        this.state.dateFrom = _fmtDay(d);
        await this.reload();
    }
}
HotelRateCalendar.template = 'HotelRateCalendar';
registry.category('actions').add('hotel_rate_calendar', HotelRateCalendar);
