/** @odoo-module */

import { GeneratePrinterData } from "@point_of_sale/app/utils/printer/generate_printer_data";
import { patch } from "@web/core/utils/patch";

/**
 * Show the charged room on printed receipts for hotel-charge payments.
 * Replaces the old OrderReceipt XML extension (that template no longer
 * exists in Odoo 20): the room name rides on the receipt data itself,
 * so printed tickets, the portal and emailed receipts all show it.
 */
patch(GeneratePrinterData.prototype, {
    generatePaymentData() {
        const lines = super.generatePaymentData(...arguments);
        const roomName = this.order?.uiState?.roomName;
        if (!roomName) {
            return lines;
        }
        const methodModel = this.models?.["pos.payment.method"];
        const hotelIds = new Set(
            (methodModel?.filter((m) => m.is_hotel_charge) || []).map((m) => m.id)
        );
        return lines.map((data) => {
            const methodId =
                data.payment_method_id?.id ?? data.payment_method_id?.[0];
            const isHotel =
                hotelIds.has(methodId) || data.payment_method_data?.is_hotel_charge;
            if (!isHotel) {
                return data;
            }
            return {
                ...data,
                payment_method_data: {
                    ...(data.payment_method_data || {}),
                    name: `${data.payment_method_data?.name || ""} (Room: ${roomName})`,
                },
            };
        });
    },
});
