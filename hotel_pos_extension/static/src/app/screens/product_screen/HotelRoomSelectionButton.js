/** @odoo-module */

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { patch } from "@web/core/utils/patch";
import { HotelRoomPopup } from "@hotel_pos_extension/js/HotelRoomPopup";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";

patch(ProductScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.orm = useService("orm");
        this.ui = useService("ui");
    },

    get currentBookingName() {
        // 20.0 port: return the plain room name only. The "Add Room"
        // fallback lives as static text in the template: a lazy _t()
        // string here races translations loading and renders empty.
        const order = this.pos.getOrder();
        return order?.uiState?.roomName || "";
    },

    async onClickAddRoom() {
        const bookings = await this.orm.searchRead("room.booking",
            [["state", "=", "check_in"]],
            ["id", "name", "partner_id"]
        );

        if (bookings.length === 0) {
            this.env.services.notification.add(_t("No active hotel bookings found."), { type: 'warning' });
            return;
        }

        const selectedBooking = await makeAwaitable(this.dialog, HotelRoomPopup, {
            title: _t("Room Information"),
            bookings: bookings,
        });

        if (selectedBooking) {
            const order = this.pos.getOrder();
            order?.setBooking(selectedBooking);
            if (selectedBooking.partner_id) {
                const partnerId = selectedBooking.partner_id[0];
                // POS only preloads a limited partner set: the booking
                // customer is often absent from the frontend cache, which
                // used to skip setPartner silently and break Pay at
                // Checkout later ("Customer Required" despite a room).
                // Load the record on demand so room always carries customer.
                let partner = this.pos.models["res.partner"].get(partnerId);
                if (!partner) {
                    try {
                        const loaded = await this.pos.data.read("res.partner", [partnerId]);
                        partner = loaded?.[0] || this.pos.models["res.partner"].get(partnerId);
                    } catch {
                        partner = null;
                    }
                }
                if (partner) {
                    order.setPartner(partner);
                } else {
                    this.env.services.notification.add(
                        _t("Room selected, but its customer could not be loaded. Please select the customer manually."),
                        { type: "warning" }
                    );
                }
            }
        }
    }
});
