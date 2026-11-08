/** @odoo-module */
// Kitchen -> POS status sync (pwairuru fix).
//
// The kitchen screen writes order_status on pos.order (draft=cooking,
// waiting=ready-to-serve, ready=completed, cancel) and broadcasts on the
// bus channel `pos_order_created_<config_id>`. Nothing in POS listened,
// so waiters never saw readiness. This patch subscribes the POS store to
// that channel and mirrors status onto the local pos.order records:
//
// - Floor tables with a ready-to-serve order get a green highlight
//   (see FloorTable patch below).
// - A toast names the table when its order becomes ready.
// - TicketScreen / tracker read the same local records, so every order
//   list refreshes automatically (reactive models).
//
// Status lives on order.uiState (client models only declare core fields,
// so order_status cannot be set/updated directly). On POS load, open
// kitchen orders are backfilled once via a single searchRead.
//
// Scope: own POS config only. Drafts are config-scoped server-side, so
// messages for other configs are ignored.
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { FloorTable } from "@pos_restaurant/app/services/floor_plan/elements/table";
import { _t } from "@web/core/l10n/translation";

const KITCHEN_MESSAGES = [
    "pos_order_created",
    "pos_order_updated",
    "pos_order_accepted",
    "pos_order_cancelled",
    "pos_order_completed",
    "pos_order_line_updated",
    "kitchen_order_status_updated",
];

// Border/background used when the table's active order is ready to serve.
const READY_BORDER = "#198754";
const READY_BG = "rgba(25, 135, 84, 0.35)";

function kitchenStatusOf(order) {
    return order && !order.finalized ? order.uiState?.kitchenStatus || false : false;
}

patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        this._kitchenSyncHandler = this._onKitchenNotification.bind(this);
        this._kitchenSyncChannel = `pos_order_created_${this.config.id}`;
        this.bus.addChannel(this._kitchenSyncChannel);
        this.bus.subscribe("notification", this._kitchenSyncHandler);
        this._backfillKitchenStatus().catch((e) => {
            console.error("Kitchen status backfill failed:", e);
        });
        // Poll fallback: bus delivery depends on the websocket worker, which
        // is fragile (proxy/gevent/flaps). One small read every 15s keeps
        // tables fresh even when live push dies. Same pattern as the kitchen
        // dashboard's own 5s refresh.
        this._kitchenPollId = setInterval(() => {
            this._backfillKitchenStatus().catch(() => {});
        }, 15000);
    },

    async _backfillKitchenStatus() {
        const rows = await this.env.services.orm.searchRead(
            "pos.order",
            [
                ["session_id", "=", this.session.id],
                ["state", "=", "draft"],
                ["is_cooking", "=", true],
            ],
            ["order_status", "table_id"]
        );
        for (const row of rows) {
            const local = this.models["pos.order"].get(row.id);
            if (local && !local.finalized && row.order_status) {
                const before = kitchenStatusOf(local);
                local.uiState.kitchenStatus = row.order_status;
                this._notifyIfReady(local, before);
            }
        }
    },

    _notifyIfReady(local, before) {
        if (kitchenStatusOf(local) === "waiting" && before !== "waiting") {
            const tableNo = local.table_id?.table_number ?? local.name;
            this.notification.add(_t("Table %s is ready for pickup.", tableNo), {
                type: "success",
            });
        }
    },

    _onKitchenNotification(message) {
        if (!message || message.config_id !== this.config.id) {
            return;
        }
        if (
            (message.res_model !== "pos.order" &&
                message.res_model !== "pos.order.line") ||
            !KITCHEN_MESSAGES.includes(message.message)
        ) {
            return;
        }
        const orderId = message.order_id;
        if (!orderId) {
            return;
        }
        this._refreshKitchenOrderStatus(orderId, message.message).catch((e) => {
            // Never break POS on a status-sync failure; kitchen screen
            // remains the source of truth.
            console.error("Kitchen status sync failed:", e);
        });
    },

    async _refreshKitchenOrderStatus(orderId, kind) {
        const local = this.models["pos.order"].get(orderId);
        if (!local || local.finalized) {
            return;
        }
        const [vals] = await this.env.services.orm.read("pos.order", [orderId], [
            "order_status",
            "is_cooking",
        ]);
        if (!vals) {
            return;
        }
        const before = kitchenStatusOf(local);
        local.uiState.kitchenStatus = vals.order_status || false;
        if (kind === "pos_order_accepted") {
            this._notifyIfReady(local, before);
        }
    },
});

patch(FloorTable.prototype, {
    getCssColorStyle() {
        if (kitchenStatusOf(this.record?.getOrder?.()) === "waiting") {
            return (
                `border-color:${READY_BORDER};` +
                `background-color:${READY_BG};color:#fff;`
            );
        }
        return super.getCssColorStyle(...arguments);
    },
});
