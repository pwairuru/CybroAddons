/** Kitchen screen alerter tests.
 *
 * Exercises the real methods shipped in
 * `../../static/src/js/kitchen_screen.js` (extracted by balanced-brace
 * scan, bound onto a stub context) so refactors of the component break
 * these tests instead of silently drifting.
 *
 * Run: `node --test tests/js/` from the module root.
 */
import { afterEach, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const COMPONENT = join(
    dirname(fileURLToPath(import.meta.url)),
    '..', '..', 'static', 'src', 'js', 'kitchen_screen.js');

function extractMethod(source, name) {
    const start = source.indexOf(`    ${name}(`);
    assert.notEqual(start, -1, `method ${name} found in component`);
    let i = source.indexOf('{', start) + 1;
    let depth = 1;
    while (depth > 0) {
        const c = source[i];
        if (c === '{') {
            depth += 1;
        } else if (c === '}') {
            depth -= 1;
        }
        i += 1;
    }
    return source.slice(start, i);
}

const METHOD_NAMES = [
    'orderFingerprint',
    'clearMute',
    'detectArrivals',
    'pruneUnacked',
    'toggleMute',
    'syncAlertState',
    'startAlertLoop',
    'playAlert',
    'alertCountFor',
];

const body = METHOD_NAMES
    .map((name) => extractMethod(readFileSync(COMPONENT, 'utf8'), name))
    .join(',\n\n');

const contexts = [];
afterEach(() => {
    // Repeat timers would keep the runner alive; the assertions already
    // ran, so drop them between tests.
    for (const ctx of contexts.splice(0)) {
        if (ctx.repeatTimer) {
            clearInterval(ctx.repeatTimer);
            ctx.repeatTimer = null;
        }
    }
});

// eslint-disable-next-line no-eval
function makeCtx(overrides = {}) {
    const { state: stateOverrides, ...rest } = overrides;    const state = {
        muted: false,
        alertIds: [],
        audioReady: true,
        order_details: [],
        ...stateOverrides,
    };
    const calls = { start: 0, stop: 0, plays: 0 };
    const ctx = {
        knownOrderIds: new Set(),
        knownLineIds: new Set(),
        knownFingerprints: new Map(),
        knownStatuses: new Map(),
        unackedOrderIds: new Set(),
        alerterReady: false,
        audioUnlocked: true,
        soundChoice: 'chime',
        repeatDelay: 8,
        repeatTimer: null,
        alertAudio: { currentTime: 0, play() { calls.plays += 1; } },
        state,
        muteKey() { return 'kitchen_muted_test'; },
        stopAlertLoop() {
            if (this.repeatTimer) {
                clearInterval(this.repeatTimer);
                this.repeatTimer = null;
            }
            calls.stop += 1;
        },
        ...eval(`({${body}})`),
        ...rest,
    };
    // Re-bind extracted methods (spread loses nothing, but be explicit).
    for (const name of METHOD_NAMES) {
        ctx[name] = ctx[name].bind(ctx);
    }
    // Real startAlertLoop uses stubbed stopAlertLoop; count starts.
    const realStart = ctx.startAlertLoop;
    ctx.startAlertLoop = (...args) => {
        calls.start += 1;
        return realStart.apply(ctx, args);
    };
    contexts.push(ctx);
    return { ctx, state, calls };
}

const O = (id, status, extra = {}) => Object.assign({
    id,
    order_status: status,
    lines: [101],
    general_customer_note: '',
    internal_note: '',
}, extra);
const L = (id, extra = {}) => Object.assign({
    id,
    qty: 1,
    note: '',
    customer_note: '',
    full_product_name: 'Burger',
    order_status: 'draft',
}, extra);

describe('arrival detection', () => {
    it('baselines first load silently', () => {
        const { ctx, calls } = makeCtx();
        ctx.detectArrivals([O(1, 'draft')], [L(101)]);
        assert.equal(ctx.unackedOrderIds.size, 0);
        assert.equal(calls.start, 0);
    });

    it('alerts on new draft orders', () => {
        const { ctx, state, calls } = makeCtx();
        ctx.detectArrivals([O(1, 'draft')], [L(101)]);
        ctx.detectArrivals([O(1, 'draft'), O(2, 'draft')], [L(101)]);
        assert.ok(ctx.unackedOrderIds.has(2));
        assert.equal(calls.start, 1);
        assert.deepEqual(state.alertIds, [2]);
    });

    it('re-arms on draft note edits', () => {
        const { ctx, calls } = makeCtx();
        ctx.detectArrivals([O(1, 'draft')], [L(101)]);
        ctx.detectArrivals(
            [O(1, 'draft', { general_customer_note: 'no salt' })], [L(101)]);
        assert.equal(calls.start, 1);
    });

    it('re-arms on waiting note edits', () => {
        const { ctx, calls } = makeCtx();
        ctx.detectArrivals([O(2, 'waiting')], [L(101)]);
        ctx.detectArrivals(
            [O(2, 'waiting', { general_customer_note: 'ketchup' })], [L(101)]);
        assert.ok(ctx.unackedOrderIds.has(2));
        assert.equal(calls.start, 1);
    });

    it('drops alarm on external accept without sound', () => {
        const { ctx, calls } = makeCtx();
        ctx.detectArrivals([O(2, 'draft')], [L(101)]);
        const before = calls.start;
        ctx.detectArrivals([O(2, 'waiting')], [L(101)]);
        assert.ok(!ctx.unackedOrderIds.has(2));
        assert.equal(calls.start, before);
    });

    it('ignores chef line-status toggles', () => {
        const { ctx, calls } = makeCtx();
        ctx.detectArrivals([O(2, 'waiting')], [L(101)]);
        const before = calls.start;
        ctx.detectArrivals(
            [O(2, 'waiting')], [L(101, { order_status: 'ready' })]);
        assert.equal(calls.start, before);
    });

    it('ignores non-kitchen line additions', () => {
        const { ctx, calls } = makeCtx();
        // Order carries a bar-only line id (999) never sent to the screen.
        ctx.detectArrivals([O(1, 'draft', { lines: [101, 999] })], [L(101)]);
        const before = calls.start;
        ctx.detectArrivals(
            [O(1, 'draft', { lines: [101, 999, 998] })], [L(101)]);
        assert.equal(calls.start, before);
        assert.equal(ctx.unackedOrderIds.size, 0);
    });

    it('prunes completed orders and clears glow', () => {
        const { ctx, state } = makeCtx();
        ctx.detectArrivals([O(1, 'draft'), O(2, 'draft')], [L(101)]);
        ctx.detectArrivals([O(1, 'draft')], [L(101)]);
        assert.equal(ctx.unackedOrderIds.size, 0);
        assert.deepEqual(state.alertIds, []);
    });
});

describe('mute semantics', () => {
    it('mute acknowledges the batch and clears glow', () => {
        const { ctx, state } = makeCtx();
        ctx.detectArrivals([O(1, 'draft'), O(2, 'draft')], [L(101)]);
        ctx.toggleMute();
        assert.equal(state.muted, true);
        assert.equal(ctx.unackedOrderIds.size, 0);
        assert.deepEqual(state.alertIds, []);
    });

    it('next change re-arms and unmutes', () => {
        const { ctx, state, calls } = makeCtx();
        ctx.detectArrivals([O(2, 'draft')], [L(101)]);
        ctx.toggleMute();
        const before = calls.start;
        ctx.detectArrivals(
            [O(2, 'draft', { general_customer_note: 'onions' })], [L(101)]);
        assert.equal(state.muted, false);
        assert.equal(calls.start, before + 1);
        assert.deepEqual(state.alertIds, [2]);
    });
});

describe('silent kitchens', () => {
    it('none arms no timer and plays nothing', () => {
        const { ctx, calls } = makeCtx();
        ctx.soundChoice = 'none';
        ctx.unackedOrderIds.add(7);
        ctx.startAlertLoop();
        assert.equal(calls.plays, 0);
        assert.equal(ctx.repeatTimer, null);
    });

    it('glow still marks changes when silent', () => {
        const { ctx, state } = makeCtx();
        ctx.soundChoice = 'none';
        ctx.detectArrivals([O(1, 'draft')], [L(101)]);
        ctx.detectArrivals([O(1, 'draft'), O(2, 'draft')], [L(101)]);
        assert.deepEqual(state.alertIds, [2]);
    });
});

describe('play() rejection handling', () => {
    for (const [name, locked] of [
        ['AbortError', true],
        ['InterruptError', true],
        ['NotAllowedError', false],
    ]) {
        it(`only NotAllowedError re-locks (case ${name})`, async () => {
            const { ctx, state } = makeCtx({
                alertAudio: {
                    currentTime: 0,
                    play() {
                        const err = new Error(name);
                        err.name = name;
                        return Promise.reject(err);
                    },
                },
            });
            ctx.playAlert();
            await new Promise((resolve) => setTimeout(resolve, 20));
            assert.equal(state.audioReady, locked);
        });
    }
});

describe('tab badges', () => {
    it('counts alerts per stage and clears with alarm', () => {
        const { ctx, state } = makeCtx({
            state: {
                order_details: [
                    { id: 5, order_status: 'draft' },
                    { id: 9, order_status: 'waiting' },
                    { id: 3, order_status: 'draft' },
                ],
            },
        });
        state.alertIds = [5, 9];
        assert.equal(ctx.alertCountFor('draft'), 1);
        assert.equal(ctx.alertCountFor('waiting'), 1);
        assert.equal(ctx.alertCountFor('ready'), 0);
        state.alertIds = [];
        assert.equal(ctx.alertCountFor('draft'), 0);
    });
});
