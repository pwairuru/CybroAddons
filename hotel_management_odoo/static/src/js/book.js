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
  // ---- Esidai calendar popup (the native picker cannot be styled) ----
  const rangeShow = document.querySelector('.search input[data-cal-show="range"]');
  const ciHid = document.querySelector('.search input[name="ci"]');
  const coHid = document.querySelector('.search input[name="co"]');
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const maxDate = new Date(today.getFullYear() + 1, today.getMonth(), today.getDate());
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  const panel = document.createElement('div');
  panel.className = 'cal-panel';
  panel.hidden = true;
  panel.innerHTML = '<div class="cal-head"><button type="button" class="cal-nav" data-cal-nav="-1" aria-label="Previous month">‹</button><span class="cal-title" data-cal-title="1"></span><button type="button" class="cal-nav" data-cal-nav="1" aria-label="Next month">›</button></div>' +
    '<div class="cal-grid" data-cal-grid="1"></div>' +
    '<div class="cal-foot"><span data-cal-nights="1"></span><span class="cal-actions"><button type="button" data-cal-clear="1">Clear</button><button type="button" data-cal-done="1">Done</button></span></div>';
  document.body.appendChild(panel);
  let view = new Date(today.getFullYear(), today.getMonth(), 1);
  let anchor = 'ci';
  const getSel = () => ({ ci: parseISO(ciHid ? ciHid.value : ''), co: parseISO(coHid ? coHid.value : '') });
  const setSel = (ciD, coD) => {
    if (ciHid) ciHid.value = ciD ? iso(ciD) : '';
    if (coHid) coHid.value = coD ? iso(coD) : '';
    if (rangeShow) {
      rangeShow.value = (ciD && coD) ? pretty(iso(ciD)) + ' → ' + pretty(iso(coD))
        : ciD ? pretty(iso(ciD)) + ' → …' : '';
    }
  };
  const render = () => {
    const { ci, co } = getSel();
    panel.querySelector('[data-cal-title]').textContent = MONTHS[view.getMonth()] + ' ' + view.getFullYear();
    const grid = panel.querySelector('[data-cal-grid]');
    grid.innerHTML = '';
    ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'].forEach((d) => {
      const s = document.createElement('span');
      s.className = 'cal-dow';
      s.textContent = d;
      grid.appendChild(s);
    });
    const first = (new Date(view.getFullYear(), view.getMonth(), 1).getDay() + 6) % 7;
    for (let i = 0; i < first; i++) grid.appendChild(document.createElement('span'));
    const days = new Date(view.getFullYear(), view.getMonth() + 1, 0).getDate();
    for (let d = 1; d <= days; d++) {
      const dt = new Date(view.getFullYear(), view.getMonth(), d);
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'cal-day';
      b.textContent = String(d);
      b.setAttribute('aria-label', pretty(iso(dt)));
      const dis = dt < today || dt > maxDate;
      if (dis) b.disabled = true;
      if (!dis) {
        if (ci && dt.getTime() === ci.getTime()) b.classList.add('is-start');
        if (co && dt.getTime() === co.getTime()) b.classList.add('is-end');
        if (ci && co && dt > ci && dt < co) b.classList.add('is-range');
        b.addEventListener('click', () => pick(dt));
      }
      grid.appendChild(b);
    }
    const n = panel.querySelector('[data-cal-nights]');
    if (n) {
      if (ci && co && co > ci) {
        const nights = Math.round((co - ci) / 86400000);
        n.textContent = nights + (nights === 1 ? ' night' : ' nights') + ' selected';
      } else if (ci) n.textContent = 'Now pick check-out';
      else n.textContent = 'Pick check-in, then check-out';
    }
    panel.querySelector('[data-cal-nav="-1"]').disabled = view <= new Date(today.getFullYear(), today.getMonth(), 1);
    panel.querySelector('[data-cal-nav="1"]').disabled = view >= new Date(maxDate.getFullYear(), maxDate.getMonth(), 1);
  };
  const pick = (dt) => {
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
    const { ci, co } = getSel();
    anchor = (!ci || (ci && co)) ? 'ci' : 'co';
    const base = anchor === 'co' && ci ? ci : (ci || today);
    view = new Date(base.getFullYear(), base.getMonth(), 1);
    render();
    panel.hidden = false;
  };
  const closeCal = () => { panel.hidden = true; };
  panel.querySelectorAll('[data-cal-nav]').forEach((b) => b.addEventListener('click', () => {
    view = new Date(view.getFullYear(), view.getMonth() + Number(b.dataset.calNav), 1);
    render();
  }));
  panel.querySelector('[data-cal-clear]').addEventListener('click', () => { setSel(null, null); anchor = 'ci'; render(); });
  panel.querySelector('[data-cal-done]').addEventListener('click', closeCal);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeCal(); });
  document.addEventListener('click', (e) => {
    if (!panel.hidden && !panel.contains(e.target) && !e.target.closest('.search')) closeCal();
  });
  if (rangeShow) {
    rangeShow.addEventListener('click', () => openCal());
    rangeShow.addEventListener('focus', () => openCal());
  }
  // Seed pretty labels from server-rendered ISO values.
  setSel(parseISO(ciHid ? ciHid.value : ''), parseISO(coHid ? coHid.value : ''));
  // Don't search dateless: open the calendar instead.
  const searchForm = document.querySelector('form.search');
  if (searchForm) searchForm.addEventListener('submit', (e) => {
    if (!getSel().ci || !getSel().co) {
      e.preventDefault();
      openCal();
    }
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
      if (roomEl) roomEl.textContent = (btn.dataset.roomName || '') + ' · ' + (btn.dataset.roomType || '');
      const sumEl = dlg.querySelector('[data-dlg-summary]');
      if (sumEl) sumEl.textContent = 'Total ' + (btn.dataset.total || '') + ' · taxes included. Pay nothing now — we confirm by phone.';
      if (typeof dlg.showModal === 'function') dlg.showModal();
      else dlg.setAttribute('open', '');
    });
  });
  const closeBtn = dlg ? dlg.querySelector('[data-dlg-close]') : null;
  if (closeBtn) closeBtn.addEventListener('click', () => dlg.close());
});
