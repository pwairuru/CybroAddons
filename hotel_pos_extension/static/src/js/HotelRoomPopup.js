/** @odoo-module */

import { Component, useProps, proxy, t } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { Input } from "@point_of_sale/app/components/inputs/input/input";
import { useService } from "@web/core/utils/hooks";

export class HotelRoomPopup extends Component {
    static template = "hotel_pos_extension.HotelRoomPopup";
    static components = { Dialog, Input };
    // Props mirror core PartnerList (undeclared props do not reach
    // the component), bookings are plain searchRead rows.
    props = useProps({
        title: t.string().optional(""),
        bookings: t.array().optional([]),
        getPayload: t.function(),
        close: t.function(),
    });

    setup() {
        this.ui = useService("ui");
        this.state = proxy({
            query: "",
            selectedBooking: this.props.bookings[0] || null,
        });
    }

    get filteredBookings() {
        const q = (this.state.query || "").trim().toLowerCase();
        if (!q) {
            return this.props.bookings;
        }
        return this.props.bookings.filter((b) => {
            const room = (b.room_label || "").toLowerCase();
            const ref = (b.name || "").toLowerCase();
            const customer = Array.isArray(b.partner_id)
                ? (b.partner_id[1] || "").toLowerCase()
                : "";
            return room.includes(q) || ref.includes(q) || customer.includes(q);
        });
    }

    // Privacy: cashier screen shows the guest's first name only,
    // never the full customer name.
    firstName(booking) {
        const full = Array.isArray(booking.partner_id)
            ? (booking.partner_id[1] || "")
            : "";
        return (full.trim().split(/\s+/)[0] || "");
    }

    roomLabel(booking) {
        return booking.room_label || booking.name || "";
    }

    clickBooking(booking) {
        this.state.selectedBooking = booking;
    }

    confirm() {
        this.props.getPayload(this.state.selectedBooking);
        this.props.close();
    }

    cancel() {
        this.props.close();
    }
}
