/** @odoo-module */
// 20.0 port: rewritten against the Odoo 20 POS API.
// - pos.getOrderChanges() was removed after 17.0; change tracking now lives
//   on the order (preparationChanges / updateLastOrderChange).
// - pos.sendOrderInPreparationUpdateLastChange() is now
//   pos.sendOrderInPreparation(order) (which marks changes as sent itself).
// - Client orders expose tracking_number (synced as server pos_reference).
// - Getters already provided by pos_restaurant (swapButton, highlightPay,
//   displayOrderButton, categoryChanges) are left untouched.
import { patch } from "@web/core/utils/patch";
import { ActionpadWidget } from "@point_of_sale/app/screens/product_screen/action_pad/action_pad";
import { useService } from "@web/core/utils/hooks";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

/**
 * @props partner
 */
patch(ActionpadWidget.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        // Odoo 20 core ActionpadWidget has no uiState; keep a local
        // re-entrancy guard for the kitchen submit flow.
        this.uiState = { clicked: false };
    },

    async submitOrder() {
        var self = this;
        if (!this.uiState.clicked) {
            this.uiState.clicked = true;
            try {
                const orderRef = this.currentOrder?.tracking_number;
                await self.orm.call("pos.order", "check_order_status", ["", orderRef]).then(function(result){
                    if (result == false){
                        self.kitchen_order_status = false
                        self.env.services.dialog.add(AlertDialog, {
                            title: _t("Order is Completed"),
                            body: _t("This Order is Completed. Please create a new Order"),
                        });
                    }
                    else{
                         self.kitchen_order_status = true
                    }
                });
                if (self.kitchen_order_status){
                    // Marks the preparation changes as sent (was
                    // sendOrderInPreparationUpdateLastChange in <=17.0).
                    this.currentOrder?.updateLastOrderChange();
                    await this.processOrderForKitchen();
                }
            } finally {
                this.uiState.clicked = false;
            }
        }
    },
//
    async processOrderForKitchen() {
        var self = this;
        const order = this.currentOrder;
        const orderData = {
            'pos_reference': order?.tracking_number,
            'config_id': order?.config_id?.id ?? false,
            'table_id': order?.table_id?.id ?? false,
            'session_id': order?.session_id?.id ?? false,
        };
        await this.pos.syncAllOrders()
        await self.orm.call("pos.order", "process_order_for_kitchen", [orderData]);
    },

    hasQuantity(order) {
        if (!order) {
            return false;
        } else {
            return (
                order.lines.reduce((totalQty, line) => totalQty + line.getQuantity(), 0) > 0
            );
        }
    },
});
