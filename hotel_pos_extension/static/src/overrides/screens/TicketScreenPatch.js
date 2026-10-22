/** @odoo-module */

import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

/**
 * Safe replacement for `new URL(qrcode).searchParams.get("order_uuid")`.
 * The camera scanner passes any barcode rawValue (EAN, ref, garbage),
 * and `new URL()` throws TypeError on non-URL input. Return null instead
 * so the caller can show the "Invalid QR Code" warning.
 */
export function extractOrderUuid(qrcode) {
    if (!qrcode) {
        return null;
    }
    try {
        return new URL(qrcode).searchParams.get("order_uuid") || null;
    } catch {
        return null;
    }
}

patch(TicketScreen.prototype, {
    async onClickScanOrder(qrcode) {
        const uuid = extractOrderUuid(qrcode);
        if (!uuid) {
            this.env.services.notification.add(_t("Invalid QR Code! Please, Scan again!"), {
                type: "warning",
            });
            return;
        }
        const orders = await this.pos.data.loadServerOrders([["uuid", "=", uuid]]);
        const order = orders[0];
        if (order) {
            this.state.filter = "SYNCED";
            this.setSelectedOrder(order);
            this.pos.scanning = !this.pos.scanning;
        } else {
            this.env.services.notification.add(_t("Invalid QR Code! Please, Scan again!"), {
                type: "warning",
            });
        }
    },
});
