// Public booking: idempotency mint + availability hint. No framework deps.
document.addEventListener('DOMContentLoaded', () => {
  const mint = () => {
    try {
      return crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + '-' + Math.random().toString(16).slice(2);
    } catch (e) {
      return String(Date.now());
    }
  };
  // Every confirm form carries an idempotency key (server dedupes re-POSTs).
  document.querySelectorAll('form.book-confirm').forEach((f) => {
    if (!f.querySelector('input[name="idem_key"]')) {
      const h = document.createElement('input');
      h.type = 'hidden';
      h.name = 'idem_key';
      h.value = mint();
      f.appendChild(h);
    }
  });
  // Keep date inputs sane + show live availability hint (progressive).
  const ci = document.querySelector('input[name="ci"]');
  const co = document.querySelector('input[name="co"]');
  const note = document.querySelector('[data-avail-note]');
  if (ci && co) {
    const today = new Date().toISOString().slice(0, 10);
    ci.min = today;
    co.min = today;
    const refresh = async () => {
      if (!note || !ci.value || !co.value || co.value <= ci.value) return;
      try {
        const res = await fetch('/book/availability', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: { ci: ci.value, co: co.value } }),
        });
        const data = await res.json();
        const n = (data.result && data.result.rooms && data.result.rooms.length) || 0;
        note.textContent = n + (n === 1 ? ' room' : ' rooms') + ' free for these dates.';
      } catch (e) {
        /* offline hint stays empty; server render remains source of truth */
      }
    };
    ci.addEventListener('change', refresh);
    co.addEventListener('change', refresh);
    refresh();
  }
});
