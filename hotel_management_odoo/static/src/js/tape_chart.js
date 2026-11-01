/** @odoo-module */
import { registry } from '@web/core/registry';
import { useService } from '@web/core/utils/hooks';
import { Component, onWillStart, proxy } from '@odoo/owl';

export class HotelTapeChart extends Component {
    setup() {
        this.orm = useService('orm');
        this.action = useService('action');
        this.state = proxy({ dates: [], rooms: [], segments: [],
            occupancy: {}, days: 14, dateFrom: false, loading: true, groupBy: 'floor' });
        onWillStart(this.load.bind(this));
    }
    async load() {
        this.state.loading = true;
        const data = await this.orm.call('hotel.daily.inventory', 'get_tape', [],
            { days: this.state.days, date_from: this.state.dateFrom || undefined });
        Object.assign(this.state, { dates: data.dates, rooms: data.rooms,
            segments: data.segments, occupancy: data.occupancy,
            dateFrom: data.date_from, loading: false });
    }
    colFor(date) { return this.state.dates.indexOf(date) + 2; }
    headFor(date) { const d = new Date(date + 'T00:00:00Z'); const DOW = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat']; const MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']; return { dow: DOW[d.getUTCDay()], day: d.getUTCDate(), mon: MON[d.getUTCMonth()] }; }
    spanFor(seg) {
        const from = this.state.dates.indexOf(seg.date_from);
        let to = this.state.dates.indexOf(seg.date_to);
        if (to < 0) { to = this.state.dates.length; }
        return Math.max(to - Math.max(from, 0), 1);
    }
    segsFor(roomId, date) {
        return (this.state.segments || []).filter((s) =>
            s.room_id === roomId && s.date_from <= date && date < s.date_to);
    }
    isBlocked(room, date) {
        if (!room || !date) { return true; }
        if (room.is_ooo || room.hk_status === 'ooo' || room.hk_status === 'dirty') { return true; }
        return this.segsFor(room.id, date).length > 0;
    }
    blockReason(room, date) {
        if (!room) { return 'No room'; }
        if (room.is_ooo || room.hk_status === 'ooo') { return 'Out of order — cannot book'; }
        if (room.hk_status === 'dirty') { return 'Dirty — clean first'; }
        const hits = this.segsFor(room.id, date);
        if (hits.length) {
            const s = hits[0];
            return 'Booked: ' + (s.guest_name || s.booking_name) + ' → checkout ' + s.date_to + ' (free for turnover)';
        }
        return 'New booking · Room ' + room.name + ' · ' + date;
    }
    emptyCls(room, date) {
        const dow = this.headFor(date).dow;
        let cls = 'o_ahb_empty' + ((dow === 'Sat' || dow === 'Sun') ? ' is-weekend' : '');
        if (this.isBlocked(room, date)) { cls += ' is-blocked'; }
        return cls;
    }
    clsFor(seg) {
        let base = seg.state === 'check_in'
            ? 'o_ahb_seg o_ahb_st_checked_in' : 'o_ahb_seg o_ahb_st_confirmed';
        const overlap = (this.state.segments || []).some((o) =>
            o.id !== seg.id && o.room_id === seg.room_id
            && o.date_from < seg.date_to && seg.date_from < o.date_to);
        if (overlap) { base += ' o_ahb_st_conflict'; }
        if (seg.is_arrival) { base += ' is-arrival'; }
        if (seg.is_departure) { base += ' is-departure'; }
        return base;
    }
    occTitle(date) {
        const o = this.state.occupancy ? this.state.occupancy[date] : false;
        if (!o) { return ''; }
        const reserved = (o.reserved !== undefined) ? ', ' + o.reserved + ' reserved' : '';
        return o.sold + '/' + o.sellable + ' in-house' + reserved;
    }
    async setDays(days) { this.state.days = days; await this.load(); }
    onDaysChange(e) { this.setDays(Number(e.target.value)); }
    setGroup(mode) { this.state.groupBy = mode; }
    groupedRows() {
        const mode = this.state.groupBy;
        const groups = new Map();
        for (const room of this.state.rooms) {
            const label = mode === 'floor'
                ? (room.floor_name || 'No Floor')
                : (room.room_type_label || room.room_type || 'No Type');
            if (!groups.has(label)) { groups.set(label, []); }
            groups.get(label).push(room);
        }
        let labels = [...groups.keys()];
        if (mode === 'room_type') { labels.sort((a, b) => a.localeCompare(b)); }
        else { labels = labels.filter((l) => l !== 'No Floor').concat(labels.filter((l) => l === 'No Floor')); }
        const rows = [];
        for (const label of labels) {
            rows.push({ type: 'group', label });
            const rooms = groups.get(label).slice()
                .sort((a, b) => (a.name || '').localeCompare(b.name || ''));
            for (const room of rooms) { rows.push({ type: 'room', room }); }
        }
        return rows;
    }
    async goToday() { this.state.dateFrom = false; await this.load(); }
    async shift(n) {
        const d = new Date(this.state.dateFrom + 'T00:00:00');
        d.setDate(d.getDate() + n * this.state.days);
        this.state.dateFrom = d.toISOString().slice(0, 10);
        await this.load();
    }
    openBooking(bookingId) {
        if (!bookingId) { return; }
        this.action.doAction({ type: 'ir.actions.act_window', name: 'Booking',
            res_model: 'room.booking', views: [[false, 'form']],
            res_id: bookingId, target: 'current' });
    }
    openNewBooking(roomId, date) {
        if (!roomId || !date) { return; }
        const room = (this.state.rooms || []).find((r) => r.id === roomId);
        if (room && this.isBlocked(room, date)) { return; }
        const ci = date + ' 14:00:00';
        const d = new Date(date + 'T00:00:00Z');
        d.setUTCDate(d.getUTCDate() + 1);
        const co = d.toISOString().slice(0, 10) + ' 12:00:00';
        this.action.doAction({ type: 'ir.actions.act_window', name: 'Booking',
            res_model: 'room.booking', views: [[false, 'form']],
            target: 'current',
            context: { default_checkin_date: ci, default_checkout_date: co,
                default_room_line_ids: [[0, 0, { room_id: roomId, checkin_date: ci, checkout_date: co }]] } });
    }
}
HotelTapeChart.template = 'HotelTapeChart';
registry.category('actions').add('hotel_tape_chart', HotelTapeChart);
