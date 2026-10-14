/** @odoo-module */

import { Component, useProps, proxy, t } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class HotelRoomPopup extends Component {
    static template = "hotel_pos_extension.HotelRoomPopup";
    static components = { Dialog };
    // 20.0 port: declare props like core SelectionPopup (undeclared props
    // do not reach the component), and use proxy directly as core does.
    props = useProps({
        title: t.string().optional(""),
        bookings: t.array().optional([]),
        getPayload: t.function(),
        close: t.function(),
    });

    setup() {
        this.state = proxy({
            selectedBooking: this.props.bookings[0] || null,
        });
    }

    onBookingChange(ev) {
        const bookingId = parseInt(ev.target.value);
        this.state.selectedBooking = this.props.bookings.find(b => b.id === bookingId);
    }

    confirm() {
        this.props.getPayload(this.state.selectedBooking);
        this.props.close();
    }

    cancel() {
        this.props.close();
    }
}
