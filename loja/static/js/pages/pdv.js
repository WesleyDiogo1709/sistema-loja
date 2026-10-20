import { api, qs } from '../api.js';
import { h, clear, money, moneyInput, field, select, modal, confirmBox, toast, errorToast, withAuth, openPrint, debounce, askText } from '../ui.js';
import { state, can, methodLabel } from '../state.js';
import { productDialog, customerPicker } from './shared.js';
import { refreshMe } from '../main.js';

let audioCtx = null;
function beep(ok = true) {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const o = audioCtx.createOscillator(), g = audioCtx.createGain();
    o.frequency.value = ok ? 1000 : 220; o.type = ok ? 'sine' : 'square'; g.gain.value = 0.08;
    o.connect(g); g.connect(audioCtx.destination); o.start(); o.stop(audioCtx.currentTime + (ok ? 0.07 : 0.25));
  } catch (e) { /* sem áudio */ }
}
const newToken = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));

export default async function (ctx) {
  const el = ctx.el;
  const cart = [];           // {key, kind, id, name, price, qty, discount, stock}
  let customer = null, token = newToken(), busy = false;
  const suffix = state.settings.scanner_suffix || 'enter';
  const minLen = parseInt(state.settings.scanner_min_length || '6', 10);

  const scan = h('input', { id: 'scan', placeholder: 'Passe o leitor ou digite o código / nome do produto e tecle Enter', autocomplete: 'off', autofocus: true, 'aria-label': 'Leitura de código de barras' });
  const msg = h('div', { class: 'scan-msg' });
  const cartBox = h('div', { class: 'cart' });
  const sub = h('span'), disc = h('span'), total = h('div', { class: 'big' }), count = h('span'), custLine = h('div', { class: 'muted' });
  const cashBanner = h('div');

  function say(text, kind = '') { msg.textContent = text; msg.className = 'scan-msg ' + kind; }
  function focusScan() { if (!document.querySelector('.overlay')) scan.focus(); }

  function totals() {
    const s = cart.reduce((a, i) => a + i.price * i.qty, 0), d = cart.reduce((a, i) => a + i.discount, 0);
    return { subtotal: s, discount: d, total: s - d, units: cart.reduce((a, i) => a + i.qty, 0) };
  }

  function renderCart() {
    clear(cartBox);
    if (!cart.length) {
      cartBox.append(h('div', { class: 'empty', style: { margin: '16px', border: 0 } }, 'Carrinho vazio. Passe o primeiro produto no leitor.'));
    } else {
      const body = h('tbody');
      cart.forEach((it, idx) => {
        const qtyIn = h('input', { type: 'number', min: 1, value: it.qty, disabled: it.kind === 'd', 'aria-label': 'Quantidade' });
        qtyIn.addEventListener('change', () => { setQty(it, parseInt(qtyIn.value, 10)); });
        const dec = h('button', { class: 'btn', type: 'button', disabled: it.kind === 'd', onclick: () => setQty(it, it.qty - 1) }, '−');
        const inc = h('button', { class: 'btn', type: 'button', disabled: it.kind === 'd', onclick: () => setQty(it, it.qty + 1) }, '+');
        const warn = it.kind === 'p' && it.stock < it.qty ? h('div', { class: 'badge warn' }, `estoque: ${it.stock}`) : null;
        body.append(h('tr', {},
          h('td', { class: 'name' }, it.name, warn, it.kind === 'd' ? h('div', { class: 'muted' }, 'Aparelho individual') : null),
          h('td', {}, h('span', { class: 'qty' }, dec, qtyIn, inc)),
          h('td', { class: 'num' }, money(it.price)),
          h('td', { class: 'num' }, it.discount ? '−' + money(it.discount) : ''),
          h('td', { class: 'num' }, h('b', {}, money(it.price * it.qty - it.discount))),
          h('td', {}, h('button', { class: 'btn small', type: 'button', title: 'Desconto no item', onclick: () => itemDiscount(it) }, '%'),
            ' ', h('button', { class: 'btn small', type: 'button', title: 'Remover', onclick: () => { cart.splice(idx, 1); renderCart(); focusScan(); } }, '✕'))));
      });
      cartBox.append(h('table', {}, h('thead', {}, h('tr', {}, ['Produto', 'Qtd.', 'Preço', 'Desconto', 'Total', ''].map((t) => h('th', {}, t)))), body));
      cartBox.scrollTop = cartBox.scrollHeight;
    }
    const t = totals();
    sub.textContent = money(t.subtotal); disc.textContent = t.discount ? '−' + money(t.discount) : money(0); total.textContent = money(t.total);
    count.textContent = `${t.units} ${t.units === 1 ? 'item' : 'itens'}`;
    custLine.textContent = customer ? `Cliente: ${customer.name}` : 'Sem cliente (venda balcão)';
  }

  function setQty(it, q) {
    if (!Number.isFinite(q) || q < 1) q = 1;
    it.qty = q; if (it.discount > it.price * q) it.discount = 0; renderCart(); focusScan();
  }

  function addProduct(p, qty = 1) {
    const ex = cart.find((i) => i.key === 'p' + p.id);
    if (ex) ex.qty += qty;
    else cart.push({ key: 'p' + p.id, kind: 'p', id: p.id, name: p.name, price: p.price_cents, qty, discount: 0, stock: p.qty });
    const it = cart.find((i) => i.key === 'p' + p.id);
    renderCart(); beep(true);
    say(`${p.name} adicionado${it.qty > 1 ? ` (${it.qty} un.)` : ''}`, it.stock < it.qty ? '' : 'good');
    if (it.stock < it.qty) say(`${p.name}: estoque insuficiente (${it.stock}). A venda exigirá autorização de supervisor.`, 'bad');
  }
  function addDevice(d) {
    if (d.status !== 'disponivel') { beep(false); say(`Aparelho ${d.code} não está disponível (${d.status.replace('_', ' ')}).`, 'bad'); return; }
    if (cart.some((i) => i.key === 'd' + d.id)) { beep(false); say('Este aparelho já está no carrinho.', 'bad'); return; }
    cart.push({ key: 'd' + d.id, kind: 'd', id: d.id, name: `${d.brand} ${d.model} ${d.storage || ''} ${d.color || ''} [${d.code}]`.replace(/\s+/g, ' '), price: d.price_cents, qty: 1, discount: 0 });
    renderCart(); beep(true); say(`Aparelho ${d.code} adicionado`, 'good');
  }

  async function handleInput(raw) {
    let text = raw.trim();
    scan.value = '';
    if (!text) return;
    let qty = 1;
    const m = text.match(/^(\d{1,3})\s*[*xX]\s*(.+)$/);   // 3*789100... -> 3 unidades
    if (m) { qty = parseInt(m[1], 10); text = m[2]; }
    try {
      const r = await api.get('/api/lookup' + qs({ code: text }));
      if (r.found === 'product') return addProduct(r.product, qty);
      if (r.found === 'device') return addDevice(r.device);
      const looksLikeCode = /^[0-9A-Za-z\-]{6,}$/.test(text.replace(/\s/g, '')) && !/\s/.test(text) && /\d/.test(text);
      if (!looksLikeCode) return searchDialog(text);
      beep(false); say(`Código ${r.code} não cadastrado.`, 'bad');
      if (can('gerenciar_produtos')) {
        const yes = await confirmBox(`O código ${r.code} não está cadastrado. Deseja cadastrar um novo produto com este código?`, { title: 'Código não cadastrado', okLabel: 'Cadastrar produto' });
        if (yes) { const p = await productDialog(null, { barcode: r.code }); if (p) addProduct(p, qty); }
      } else {
        toast('Código não cadastrado. Peça a um gerente para cadastrar o produto.', 'bad');
      }
    } catch (e) { beep(false); say(e.message, 'bad'); }
    finally { focusScan(); }
  }

  // ---- leitura: Enter (padrão), Tab ou detecção por velocidade (sem sufixo)
  let lastKey = 0, fast = 0, timer = null;
  scan.addEventListener('keydown', (e) => {
    const now = performance.now(); fast = (now - lastKey) < 45 ? fast + 1 : 0; lastKey = now;
    if (e.key === 'Enter') { e.preventDefault(); clearTimeout(timer); handleInput(scan.value); }
    else if (e.key === 'Tab' && suffix === 'tab' && scan.value.trim()) { e.preventDefault(); handleInput(scan.value); }
  });
  scan.addEventListener('input', () => {
    if (suffix !== 'nenhum') return;
    clearTimeout(timer);
    timer = setTimeout(() => { if (scan.value.trim().length >= minLen && fast >= minLen - 2) handleInput(scan.value); }, 90);
  });

  // ---- busca manual
  async function searchDialog(initial = '') {
    const input = h('input', { value: initial, placeholder: 'Nome, SKU, código, IMEI...', autocomplete: 'off' });
    const out = h('div', { class: 'results' });
    let closeFn = () => {}; let sel = 0; let list = [];
    const run = async () => {
      clear(out); const q = input.value.trim(); if (q.length < 2) return;
      const r = await api.get('/api/pdv/search' + qs({ q }));
      list = [...r.products.map((p) => ({ t: 'p', p })), ...r.devices.map((d) => ({ t: 'd', d }))]; sel = 0;
      if (!list.length) out.append(h('div', { class: 'empty' }, 'Nada encontrado. Confira o nome ou tente outro código.'));
      list.forEach((x, i) => {
        const label = x.t === 'p' ? [x.p.name, `${money(x.p.price_cents)} · estoque ${x.p.qty}`] : [`Aparelho: ${x.d.brand} ${x.d.model} ${x.d.storage || ''} ${x.d.color || ''}`, `${money(x.d.price_cents)} · ${x.d.code}`];
        const b = h('button', { type: 'button', class: i === 0 ? 'sel' : '' }, h('span', {}, label[0]), h('span', {}, label[1]));
        b.addEventListener('click', () => closeFn(x)); out.append(b);
      });
    };
    input.addEventListener('input', debounce(() => run().catch(errorToast), 180));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault(); sel = Math.max(0, Math.min(list.length - 1, sel + (e.key === 'ArrowDown' ? 1 : -1)));
        [...out.children].forEach((c, i) => c.classList.toggle('sel', i === sel)); out.children[sel]?.scrollIntoView({ block: 'nearest' });
      } else if (e.key === 'Enter' && list[sel]) { e.preventDefault(); e.stopPropagation(); closeFn(list[sel]); }
    }, true);
    if (initial) run().catch(errorToast);
    const pick = await modal({ title: 'Buscar produto', size: 'wide', content: [field('Digite para buscar (↑ ↓ para escolher, Enter para adicionar)', input), out], cancelLabel: 'Fechar', onOpen: (c) => { closeFn = c; } });
    if (pick) { pick.t === 'p' ? addProduct(pick.p) : addDevice(pick.d); }
    focusScan();
  }

  // ---- descontos
  async function itemDiscount(it) {
    const val = moneyInput(it.discount), pct = h('input', { type: 'number', min: 0, max: 100, step: '0.1', placeholder: '0' });
    pct.addEventListener('input', () => { const p = parseFloat(pct.value); if (p >= 0) val.setCents(Math.round(it.price * it.qty * p / 100)); });
    const ok = await modal({ title: `Desconto: ${it.name}`, size: 'narrow', content: [field('Valor do desconto (R$)', val), field('ou em porcentagem (%)', pct),
      h('div', { class: 'muted' }, `Valor do item: ${money(it.price * it.qty)}`)],
      buttons: [{ label: 'Aplicar', kind: 'primary', onClick: (close) => {
        const c = val.cents(); if (Number.isNaN(c) || c < 0 || c > it.price * it.qty) { toast('Desconto inválido: não pode passar do valor do item.', 'bad'); return; }
        it.discount = c; close(true); } }] });
    if (ok) renderCart(); focusScan();
  }
  async function saleDiscount() {
    if (!cart.length) return;
    const t = totals(); const val = moneyInput(0), pct = h('input', { type: 'number', min: 0, max: 100, step: '0.1' });
    pct.addEventListener('input', () => { const p = parseFloat(pct.value); if (p >= 0) val.setCents(Math.round(t.subtotal * p / 100)); });
    const ok = await modal({ title: 'Desconto na venda', size: 'narrow', content: [field('Valor total do desconto (R$)', val), field('ou em porcentagem (%)', pct), h('div', { class: 'muted' }, 'O desconto é dividido proporcionalmente entre os itens.')],
      buttons: [{ label: 'Aplicar', kind: 'primary', onClick: (close) => {
        const c = val.cents(); if (Number.isNaN(c) || c < 0 || c >= t.subtotal) { toast('Desconto inválido.', 'bad'); return; }
        let left = c; cart.forEach((it, i) => { const share = i === cart.length - 1 ? left : Math.floor(c * (it.price * it.qty) / t.subtotal); it.discount = Math.min(share, it.price * it.qty); left -= it.discount; });
        close(true); } }] });
    if (ok) renderCart(); focusScan();
  }

  // ---- pagamento
  async function pay() {
    if (busy) return;
    if (!cart.length) { say('Adicione ao menos um produto.', 'bad'); beep(false); return; }
    if (!state.cashOpen) { await openCashDialog(); if (!state.cashOpen) return; }
    const t = totals();
    if (t.total <= 0) { toast('O total da venda deve ser maior que zero.', 'bad'); return; }
    const lines = []; const linesBox = h('div', { style: { display: 'grid', gap: '10px' } });
    const info = h('div', { class: 'card' }), addBtn = h('button', { class: 'btn', type: 'button' }, '+ Adicionar forma de pagamento (combinar)');
    const maxInst = parseInt(state.settings.max_installments || '12', 10);
    const methods = state.methods;

    function remaining() { return t.total - lines.reduce((a, l) => a + (l.amount.cents() || 0), 0); }
    function refresh() {
      const rem = remaining(); let change = 0;
      lines.forEach((l) => { const m = methods.find((x) => x.key === l.method.value); const a = l.amount.cents() || 0;
        l.recvWrap.style.display = m.type === 'cash' ? '' : 'none'; l.instWrap.style.display = m.installments ? '' : 'none';
        if (m.type === 'cash') { const r = l.recv.cents(); if (r && r > a) change += r - a; } });
      const infoRows = [h('div', { class: 'row between' }, h('span', {}, 'Total da venda'), h('b', {}, money(t.total))),
        h('div', { class: 'row between' }, h('span', {}, rem > 0 ? 'Falta receber' : rem < 0 ? 'Valor passou do total' : 'Pagamento completo'), h('b', { style: { color: rem === 0 ? 'var(--good)' : 'var(--bad)' } }, money(Math.abs(rem))))];
      if (change) infoRows.push(h('div', { class: 'row between' }, h('span', {}, 'Troco a devolver'), h('b', { style: { fontSize: '22px' } }, money(change))));
      info.replaceChildren(...infoRows);
      const cb = document.querySelector('.overlay:last-child .modal-foot .btn.primary');
      if (cb && !cb.dataset.busy) cb.disabled = rem !== 0 || lines.length === 0;
    }
    function addLine(defaultMethod) {
      const method = select(methods.map((m) => [m.key, m.label]), defaultMethod || methods[0].key);
      const amount = moneyInput(Math.max(remaining(), 0));
      const recv = moneyInput(0, { placeholder: 'igual ao valor' });
      const inst = select(Array.from({ length: maxInst }, (_, i) => [i + 1, i === 0 ? 'À vista' : `${i + 1}x`]), 1);
      const recvWrap = field('Valor recebido', recv), instWrap = field('Parcelas', inst);
      const rm = h('button', { class: 'btn small', type: 'button', title: 'Remover', onclick: () => { lines.splice(lines.indexOf(L), 1); row.remove(); refresh(); } }, '✕');
      const row = h('div', { class: 'payline' }, field('Forma', method), field('Valor (R$)', amount), recvWrap, instWrap, rm);
      const L = { method, amount, recv, inst, recvWrap, instWrap };
      [method, amount, recv, inst].forEach((x) => x.addEventListener('input', refresh)); method.addEventListener('change', refresh);
      lines.push(L); linesBox.append(row); refresh(); amount.focus();
    }
    addBtn.addEventListener('click', () => addLine('pix'));
    const quick = h('div', { class: 'keys' }, methods.map((m) => h('button', { class: 'btn', type: 'button', onclick: () => { lines.length = 0; clear(linesBox); addLine(m.key); } }, m.label)));
    const content = [h('div', { class: 'keys' }, h('b', {}, 'Atalho:'), quick), linesBox, addBtn, info];
    addLine(methods[0].key);

    const result = await modal({ title: 'Receber pagamento', size: 'wide', content, buttons: [{
      label: 'Confirmar venda', kind: 'primary', onClick: async (close) => {
        const payments = lines.map((l) => { const m = methods.find((x) => x.key === l.method.value); const a = l.amount.cents();
          const p = { method: m.key, amount_cents: a }; if (m.type === 'cash') p.received_cents = l.recv.cents() || a; if (m.installments) p.installments = +l.inst.value; return p; });
        if (payments.some((p) => !(p.amount_cents > 0) || (p.received_cents !== undefined && Number.isNaN(p.received_cents)))) { toast('Confira os valores informados.', 'bad'); return; }
        busy = true;
        try {
          const body = (auth) => ({ client_token: token, customer_id: customer ? customer.id : null, authorization: auth,
            items: cart.map((i) => (i.kind === 'd' ? { device_id: i.id, discount_cents: i.discount } : { product_id: i.id, qty: i.qty, discount_cents: i.discount })), payments });
          const r = await withAuth((auth) => api.post('/api/sales', body(auth)), 'Esta venda precisa de autorização de um supervisor (desconto ou estoque insuficiente).');
          if (r) close(r);
        } finally { busy = false; }
      } }], onOpen: () => refresh() });
    if (result) await afterSale(result);
    focusScan();
  }

  async function afterSale(r) {
    const sale = r.sale; cart.length = 0; customer = null; token = newToken(); renderCart(); beep(true);
    const change = sale.payments.reduce((a, p) => a + p.change_cents, 0);
    say(`Venda #${sale.id} concluída.`, 'good');
    if (state.settings.auto_print_receipt === '1') openPrint(`/print/sale/${sale.id}?w=80&print=1`);
    await modal({ title: 'Venda concluída', size: 'narrow', noCancel: true, content: [h('div', { class: 'bigcheck' }, '✔'),
      h('div', { class: 'center' }, h('b', { style: { fontSize: '22px' } }, `Venda nº ${sale.id}`), h('div', {}, money(sale.total_cents))),
      change ? h('div', { class: 'alertbox good center', style: { fontSize: '20px' } }, 'Troco: ', h('b', {}, money(change))) : null],
      buttons: [{ label: 'Imprimir comprovante', onClick: () => openPrint(`/print/sale/${sale.id}?w=80&print=1`) }, { label: 'Nova venda', kind: 'primary', onClick: (close) => close(true) }] });
    refreshMe().catch(() => {});
  }

  async function openCashDialog() {
    if (!can('gerenciar_caixa')) { toast('O caixa está fechado e você não tem permissão para abri-lo. Chame um gerente.', 'bad'); return; }
    const v = moneyInput(0);
    const ok = await modal({ title: 'Abrir caixa', size: 'narrow', content: [h('p', { style: { margin: 0 } }, 'Informe o valor em dinheiro (troco) que está na gaveta agora.'), field('Valor inicial (R$)', v)],
      buttons: [{ label: 'Abrir caixa', kind: 'primary', onClick: async (close) => { const c = v.cents(); if (Number.isNaN(c)) { toast('Valor inválido.', 'bad'); return; }
        await api.post('/api/cash/open', { opening_cents: c }); await refreshMe(); close(true); } }] });
    if (ok) { toast('Caixa aberto.', 'good'); drawCash(); }
  }
  function drawCash() {
    clear(cashBanner);
    if (!state.cashOpen) cashBanner.append(h('div', { class: 'alertbox' }, 'O caixa está fechado. Abra o caixa para registrar vendas. ',
      can('gerenciar_caixa') ? h('button', { class: 'btn small primary', onclick: openCashDialog }, 'Abrir caixa') : null));
  }

  async function pickCustomer() { const c = await customerPicker(); if (c) { customer = c; renderCart(); } focusScan(); }
  async function cancelSale() {
    if (!cart.length) return;
    if (await confirmBox('Descartar todos os itens do carrinho?', { title: 'Cancelar venda atual', danger: true, okLabel: 'Descartar carrinho' })) { cart.length = 0; customer = null; token = newToken(); renderCart(); say('Carrinho descartado.'); }
    focusScan();
  }

  // ---- layout
  const btn = (label, fn, cls = '') => h('button', { class: 'btn ' + cls, type: 'button', onclick: fn }, label);
  const right = h('div', { class: 'pdv-right' },
    h('div', { class: 'line' }, h('span', {}, 'Subtotal'), sub), h('div', { class: 'line' }, h('span', {}, 'Descontos'), disc), h('div', { class: 'line' }, h('span', {}, 'Quantidade'), count),
    h('div', { class: 'pdv-total' }, h('div', { class: 'muted', style: { color: '#9bb0a7' } }, 'Total a pagar'), total),
    custLine,
    btn('Cliente (F6)', pickCustomer), can('aplicar_descontos') || true ? btn('Desconto na venda (F7)', saleDiscount) : null,
    btn('Buscar produto (F3)', () => searchDialog(scan.value.trim() ? scan.value : '')), btn('Cancelar venda (F9)', cancelSale),
    h('div', { style: { flex: 1 } }), btn('RECEBER (F8)', pay, 'pay'));
  el.append(cashBanner, h('div', { class: 'pdv' }, h('div', { class: 'pdv-left' }, h('div', { class: 'scan' }, scan), msg, cartBox), right));
  drawCash(); renderCart(); focusScan();

  // atalhos e foco permanente no campo do leitor
  const onKey = (e) => {
    if (document.querySelector('.overlay')) return;
    const map = { F3: () => searchDialog(scan.value.trim()), F6: pickCustomer, F7: saleDiscount, F8: pay, F9: cancelSale };
    if (map[e.key]) { e.preventDefault(); map[e.key](); }
  };
  document.addEventListener('keydown', onKey);
  const keepFocus = setInterval(() => {
    const a = document.activeElement;
    if (!document.querySelector('.overlay') && (!a || a === document.body || a.tagName === 'BODY')) scan.focus();
  }, 400);
  const onClickPage = (e) => { if (!e.target.closest('input, select, textarea, .modal')) setTimeout(focusScan, 0); };
  el.addEventListener('click', onClickPage);
  return () => { document.removeEventListener('keydown', onKey); clearInterval(keepFocus); };
}
