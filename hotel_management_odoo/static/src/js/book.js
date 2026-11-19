// Public booking: single modal dialog + idempotency mint. No framework deps.
document.addEventListener('DOMContentLoaded', () => {
  const mint = () => {
    try {
      return crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + '-' + Math.random().toString(16).slice(2);
    } catch (e) {
      return String(Date.now());
    }
  };
  const iso = (d) => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  const pretty = (isoStr) => {
    if (!isoStr) return '';
    const [y, m, d] = isoStr.split('-').map(Number);
    return new Date(y, m - 1, d).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
  };
  const parseISO = (s) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || '');
    if (!m) return null;
    const d = new Date(+m[1], +m[2] - 1, +m[3]);
    return isNaN(d) ? null : d;
  };
  // Panels drop down from their own pill segment (not bar-centered).
  // On narrow screens they are fixed bottom sheets (see CSS), so skip JS.
  const isNarrow = () => window.matchMedia('(max-width: 43.99rem)').matches;
  const positionPanel = (p, trigger) => {
    if (!p || !trigger) return;
    if (isNarrow()) { p.style.left = ''; p.style.right = ''; p.style.transform = ''; return; }
    const bar = document.querySelector('.pill-bar');
    if (!bar) return;
    p.style.left = trigger.offsetLeft + 'px';
    p.style.right = 'auto';
    p.style.transform = 'none';
    const maxLeft = Math.max(0, bar.clientWidth - p.offsetWidth - 8);
    if (trigger.offsetLeft > maxLeft) p.style.left = maxLeft + 'px';
  };
  // ---- Esidai dual-month calendar dropdown, anchored under the pill bar ----
  const pillDates = document.querySelector('[data-pill-dates]');
  const pillDatesLabel = document.querySelector('[data-pill-dates-label]');
  const searchForm = document.querySelector('form.search');
  const ciHid = document.querySelector('.search input[name="ci"]');
  const coHid = document.querySelector('.search input[name="co"]');
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const maxDate = new Date(today.getFullYear() + 1, today.getMonth(), today.getDate());
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  const firstOfMonth = (d) => new Date(d.getFullYear(), d.getMonth(), 1);
  const panel = document.createElement('div');
  panel.className = 'pill-panel';
  panel.setAttribute('data-panel-dates', '1');
  panel.hidden = true;
  panel.innerHTML = '<div class="cal-head"><button type="button" class="cal-nav" data-cal-nav="-1" aria-label="Previous month">‹</button><span class="cal-hint">Select dates</span><button type="button" class="cal-nav" data-cal-nav="1" aria-label="Next month">›</button></div>' +
    '<div class="cal-months" data-cal-months="1"></div>' +
    '<div class="cal-foot"><span data-cal-nights="1"></span><span class="cal-actions"><button type="button" data-cal-clear="1">Clear</button><button type="button" data-cal-done="1">Done</button></span></div>';
  (document.querySelector('.pill-bar') || searchForm || document.body).appendChild(panel);
  let view = new Date(today.getFullYear(), today.getMonth(), 1);
  let anchor = 'ci';
  const getSel = () => ({ ci: parseISO(ciHid ? ciHid.value : ''), co: parseISO(coHid ? coHid.value : '') });
  const setSel = (ciD, coD) => {
    if (ciHid) ciHid.value = ciD ? iso(ciD) : '';
    if (coHid) coHid.value = coD ? iso(coD) : '';
    if (pillDatesLabel) {
      pillDatesLabel.textContent = (ciD && coD) ? pretty(iso(ciD)) + ' → ' + pretty(iso(coD))
        : ciD ? pretty(iso(ciD)) + ' → …' : 'Add dates';
    }
  };
  // Fully-booked feed (/book/blocked): blocked night ISOs, cached per month key.
  // Server stays authoritative (re-checks at confirm); the calendar only greys.
  const blockedDays = new Set();
  const blockedMonths = new Set();
  const monthKey = (d) => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
  const rangeHasBlocked = (ciD, coD) => {
    if (!ciD || !coD || coD <= ciD) return false;
    for (let t = new Date(ciD); t < coD; t = new Date(t.getFullYear(), t.getMonth(), t.getDate() + 1)) {
      if (blockedDays.has(iso(t))) return true;
    }
    return false;
  };
  const fetchBlocked = (fromD, toD) => {
    const keys = [];
    for (let m = new Date(fromD.getFullYear(), fromD.getMonth(), 1); m < toD; m = new Date(m.getFullYear(), m.getMonth() + 1, 1)) {
      if (!blockedMonths.has(monthKey(m))) keys.push(monthKey(m));
    }
    if (!keys.length) return;
    keys.forEach((k) => blockedMonths.add(k));
    fetch('/book/blocked', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: { from: iso(fromD), to: iso(toD) } }),
    }).then((r) => r.json()).then((data) => {
      const list = (data && data.result && data.result.blocked) || (data && data.blocked) || [];
      if (Array.isArray(list)) list.forEach((s) => { if (typeof s === 'string' && s) blockedDays.add(s); });
      render();
    }).catch(() => { keys.forEach((k) => blockedMonths.delete(k)); });
  };
  const ensureBlocked = () => {
    fetchBlocked(new Date(view.getFullYear(), view.getMonth(), 1),
      new Date(view.getFullYear(), view.getMonth() + 2, 1));
  };
  const hideBlockedNotice = () => {
    const ntc = searchForm ? searchForm.querySelector('[data-blocked-notice]') : null;
    if (ntc) ntc.hidden = true;
  };
  const renderMonth = (host, monthDate) => {
    const { ci, co } = getSel();
    const wrap = document.createElement('section');
    wrap.className = 'cal-month';
    const title = document.createElement('h3');
    title.className = 'cal-title';
    title.textContent = MONTHS[monthDate.getMonth()] + ' ' + monthDate.getFullYear();
    wrap.appendChild(title);
    const grid = document.createElement('div');
    grid.className = 'cal-grid';
    ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'].forEach((d) => {
      const s = document.createElement('span');
      s.className = 'cal-dow';
      s.textContent = d;
      grid.appendChild(s);
    });
    const first = (new Date(monthDate.getFullYear(), monthDate.getMonth(), 1).getDay() + 6) % 7;
    for (let i = 0; i < first; i++) grid.appendChild(document.createElement('span'));
    const days = new Date(monthDate.getFullYear(), monthDate.getMonth() + 1, 0).getDate();
    for (let d = 1; d <= days; d++) {
      const dt = new Date(monthDate.getFullYear(), monthDate.getMonth(), d);
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'cal-day';
      b.textContent = String(d);
      b.setAttribute('aria-label', pretty(iso(dt)));
      // Absolute blocking: feed-listed nights and capped checkouts disable,
      // including current selection endpoints (stale links/ late feed).
      // Selection marking stays class-only; clicks attach to enabled days.
      const isBlockedDay = blockedDays.has(iso(dt));
      const cappedDay = ci && dt > ci && rangeHasBlocked(ci, dt);
      const dis = dt < today || dt > maxDate || isBlockedDay || cappedDay;
      if (dis) b.disabled = true;
      if (isBlockedDay) b.classList.add('is-blocked');
      if (ci && dt.getTime() === ci.getTime()) b.classList.add('is-start');
      if (co && dt.getTime() === co.getTime()) b.classList.add('is-end');
      if (ci && co && dt > ci && dt < co) b.classList.add('is-range');
      if (!dis) {
        b.addEventListener('click', (ev) => { ev.stopPropagation(); pick(dt); });
      }
      grid.appendChild(b);
    }
    wrap.appendChild(grid);
    host.appendChild(wrap);
  };
  const render = () => {
    const { ci, co } = getSel();
    const host = panel.querySelector('[data-cal-months]');
    host.innerHTML = '';
    renderMonth(host, view);
    renderMonth(host, new Date(view.getFullYear(), view.getMonth() + 1, 1));
    const n = panel.querySelector('[data-cal-nights]');
    if (n) {
      if (ci && co && co > ci) {
        const nights = Math.round((co - ci) / 86400000);
        n.textContent = nights + (nights === 1 ? ' night' : ' nights') + ' selected';
      } else if (ci) n.textContent = 'Now pick check-out';
      else n.textContent = 'Pick check-in, then check-out';
    }
    panel.querySelector('[data-cal-nav="-1"]').disabled = view <= firstOfMonth(today);
    panel.querySelector('[data-cal-nav="1"]').disabled =
      new Date(view.getFullYear(), view.getMonth() + 1, 1) >= firstOfMonth(maxDate);
  };
  const pick = (dt) => {
    hideBlockedNotice();
    const { ci, co } = getSel();
    if (anchor === 'ci' || (ci && co) || (ci && dt <= ci)) {
      setSel(dt, null);
      anchor = 'co';
    } else {
      setSel(ci, dt);
      anchor = 'ci';
    }
    render();
  };
  const openCal = () => {
    const gp = document.querySelector('[data-panel-guests]');
    if (gp) gp.hidden = true;
    const bp = document.querySelector('[data-panel-board]');
    if (bp) bp.hidden = true;
    const pb = document.querySelector('[data-pill-board]');
    if (pb) pb.setAttribute('aria-expanded', 'false');
    const { ci, co } = getSel();
    anchor = (!ci || (ci && co)) ? 'ci' : 'co';
    const base = anchor === 'co' && ci ? ci : (ci || today);
    view = new Date(base.getFullYear(), base.getMonth(), 1);
    render();
    ensureBlocked();
    hideBlockedNotice();
    panel.hidden = false;
    positionPanel(panel, pillDates);
    if (pillDates) pillDates.setAttribute('aria-expanded', 'true');
  };
  const closeCal = () => {
    panel.hidden = true;
    if (pillDates) pillDates.setAttribute('aria-expanded', 'false');
  };
  panel.querySelectorAll('[data-cal-nav]').forEach((b) => b.addEventListener('click', () => {
    view = new Date(view.getFullYear(), view.getMonth() + Number(b.dataset.calNav), 1);
    render();
    ensureBlocked();
  }));
  panel.querySelector('[data-cal-clear]').addEventListener('click', () => { setSel(null, null); anchor = 'ci'; hideBlockedNotice(); render(); });
  panel.querySelector('[data-cal-done]').addEventListener('click', () => { closeCal(); if (pillDates) pillDates.focus(); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !panel.hidden) { closeCal(); if (pillDates) pillDates.focus(); }
  });
  document.addEventListener('click', (e) => {
    if (panel.hidden) return;
    const t = e.target;
    // Note: picking a day re-renders the grid, detaching the clicked button
    // before this bubble-phase handler runs — so also ignore .cal-day itself.
    if (panel.contains(t)) return;
    if (t.closest && t.closest('[data-pill-dates], .cal-day')) return;
    closeCal();
  });
  if (pillDates) pillDates.addEventListener('click', () => {
    if (panel.hidden) openCal();
    else closeCal();
  });
  // Seed pretty labels from server-rendered ISO values.
  setSel(parseISO(ciHid ? ciHid.value : ''), parseISO(coHid ? coHid.value : ''));
  // Don't search dateless: open the calendar instead.
  // Backstop: a blocked night in range shows the notice instead of navigating
  // (server re-checks at confirm; this only stops obviously stale ranges).
  if (searchForm) searchForm.addEventListener('submit', (e) => {
    const sel = getSel();
    if (!sel.ci || !sel.co) {
      e.preventDefault();
      openCal();
      return;
    }
    if (rangeHasBlocked(sel.ci, sel.co)) {
      e.preventDefault();
      const ntc = searchForm.querySelector('[data-blocked-notice]');
      if (ntc) ntc.hidden = false;
    }
  });
  // ---- Esidai guest stepper dropdown, anchored under the pill bar ----
  const pillGuests = document.querySelector('[data-pill-guests]');
  const pillGuestsLabel = document.querySelector('[data-pill-guests-label]');
  const adultsHid = document.querySelector('.search input[name="adults"]');
  const childrenHid = document.querySelector('.search input[name="children"]');
  const AD_MIN = 1, CH_MIN = 0;
  // Total cap from DB (Task 1: data-max-pax on form.search, #pax-data fallback).
  const GMAX = (() => {
    const fromForm = parseInt(searchForm && searchForm.dataset ? searchForm.dataset.maxPax : '', 10);
    if (!isNaN(fromForm) && fromForm >= 1) return fromForm;
    const paxEl = document.querySelector('#pax-data span[data-max]');
    const fromPax = parseInt(paxEl ? paxEl.dataset.max : '', 10);
    if (!isNaN(fromPax) && fromPax >= 1) return fromPax;
    return 4;
  })();
  const clampInt = (v, lo, hi, fb) => {
    let n = parseInt(v, 10);
    if (isNaN(n)) n = fb;
    return Math.min(hi, Math.max(lo, n));
  };
  const guestsText = (a, c) => a + (a === 1 ? ' adult' : ' adults') +
    (c > 0 ? ' · ' + c + (c === 1 ? ' child' : ' children') : '');
  const gPanel = document.createElement('div');
  gPanel.className = 'pill-panel';
  gPanel.setAttribute('data-panel-guests', '1');
  gPanel.hidden = true;
  gPanel.innerHTML =
    '<div class="step-row"><div class="step-meta"><strong>Adults</strong><span>Ages 13+</span></div>' +
    '<div class="stepper"><button type="button" data-step-dec="adults" aria-label="Fewer adults">−</button>' +
    '<span data-step-val="adults">2</span>' +
    '<button type="button" data-step-inc="adults" aria-label="More adults">+</button></div></div>' +
    '<div class="step-row"><div class="step-meta"><strong>Children</strong><span>Ages 2–12</span></div>' +
    '<div class="stepper"><button type="button" data-step-dec="children" aria-label="Fewer children">−</button>' +
    '<span data-step-val="children">0</span>' +
    '<button type="button" data-step-inc="children" aria-label="More children">+</button></div></div>' +
    '<div class="step-foot"><span class="step-max">Max ' + GMAX + ' guests total</span>' +
    '<span class="step-actions"><button type="button" data-step-clear="1">Clear</button>' +
    '<button type="button" data-step-done="1">Done</button></span></div>';
  (document.querySelector('.pill-bar') || searchForm || document.body).appendChild(gPanel);
  const getGuests = () => ({
    a: clampInt(adultsHid ? adultsHid.value : '2', AD_MIN, GMAX, 2),
    c: clampInt(childrenHid ? childrenHid.value : '0', CH_MIN, GMAX, 0),
  });
  // last = field just incremented; it gets trimmed first when total exceeds GMAX.
  const setGuests = (a, c, last) => {
    a = clampInt(a, AD_MIN, GMAX, 2);
    c = clampInt(c, CH_MIN, GMAX, 0);
    if (a + c > GMAX) {
      if (last === 'children') {
        c = Math.max(CH_MIN, GMAX - a);
        a = Math.max(AD_MIN, GMAX - c);
      } else {
        a = Math.max(AD_MIN, GMAX - c);
        c = Math.max(CH_MIN, GMAX - a);
      }
    }
    if (adultsHid) adultsHid.value = String(a);
    if (childrenHid) childrenHid.value = String(c);
    const av = gPanel.querySelector('[data-step-val="adults"]');
    const cv = gPanel.querySelector('[data-step-val="children"]');
    if (av) av.textContent = String(a);
    if (cv) cv.textContent = String(c);
    const sm = gPanel.querySelector('.step-max');
    if (sm) sm.textContent = 'Max ' + GMAX + ' guests total';
    const ad = gPanel.querySelector('[data-step-dec="adults"]');
    const ai = gPanel.querySelector('[data-step-inc="adults"]');
    const cd = gPanel.querySelector('[data-step-dec="children"]');
    const ci2 = gPanel.querySelector('[data-step-inc="children"]');
    if (ad) ad.disabled = a <= AD_MIN;
    if (ai) ai.disabled = a >= GMAX || a + c >= GMAX;
    if (cd) cd.disabled = c <= CH_MIN;
    if (ci2) ci2.disabled = c >= GMAX || a + c >= GMAX;
    if (pillGuestsLabel) pillGuestsLabel.textContent = guestsText(a, c);
  };
  const openGuests = () => {
    closeCal();
    const bp = document.querySelector('[data-panel-board]');
    if (bp) bp.hidden = true;
    const pb = document.querySelector('[data-pill-board]');
    if (pb) pb.setAttribute('aria-expanded', 'false');
    setGuests(getGuests().a, getGuests().c);
    gPanel.hidden = false;
    positionPanel(gPanel, pillGuests);
    if (pillGuests) pillGuests.setAttribute('aria-expanded', 'true');
  };
  const closeGuests = () => {
    gPanel.hidden = true;
    if (pillGuests) pillGuests.setAttribute('aria-expanded', 'false');
  };
  gPanel.querySelectorAll('[data-step-dec],[data-step-inc]').forEach((b) => b.addEventListener('click', (ev) => {
    ev.stopPropagation();
    const g = getGuests();
    if (b.hasAttribute('data-step-dec')) {
      if (b.dataset.stepDec === 'adults') setGuests(g.a - 1, g.c, 'adults');
      else setGuests(g.a, g.c - 1, 'children');
    } else {
      if (b.dataset.stepInc === 'adults') setGuests(g.a + 1, g.c, 'adults');
      else setGuests(g.a, g.c + 1, 'children');
    }
  }));
  gPanel.querySelector('[data-step-clear]').addEventListener('click', () => setGuests(2, 0));
  gPanel.querySelector('[data-step-done]').addEventListener('click', () => { closeGuests(); if (pillGuests) pillGuests.focus(); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !gPanel.hidden) { closeGuests(); if (pillGuests) pillGuests.focus(); }
  });
  document.addEventListener('click', (e) => {
    if (gPanel.hidden) return;
    const t = e.target;
    if (gPanel.contains(t)) return;
    if (t.closest && t.closest('[data-pill-guests]')) return;
    closeGuests();
  });
  if (pillDates) pillDates.addEventListener('click', () => { if (!gPanel.hidden) closeGuests(); });
  if (pillGuests) pillGuests.addEventListener('click', () => {
    if (gPanel.hidden) openGuests();
    else closeGuests();
  });
  // Seed stepper + label from server-rendered hidden values (?adults=&children=).
  setGuests(getGuests().a, getGuests().c);
  // UI-level clamp: never submit adults<1 (server clamps too).
  if (searchForm) searchForm.addEventListener('submit', () => {
    const g = getGuests();
    setGuests(g.a, g.c);
  });
  // ---- Esidai meal-plan dropdown, options from DB (#board-data) ----
  const pillBoard = document.querySelector('[data-pill-board]');
  const pillBoardLabel = document.querySelector('[data-pill-board-label]');
  const boardHid = document.querySelector('.search input[name="board"]');
  const boardOpts = Array.from(document.querySelectorAll('#board-data span')).map((s) => ({
    code: s.dataset.code, name: s.dataset.name, desc: s.dataset.desc,
  }));
  const bPanel = document.createElement('div');
  bPanel.className = 'pill-panel';
  bPanel.setAttribute('data-panel-board', '1');
  bPanel.hidden = true;
  boardOpts.forEach((o) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'board-row';
    b.dataset.boardCode = o.code;
    b.setAttribute('aria-checked', 'false');
    b.setAttribute('role', 'radio');
    const strong = document.createElement('strong');
    strong.textContent = o.name;
    b.appendChild(strong);
    if (o.desc) {
      const small = document.createElement('small');
      small.textContent = o.desc;
      b.appendChild(small);
    }
    const tick = document.createElement('span');
    tick.className = 'board-tick';
    tick.textContent = '✓';
    tick.setAttribute('aria-hidden', 'true');
    b.appendChild(tick);
    b.addEventListener('click', (ev) => {
      ev.stopPropagation();
      setBoard(o.code);
      closeBoard();
      if (pillBoard) pillBoard.focus();
    });
    bPanel.appendChild(b);
  });
  (document.querySelector('.pill-bar') || searchForm || document.body).appendChild(bPanel);
  const setBoard = (code) => {
    if (!boardOpts.some((o) => o.code === code)) code = boardOpts.length ? boardOpts[0].code : '';
    if (boardHid) boardHid.value = code;
    bPanel.querySelectorAll('[data-board-code]').forEach((b) => {
      b.setAttribute('aria-checked', String(b.dataset.boardCode === code));
    });
    const cur = boardOpts.find((o) => o.code === code);
    if (pillBoardLabel) pillBoardLabel.textContent = cur ? cur.name : '';
  };
  const openBoard = () => {
    closeCal();
    closeGuests();
    setBoard(boardHid ? boardHid.value : '');
    bPanel.hidden = false;
    positionPanel(bPanel, pillBoard);
    if (pillBoard) pillBoard.setAttribute('aria-expanded', 'true');
  };
  const closeBoard = () => {
    bPanel.hidden = true;
    if (pillBoard) pillBoard.setAttribute('aria-expanded', 'false');
  };
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !bPanel.hidden) { closeBoard(); if (pillBoard) pillBoard.focus(); }
  });
  document.addEventListener('click', (e) => {
    if (bPanel.hidden) return;
    const t = e.target;
    if (bPanel.contains(t)) return;
    if (t.closest && t.closest('[data-pill-board]')) return;
    closeBoard();
  });
  if (pillDates) pillDates.addEventListener('click', () => { if (!bPanel.hidden) closeBoard(); });
  if (pillGuests) pillGuests.addEventListener('click', () => { if (!bPanel.hidden) closeBoard(); });
  if (pillBoard) pillBoard.addEventListener('click', () => {
    if (bPanel.hidden) openBoard();
    else closeBoard();
  });
  // Seed meal label from server-rendered hidden value (?board=).
  setBoard(boardHid ? boardHid.value : '');
  // Narrow-viewport panels are fixed sheets; drop stale desktop offsets.
  window.addEventListener('resize', () => {
    panel.hidden = true;
    gPanel.hidden = true;
    bPanel.hidden = true;
  });
  // Single booking dialog: Select buttons fill hidden room_id + summary.
  const dlg = document.getElementById('book-dialog');
  const form = dlg ? dlg.querySelector('form.book-confirm') : null;
  if (form && !form.querySelector('input[name="idem_key"]')) {
    const h = document.createElement('input');
    h.type = 'hidden';
    h.name = 'idem_key';
    h.value = mint();
    form.appendChild(h);
  }
  document.querySelectorAll('.select-room').forEach((btn) => {
    btn.addEventListener('click', () => {
      if (!dlg || !form) return;
      form.querySelector('[data-dlg-room-id]').value = btn.dataset.roomId || '';
      const roomEl = dlg.querySelector('[data-dlg-room]');
      if (roomEl) roomEl.textContent = (btn.dataset.roomType || '') + ' · ' + (btn.dataset.count || '') + ' free';
      const sumEl = dlg.querySelector('[data-dlg-summary]');
      if (sumEl) sumEl.textContent = 'Total ' + (btn.dataset.total || '') + ' · taxes included. Pay nothing now — we confirm by phone.';
      if (typeof dlg.showModal === 'function') dlg.showModal();
      else dlg.setAttribute('open', '');
    });
  });
  const closeBtn = dlg ? dlg.querySelector('[data-dlg-close]') : null;
  if (closeBtn) closeBtn.addEventListener('click', () => dlg.close());
});
