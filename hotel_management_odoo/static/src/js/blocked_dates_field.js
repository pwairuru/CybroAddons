/** @odoo-module */
import {
    DateTimeField,
    dateTimeField,
} from "@web/views/fields/datetime/datetime_field";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { onWillUpdateProps, proxy } from "@odoo/owl";

function _roomIdOf(value) {
    if (!value) {
        return false;
    }
    if (Array.isArray(value)) {
        return value[0] || false;
    }
    if (typeof value === "object") {
        return value.id || value.resId || false;
    }
    return value;
}

function _isoDay(value) {
    if (!value) {
        return false;
    }
    try {
        if (typeof value.toISODate === "function") {
            return value.toISODate();
        }
    } catch (_e) {
        return false;
    }
    if (typeof value === "string") {
        return value.slice(0, 10) || false;
    }
    return false;
}

export class HotelBlockedDatesField extends DateTimeField {
    setup() {
        // NOTE: DateTimeField.setup() builds the picker during
        // super.setup(), which reads our getPickerProps override
        // immediately — so reactive state must exist BEFORE super.
        this.blocked = proxy({ dates: [], ooo: false, dirty: false });
        super.setup();
        this.orm = useService("orm");
        // Reactive (proxy) so the picker props recompute when the RPC
        // lands: getPickerProps reads .dates during render, the mutation
        // below triggers a re-render, and the datetime-picker hook picks
        // up the new isDateValid/dayCellClass on its onWillRender.
        this._fetchToken = 0;
        this._lastKey = null;
        this._fetchBlocked();
        onWillUpdateProps(() => {
            this._fetchBlocked();
        });
    }

    get isCheckout() {
        return (
            this.props && this.props.name === "checkout_date"
        );
    }

    get checkinIso() {
        const rec = this.props.record;
        const raw = rec && rec.data ? rec.data.checkin_date : false;
        return _isoDay(raw);
    }

    _key() {
        return (
            this.roomId +
            "|" +
            this.ignoreBookingId +
            "|" +
            this.ignoreLineId +
            "|" +
            (this.isCheckout ? "out:" + (this.checkinIso || "-") : "in")
        );
    }

    get roomId() {
        const rec = this.props.record;
        const raw = rec && rec.data ? rec.data.room_id : false;
        return _roomIdOf(raw);
    }

    get ignoreBookingId() {
        const rec = this.props.record;
        const raw = rec && rec.data ? rec.data.booking_id : false;
        return _roomIdOf(raw);
    }

    get ignoreLineId() {
        const rec = this.props.record;
        if (!rec) {
            return false;
        }
        // Existing lines have a real resId; new editable-list rows do not.
        if (rec.resId && typeof rec.resId === "number") {
            return rec.resId;
        }
        return false;
    }

    async _fetchBlocked() {
        const key = this._key();
        if (key === this._lastKey && this._fetchToken > 0) {
            return;
        }
        this._lastKey = key;
        const token = ++this._fetchToken;
        const roomId = this.roomId;
        if (!roomId) {
            this.blocked.dates = [];
            this.blocked.ooo = false;
            this.blocked.dirty = false;
            return;
        }
        const today = new Date();
        const from = new Date(today);
        from.setDate(from.getDate() - 60);
        const to = new Date(today);
        to.setDate(to.getDate() + 180);
        const fmt = (d) => d.toISOString().slice(0, 10);
        try {
            const res = await this.orm.call(
                "hotel.daily.inventory",
                "get_blocked_dates",
                [roomId],
                {
                    date_from: fmt(from),
                    date_to: fmt(to),
                    ignore_booking_id: this.ignoreBookingId || false,
                    ignore_line_id: this.ignoreLineId || false,
                }
            );
            if (token !== this._fetchToken) {
                return;
            }
            this.blocked.dates = (res && res.blocked) || [];
            this.blocked.ooo = !!(res && res.ooo);
            this.blocked.dirty = !!(res && res.dirty);
        } catch (_e) {
            // Read-only UX helper: server stays the enforcement point.
            // On RPC failure leave every date selectable.
            if (token !== this._fetchToken) {
                return;
            }
            this.blocked.dates = [];
        }
    }

    _liveBlocked() {
        // NOTE: the picker's onWillRender skips prop updates whose
        // JSON form is unchanged — functions stringify to undefined,
        // so the FIRST closures stick. They must therefore read LIVE
        // state at call time, never a snapshot.
        const dates = (this.blocked && this.blocked.dates) || [];
        return new Set(dates);
    }

    _isBlockedIso(iso, blocked) {
        if (!iso) {
            return false;
        }
        // Check-in: a booked night cannot start a stay.
        if (!this.isCheckout) {
            return blocked.has(iso);
        }
        // Check-out: the stay [checkin, D) must hold no booked night.
        // Checkout exactly on another stay's check-in is same-day
        // turnover (no shared night) and stays selectable. Without a
        // check-in yet, stay permissive — the check-in picker and the
        // server enforce the range.
        const checkin = this.checkinIso;
        if (!checkin || iso <= checkin) {
            return !checkin ? false : true;
        }
        for (const night of blocked) {
            if (night >= checkin && night < iso) {
                return true;
            }
        }
        return false;
    }

    getPickerProps() {
        const props = super.getPickerProps();
        // Touch .dates here (during render) so the proxy still tracks
        // it, but the closures below ALWAYS read live state — the
        // picker keeps the first closures it sees.
        void ((this.blocked && this.blocked.dates) || []);
        void this.checkinIso;
        const self = this;
        return {
            ...props,
            isDateValid: (date) => {
                try {
                    return !self._isBlockedIso(
                        date.toISODate(), self._liveBlocked());
                } catch (_e) {
                    return true;
                }
            },
            dayCellClass: (date) => {
                try {
                    return self._isBlockedIso(
                        date.toISODate(), self._liveBlocked())
                        ? "o_hotel_blocked"
                        : "";
                } catch (_e) {
                    return "";
                }
            },
        };
    }
}

registry.category("fields").add("hotel_blocked_dates", {
    ...dateTimeField,
    component: HotelBlockedDatesField,
});
