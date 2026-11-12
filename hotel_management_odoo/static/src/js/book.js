// Public booking: single modal dialog + idempotency mint. No framework deps.
document.addEventListener('DOMContentLoaded', () => {
  const mint = () => {
    try {
      return crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + '-' + Math.random().toString(16).slice(2);
    } catch (e) {
      return String(Date.now());
    }
  };
  // Date sanity.
  const ci = document.querySelector('.search input[name="ci"]');
  const co = document.querySelector('.search input[name="co"]');
  if (ci && co) {
    const today = new Date().toISOString().slice(0, 10);
    ci.min = today;
    co.min = today;
  }
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
