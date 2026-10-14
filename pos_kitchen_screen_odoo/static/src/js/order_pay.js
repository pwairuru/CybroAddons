/** @odoo-module **/

import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";

patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        this.kitchen = true;
        this.pos = this.env.services["pos"]; // ✅ get pos service if needed
    },


    async pay() {
        const order = this.getOrder();
        if (!order) return;

        // 20.0 port: client orders expose tracking_number, which the
        // server stores as pos_reference.
        const order_name = order.tracking_number;

        const result = await rpc("/web/dataset/call_kw/pos.order/check_order", {
            model: "pos.order",
            method: "check_order",
            args: [order_name],
            kwargs: {},
        });

        if (result.category) {
            this.kitchen = false;
            await this.env.services.dialog.add(AlertDialog, {
                title: _t("No category found"),
                body: _t(
                    `No food items found for the specified category (${result.category}) for this kitchen.
                    Please remove the selected food, update the order by clicking the 'Order' button,
                    and then proceed with the payment.`
                ),
            });
            return;
        }

        if (result === true) {
            this.kitchen = false;
            await this.env.services.dialog.add(AlertDialog, {
                title: _t("Food is not ready"),
                body: _t("Please complete all the food first."),
            });
            return;
        } else {
            this.kitchen = true;
        }

        if (!order.canPay()) {
            return;
        }

        super.pay()
    },
});
