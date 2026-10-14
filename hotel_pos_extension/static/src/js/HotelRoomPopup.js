/** @odoo-module */

import { Component, proxy as useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class HotelRoomPopup extends Component {
    static template = "hotel_pos_extension.HotelRoomPopup";
    static components = { Dialog };

    setup() {
        // TEMP-DIAG-ROOM-POPUP (remove after diagnosis)
        console.log("HOTEL_POPUP_SETUP props keys:", Object.keys(this.props || {}));
        const bookings = (this.props && this.props.bookings) || [];
        this.state = useState({
            selectedBooking: bookings[0] || null,
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
