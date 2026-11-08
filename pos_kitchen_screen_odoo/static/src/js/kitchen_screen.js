/** @odoo-module */
import { registry } from "@web/core/registry";
import { Component, onMounted, onWillUnmount, proxy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

class KitchenScreenDashboard extends Component {
    setup() {
        super.setup();

        // Services
        this.action = useService("action");
        this.rpc = this.env.services.rpc;
        this.orm = useService("orm");
        this.busService = useService("bus_service");

        // Method binding
        this.getCurrentShopId = this.getCurrentShopId.bind(this);
        this.loadOrders = this.loadOrders.bind(this);
        this.startCountdown = this.startCountdown.bind(this);
        this.updateCountdownState = this.updateCountdownState.bind(this);
        this.onPosOrderCreation = this.onPosOrderCreation.bind(this);
        this.accept_order = this.accept_order.bind(this);
        this.done_order = this.done_order.bind(this);
        this.cancel_order = this.cancel_order.bind(this);
        this.accept_order_line = this.accept_order_line.bind(this);
        this.forceRefresh = this.forceRefresh.bind(this);
        this.parseKitchenNote = this.parseKitchenNote.bind(this);
        this.toggleMute = this.toggleMute.bind(this);
        this.unlockAudio = this.unlockAudio.bind(this);
        this.loadSoundConfig = this.loadSoundConfig.bind(this);

        // Stage change methods
        this.ready_stage = (e) => this.state.stages = 'ready';
        this.waiting_stage = (e) => this.state.stages = 'waiting';
        this.draft_stage = (e) => this.state.stages = 'draft';

        // Initialization
        this.currentShopId = this.getCurrentShopId();
        this.channel = `pos_order_created_${this.currentShopId}`;
        this.countdownIntervals = {};
        // Single-audio new-order alerter: one Audio element, one repeat
        // timer. Never one player per card.
        this.alertAudio = null;
        this.audioUnlocked = false;
        this.knownOrderIds = new Set();
        this.knownLineIds = new Set();
        this.knownFingerprints = new Map();
        this.knownStatuses = new Map();
        this.unackedOrderIds = new Set();
        this.alerterReady = false;
        this.repeatTimer = null;
        this.soundChoice = 'chime';
        this.repeatDelay = 8;

        // State management
        this.state = proxy({
            order_details: [],
            shop_id: this.currentShopId,
            kitchens: [],
            dark: localStorage.getItem('kitchen_dark') === '1',
            stages: 'draft',
            draft_count: 0,
            waiting_count: 0,
            ready_count: 0,
            lines: [],
            prepare_times: [],
            countdowns: {},
            isLoading: false,
            muted: localStorage.getItem('kitchen_muted') === '1',
            alertIds: [],
            audioReady: false,
        });

        // Component lifecycle
        onMounted(async () => {
            const resolved = await this.resolveShop();
            if (resolved) {
                this.currentShopId = resolved;
                this.state.shop_id = resolved;
            }
            if (this.currentShopId) {
                this.channel = `pos_order_created_${this.currentShopId}`;
                this.busService.addChannel(this.channel);
                this.busService.subscribe('notification', this.onPosOrderCreation);
            }
            this.state.muted = localStorage.getItem(this.muteKey()) === '1';
            await this.loadSoundConfig();
            window.addEventListener('pointerdown', this.unlockAudio, { once: true });
            window.addEventListener('keydown', this.unlockAudio, { once: true });
            this.loadOrders();

            // Poll fallback: bus push depends on the websocket worker,
            // which is fragile (proxy/gevent/flaps), so refresh on a short
            // tick. get_details is a few small reads; 5s keeps new tickets
            // and note edits within seconds even when live push dies.
            this.autoRefreshInterval = setInterval(() => {
                this.loadOrders();
            }, 5000);
        });

        onWillUnmount(() => {
            this.busService.deleteChannel(this.channel);
            this.busService.unsubscribe('notification', this.onPosOrderCreation);
            window.removeEventListener('pointerdown', this.unlockAudio);
            window.removeEventListener('keydown', this.unlockAudio);
            this.stopAlertLoop();
            if (this.autoRefreshInterval) {
                clearInterval(this.autoRefreshInterval);
            }
            Object.values(this.countdownIntervals).forEach(interval => {
                clearInterval(interval);
            });
            this.countdownIntervals = {};
        });
    }

    getCurrentShopId() {
        let session_shop_id;
        // NOTE: read shop_id first. default_* keys are stripped by
        // doActionButton when a type=object button returns an action,
        // so context must travel in the button's own context instead
        // (see the type=action buttons in the views).
        const ctx = this.props?.action?.context || {};
        if (ctx.shop_id || ctx.default_shop_id) {
            session_shop_id = ctx.shop_id || ctx.default_shop_id;
            sessionStorage.setItem('shop_id', session_shop_id);
        } else {
            session_shop_id = sessionStorage.getItem('shop_id');
        }
        return parseInt(session_shop_id, 10) || 0;
    }

    parseKitchenNote(note) {
        if (!note) {
            return "";
        }
        if (Array.isArray(note)) {
            return note.map((n) => (typeof n === "string" ? n : n.text || "")).filter(Boolean).join(", ");
        }
        if (typeof note === "string") {
            try {
                const parsed = JSON.parse(note);
                if (Array.isArray(parsed)) {
                    return parsed.map((n) => (typeof n === "string" ? n : n.text || "")).filter(Boolean).join(", ");
                }
                return note;
            } catch {
                return note;
            }
        }
        return "";
    }

    muteKey() {
        return `kitchen_muted_${this.currentShopId || 'all'}`;
    }

    async loadSoundConfig() {
        if (!this.currentShopId) {
            return;
        }
        try {
            const rows = await this.orm.searchRead(
                'kitchen.screen',
                [['pos_config_id', '=', this.currentShopId]],
                ['notification_sound', 'notification_repeat_delay'],
                { limit: 1 }
            );
            if (rows && rows[0]) {
                this.soundChoice = rows[0].notification_sound || 'chime';
                const delay = Number(rows[0].notification_repeat_delay) || 8;
                this.repeatDelay = Math.min(60, Math.max(3, delay));
            }
        } catch (error) {
            console.error("Error loading kitchen sound config:", error);
        }
        this.alertAudio = this.soundChoice === 'none' ? null : new Audio(this.soundUrl());
        if (this.alertAudio) {
            this.alertAudio.preload = 'auto';
        }
        if (this.unackedOrderIds.size && !this.state.muted) {
            this.startAlertLoop();
        }
    }

    soundUrl() {
        return `/pos_kitchen_screen_odoo/static/src/sounds/${this.soundChoice}.mp3`;
    }

    unlockAudio() {
        // Browsers block audio before a user gesture; first tap/click
        // arms the single shared Audio element for the alert loop.
        this.audioUnlocked = true;
        this.state.audioReady = true;
        if (this.alertAudio && this.unackedOrderIds.size && !this.state.muted) {
            this.playAlert();
        }
    }

    playAlert() {
        if (!this.alertAudio || this.state.muted || !this.audioUnlocked) {
            return;
        }
        try {
            this.alertAudio.currentTime = 0;
            const playPromise = this.alertAudio.play();
            if (playPromise && playPromise.catch) {
                playPromise.catch((err) => {
                    // Only a policy block re-arms the banner. Interrupt
                    // aborts (pause/play races on repeat ticks) are benign
                    // and must not resurrect it after a tap.
                    if (err && err.name === 'NotAllowedError' && this.state.audioReady) {
                        this.state.audioReady = false;
                    }
                });
            }
        } catch (error) {
            // Autoplay policy or missing file: stay silent, retry next tick.
        }
    }

    startAlertLoop() {
        this.stopAlertLoop();
        // 'none' = silent kitchen: card glow still marks changes, but no
        // audio element exists and no repeat timer is armed.
        if (this.state.muted || !this.unackedOrderIds.size || this.soundChoice === 'none') {
            return;
        }
        this.playAlert();
        this.repeatTimer = setInterval(() => {
            this.playAlert();
        }, this.repeatDelay * 1000);
    }

    stopAlertLoop() {
        if (this.repeatTimer) {
            clearInterval(this.repeatTimer);
            this.repeatTimer = null;
        }
        if (this.alertAudio) {
            try {
                this.alertAudio.pause();
            } catch (error) {
                // Ignore pause errors on teardown.
            }
        }
    }

    orderFingerprint(order, linesById) {
        // Content that matters to the kitchen: notes + kitchen line set
        // with quantities and notes. Only lines visible on this screen
        // (present in linesById) count, so adding a non-kitchen item
        // (e.g. a drink) never rings the kitchen. Statuses/dates excluded
        // so Accept/stage moves never count as content changes.
        const parts = [
            order.general_customer_note || '',
            order.internal_note || '',
        ];
        const lineIds = [...(order.lines || [])]
            .filter((id) => id in linesById)
            .sort((a, b) => a - b);
        for (const id of lineIds) {
            const line = linesById[id];
            parts.push([
                id,
                line.qty,
                line.note || '',
                line.customer_note || '',
                line.full_product_name || '',
            ].join('|'));
        }
        return parts.join('~');
    }

    clearMute() {
        // A new kitchen-relevant change re-arms sound: mute silences the
        // current alarm, it never deafens the screen.
        if (!this.state.muted) {
            return;
        }
        this.state.muted = false;
        try {
            localStorage.setItem(this.muteKey(), '0');
        } catch (error) {
            // Private mode etc: keep unmute session-only.
        }
    }

    syncAlertState() {
        // Mirror the alerter set into reactive state so changed cards
        // glow for exactly as long as the alarm loops for them.
        this.state.alertIds = [...this.unackedOrderIds];
    }

    alertCountFor(status) {
        // Tab badges share the card-glow lifecycle: same ids, same stop
        // rules (Accept/mute/stage move). Counts alerts per order_status.
        const statusById = {};
        for (const order of this.state.order_details) {
            statusById[order.id] = order.order_status;
        }
        return this.state.alertIds.filter((id) => statusById[id] === status).length;
    }

    detectArrivals(orders, lines) {
        // Baseline first load so pre-existing cards stay silent; alert
        // afterwards on new draft ids, new line ids, or content changes
        // (notes/quantities) on draft + waiting orders.
        const draftOrders = orders.filter((o) => o.order_status === 'draft');
        const draftIds = new Set(draftOrders.map((o) => o.id));
        const lineIds = new Set((lines || []).map((l) => l.id));
        const linesById = {};
        for (const line of lines || []) {
            linesById[line.id] = line;
        }
        const activeOrders = orders.filter(
            (o) => o.order_status === 'draft' || o.order_status === 'waiting'
        );
        if (!this.alerterReady) {
            this.knownOrderIds = draftIds;
            this.knownLineIds = lineIds;
            for (const order of activeOrders) {
                this.knownFingerprints.set(
                    order.id, this.orderFingerprint(order, linesById));
                this.knownStatuses.set(order.id, order.order_status);
            }
            this.alerterReady = true;
            return;
        }
        let arrived = false;
        const lineToOrder = {};
        for (const order of orders) {
            for (const lineId of order.lines || []) {
                lineToOrder[lineId] = order.id;
            }
        }
        for (const id of draftIds) {
            if (!this.knownOrderIds.has(id)) {
                this.unackedOrderIds.add(id);
                arrived = true;
            }
        }
        for (const line of lines || []) {
            if (!this.knownLineIds.has(line.id)) {
                const ownerId = lineToOrder[line.id];
                if (ownerId && draftIds.has(ownerId)) {
                    this.unackedOrderIds.add(ownerId);
                    arrived = true;
                }
                // Lines owned by waiting orders are covered by the
                // fingerprint check below; other unknowns stay silent.
            }
        }
        for (const order of activeOrders) {
            const prevStatus = this.knownStatuses.get(order.id);
            if (prevStatus === 'draft' && order.order_status === 'waiting') {
                // Accepted elsewhere: stage move is the acknowledgment,
                // no alarm needed.
                this.unackedOrderIds.delete(order.id);
            } else {
                const fp = this.orderFingerprint(order, linesById);
                const prevFp = this.knownFingerprints.get(order.id);
                if (prevFp === undefined) {
                    // First sight in waiting (e.g. accepted elsewhere
                    // before this screen loaded it): baseline silently.
                    this.knownFingerprints.set(order.id, fp);
                } else if (prevFp !== fp) {
                    this.knownFingerprints.set(order.id, fp);
                    this.unackedOrderIds.add(order.id);
                    arrived = true;
                }
            }
            this.knownStatuses.set(order.id, order.order_status);
        }
        for (const id of [...this.knownFingerprints.keys()]) {
            if (!activeOrders.some((o) => o.id === id)) {
                this.knownFingerprints.delete(id);
                this.knownStatuses.delete(id);
            }
        }
        this.knownOrderIds = draftIds;
        this.knownLineIds = lineIds;
        this.pruneUnacked(orders);
        this.syncAlertState();
        if (arrived && this.unackedOrderIds.size) {
            this.clearMute();
            this.startAlertLoop();
        } else if (!this.unackedOrderIds.size) {
            this.stopAlertLoop();
        }
    }

    pruneUnacked(orders) {
        const stillActive = new Set(
            orders.filter((o) => o.order_status === 'draft' || o.order_status === 'waiting')
                .map((o) => o.id)
        );
        for (const id of [...this.unackedOrderIds]) {
            if (!stillActive.has(id)) {
                this.unackedOrderIds.delete(id);
            }
        }
        if (!this.unackedOrderIds.size) {
            this.stopAlertLoop();
        }
    }

    toggleMute() {
        this.audioUnlocked = true;
        this.state.audioReady = true;
        this.state.muted = !this.state.muted;
        try {
            localStorage.setItem(this.muteKey(), this.state.muted ? '1' : '0');
        } catch (error) {
            // Private mode etc: keep mute session-only.
        }
        if (this.state.muted) {
            // Muting acknowledges the current batch: silence now, stay
            // armed for the next new order, line, or note change.
            this.unackedOrderIds.clear();
            this.syncAlertState();
            this.stopAlertLoop();
        } else if (this.unackedOrderIds.size) {
            this.startAlertLoop();
        }
    }

    async loadOrders() {
        if (this.state.isLoading) return;

        try {
            this.state.isLoading = true;
            const result = await this.orm.call("pos.order", "get_details", [this.currentShopId]);

            this.state.order_details = result.orders || [];
            this.state.lines = result.order_lines || [];
            // Internal notes (line.note, order.internal_note) are stored as
            // JSON arrays [{text, colorIndex}] by POS (see InternalNoteButton
            // reframeNotes). Parse to plain text for display; fall back to raw
            // for legacy plain-text notes.
            for (const order of this.state.order_details) {
                order.internal_note_display = this.parseKitchenNote(order.internal_note);
            }
            for (const line of this.state.lines) {
                line.note_display = this.parseKitchenNote(line.note);
            }
            this.detectArrivals(this.state.order_details, this.state.lines);

            const activeOrders = this.state.order_details.filter(order => {
                const configMatch = Array.isArray(order.config_id) ?
                    order.config_id[0] === this.currentShopId :
                    order.config_id === this.currentShopId;
                return configMatch && order.order_status !== 'cancel' && order.state !== 'cancel';
            });
            const productIds = [...new Set(this.state.lines.map(line => line.product_id[0]))];
            if (productIds.length) {
                const overTimes = await this.orm.call(
                    "product.product",
                    "search_read",
                    [[["id", "in", productIds]], ["id", "prepair_time_minutes"]]
                );
                this.state.prepare_times = overTimes.map(item => ({
                    ...item,
                    prepare_time: !item.prepair_time_minutes ? "00:00:00" :
                        typeof item.prepair_time_minutes === 'number' ?
                        parseFloat(item.prepair_time_minutes.toFixed(2)) :
                        item.prepair_time_minutes
                }));
            }
            this.state.draft_count = activeOrders.filter(o => o.order_status === 'draft').length;
            this.state.waiting_count = activeOrders.filter(o => o.order_status === 'waiting').length;
            this.state.ready_count = activeOrders.filter(o => o.order_status === 'ready').length;

            activeOrders.forEach(order => {
                if (order.order_status === 'waiting' && order.avg_prepare_time) {

                    if (!this.countdownIntervals[order.id]) {
                        this.startCountdown(order.id, order.avg_prepare_time, order.config_id);
                    }
                } else if (order.order_status === 'ready') {
                    this.updateCountdownState(order.id, 0, true);
                    if (this.countdownIntervals[order.id]) {
                        clearInterval(this.countdownIntervals[order.id]);
                        delete this.countdownIntervals[order.id];
                    }
                }
            });
        } catch (error) {
            console.error("Error loading orders:", error);
        } finally {
            this.state.isLoading = false;
        }
    }

    async startCountdown(orderId, timeString,config_id) {
        if (this.countdownIntervals[orderId]) {
            clearInterval(this.countdownIntervals[orderId]);
        }

        const [minutes, seconds] = timeString.toFixed(2).split('.').map(Number);
        let totalSeconds = minutes * 60 + seconds;

        this.updateCountdownState(orderId, totalSeconds, false);

        this.countdownIntervals[orderId] = setInterval(async () => {
            totalSeconds--;
            if (totalSeconds > 0) {
                this.updateCountdownState(orderId, totalSeconds, false, false);
                return;
            }
            clearInterval(this.countdownIntervals[orderId]);
            delete this.countdownIntervals[orderId];
            let autoDone = false;
            try {
                let orderData = await this.orm.call(
                    'kitchen.screen',
                    'search_read',
                    [
                        [["pos_config_id", "=", config_id[0]]],
                        ["is_preparation_complete"]
                    ]
                );
                if (orderData[0] && orderData[0].is_preparation_complete === true) {
                    await this.done_order({ target: { value: orderId.toString() } });
                    autoDone = true;
                }
            } catch (error) {
                console.error("Error fetching order data:", error);
                // Handle error appropriately
            }
            if (!autoDone) {
                this.updateCountdownState(orderId, 0, false, true);
            }
        }, 1000);
    }

    updateCountdownState(orderId, totalSeconds, isCompleted = false, isOverdue = false) {
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = totalSeconds % 60;
        this.state.countdowns = {
            ...this.state.countdowns,
            [orderId]: {
                minutes,
                seconds,
                isCompleted,
                isOverdue
            }
        };
    }

    onPosOrderCreation(message) {
        if (!message || message.config_id !== this.currentShopId) {
            return;
        }

        const relevantMessages = [
            'pos_order_created',
            'pos_order_updated',
            'pos_order_paid',
            'pos_order_accepted',
            'pos_order_cancelled',
            'pos_order_completed',
            'pos_order_line_updated'
        ];

        if ((message.res_model === "pos.order" || message.res_model === "pos.order.line") &&
            relevantMessages.includes(message.message)) {
            this.loadOrders();
        }
    }

    async accept_order(e) {
        const orderId = Number(e.target.value);
        this.unackedOrderIds.delete(orderId);
        this.syncAlertState();
        if (!this.unackedOrderIds.size) {
            this.stopAlertLoop();
        }
        try {
            await this.orm.call("pos.order", "order_progress_draft", [orderId]);

            const order = this.state.order_details.find(o => o.id === orderId);
            if (order) {
                order.order_status = 'waiting';
                if (order.avg_prepare_time) {
                    this.startCountdown(orderId, order.avg_prepare_time, order.config_id);
                }
            }

            setTimeout(() => this.loadOrders(), 500);
        } catch (error) {
            console.error("Error accepting order:", error);
        }
    }

    async done_order(e) {
        const orderId = Number(e.target.value);
        this.unackedOrderIds.delete(orderId);
        this.syncAlertState();
        if (!this.unackedOrderIds.size) {
            this.stopAlertLoop();
        }
        try {
            await this.orm.call("pos.order", "order_progress_change", [orderId]);

            const order = this.state.order_details.find(o => o.id === orderId);
            if (order) {
                order.order_status = 'ready';
                this.updateCountdownState(orderId, 0, true);
                if (this.countdownIntervals[orderId]) {
                    clearInterval(this.countdownIntervals[orderId]);
                    delete this.countdownIntervals[orderId];
                }
            }

            setTimeout(() => this.loadOrders(), 500);
        } catch (error) {
            console.error("Error completing order:", error);
        }
    }

    async cancel_order(e) {
        const orderId = Number(e.target.value);
        this.unackedOrderIds.delete(orderId);
        this.syncAlertState();
        if (!this.unackedOrderIds.size) {
            this.stopAlertLoop();
        }
        try {
            await this.orm.call("pos.order", "order_progress_cancel", [orderId]);

            const order = this.state.order_details.find(o => o.id === orderId);
            if (order) {
                order.order_status = 'cancel';
            }

            setTimeout(() => this.loadOrders(), 500);
        } catch (error) {
            console.error("Error cancelling order:", error);
        }
    }

    async accept_order_line(e) {
        const lineId = Number(e.target.value);
        try {
            await this.orm.call("pos.order.line", "order_progress_change", [lineId]);

            const line = this.state.lines.find(l => l.id === lineId);
            if (line) {
                line.order_status = line.order_status === 'ready' ? 'waiting' : 'ready';
            }

            setTimeout(() => this.loadOrders(), 500);
        } catch (error) {
            console.error("Error updating order line:", error);
        }
    }

    get filteredOrders() {
        return this.state.order_details.filter(order => {
            const configMatch = Array.isArray(order.config_id) ?
                order.config_id[0] === this.currentShopId :
                order.config_id === this.currentShopId;
            const stageMatch = order.order_status === this.state.stages;
            return configMatch && stageMatch && order.order_status !== 'cancel';
        });
    }

    async resolveShop() {
        // Context keys do not reliably survive the action pipeline
        // (doActionButton strips default_*, and returned/embedded
        // contexts get lost), so fall back to the kitchens themselves:
        // exactly one kitchen -> use it, several -> let user pick.
        const fromCtx = this.getCurrentShopId();
        if (fromCtx) {
            return fromCtx;
        }
        let kitchens = [];
        try {
            kitchens = await this.orm.searchRead('kitchen.screen', [], ['pos_config_id']) || [];
        } catch (error) {
            console.error('Error resolving kitchen shop:', error);
        }
        if (kitchens.length === 1 && kitchens[0].pos_config_id) {
            const shopId = kitchens[0].pos_config_id[0];
            sessionStorage.setItem('shop_id', shopId);
            return shopId;
        }
        this.state.kitchens = kitchens;
        return 0;
    }

    async pickShop(shopId) {
        if (this.channel) {
            this.busService.deleteChannel(this.channel);
            this.busService.unsubscribe('notification', this.onPosOrderCreation);
        }
        this.currentShopId = shopId;
        this.state.shop_id = shopId;
        this.state.kitchens = [];
        sessionStorage.setItem('shop_id', shopId);
        this.channel = `pos_order_created_${shopId}`;
        this.busService.addChannel(this.channel);
        this.busService.subscribe('notification', this.onPosOrderCreation);
        this.stopAlertLoop();
        this.knownOrderIds = new Set();
        this.knownLineIds = new Set();
        this.knownFingerprints = new Map();
        this.knownStatuses = new Map();
        this.unackedOrderIds = new Set();
        this.syncAlertState();
        this.alerterReady = false;
        this.state.muted = localStorage.getItem(this.muteKey()) === '1';
        await this.loadSoundConfig();
        await this.loadOrders();
    }

    forceRefresh() {
        this.loadOrders();
    }

    toggleDark() {
        this.state.dark = !this.state.dark;
        localStorage.setItem('kitchen_dark', this.state.dark ? '1' : '0');
    }

    goBack() {
        this.action.doAction('pos_kitchen_screen_odoo.kitchen_screen_action');
    }
}

KitchenScreenDashboard.template = 'KitchenCustomDashBoard';
registry.category("actions").add("kitchen_custom_dashboard_tags", KitchenScreenDashboard);