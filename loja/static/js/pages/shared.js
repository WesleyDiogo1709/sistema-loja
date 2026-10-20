import { api, qs } from '../api.js';
import { h, clear, field, formFields, moneyInput, modal, toast, debounce, select } from '../ui.js';
import { can } from '../state.js';

export async function productDialog(product = null, prefill = {}) {
  const p = { ...(product || {}), ...prefill };
  const [cats, sups] = await Promise.all([
    api.get('/api/categories').catch(() => []),
    api.get('/api/suppliers').catch(() => []),
  ]);
  const catList = h('datalist', { id: 'dl-cat' }, cats.map((c) => h('option', { value: c })));
  const supList = h('datalist', { id: 'dl-sup' }, sups.map((s) => h('option', { value: s.name })));
  const i = {
    name: h('input', { value: p.name || '', required: true }),
    category: h('input', { value: p.category || '', list: 'dl-cat' }),
    brand: h('input', { value: p.brand || '' }), model: h('input', { value: p.model || '' }),
    barcode: h('input', { value: p.barcode || '', placeholder: 'Leia ou digite (EAN-13, EAN-8, UPC)', inputmode: 'numeric' }),
    internal: h('input', { type: 'checkbox', checked: p.barcode_type === 'INTERNO' }),
    sku: h('input', { value: p.sku || '', placeholder: 'Automático se vazio' }),
    supplier: h('input', { value: p.supplier || '', list: 'dl-sup' }),
    cost: moneyInput(p.cost_cents || 0), price: moneyInput(p.price_cents || 0),
    qty: h('input', { type: 'number', min: 0, value: 0 }), min_qty: h('input', { type: 'number', min: 0, value: p.min_qty ?? 0 }),
    location: h('input', { value: p.location || '', placeholder: 'Ex.: Prateleira A2' }),
    warranty: h('input', { type: 'number', min: 90, value: p.warranty_days || 90 }),
    description: h('textarea', {}, p.description || ''), notes: h('textarea', {}, p.notes || ''),
  };
  const msg = h('div', { class: 'muted' });
  const checkCode = debounce(async () => {
    const code = i.barcode.value.trim();
    if (!code) { msg.textContent = ''; return; }
    try {
      const r = await api.get('/api/barcode/check' + qs({ code, internal: i.internal.checked ? 1 : '' }));
      if (!r.valid) { msg.textContent = r.message; msg.style.color = 'var(--bad)'; return; }
      if (r.registered && r.registered.id !== (product || {}).id) { msg.textContent = `Este código já está no produto "${r.registered.name}".`; msg.style.color = 'var(--bad)'; return; }
      msg.textContent = `Código válido (${r.type}).`; msg.style.color = 'var(--good)';
    } catch (e) { /* ignora */ }
  }, 300);
  i.barcode.addEventListener('input', checkCode); i.internal.addEventListener('change', checkCode);
  i.barcode.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); i.sku.focus(); } }, true);
  if (p.barcode) checkCode();
  const costAllowed = can('ver_custos'), priceAllowed = !product || can('alterar_precos');
  if (!priceAllowed) i.price.disabled = true;
  const fields = h('div', { class: 'fields' },
    field('Nome do produto *', i.name, 'wide'), field('Categoria', i.category), field('Marca', i.brand), field('Modelo', i.model),
    h('div', { class: 'wide' }, field('Código de barras', i.barcode), msg, h('label', { class: 'check' }, i.internal, 'É um código interno (não segue EAN/UPC)')),
    field('SKU / código interno', i.sku), field('Fornecedor', i.supplier),
    costAllowed ? field('Custo de aquisição (R$)', i.cost) : null, field('Preço de venda (R$)', i.price),
    product ? null : field('Quantidade inicial', i.qty), field('Estoque mínimo', i.min_qty), field('Localização no estoque', i.location),
    field('Garantia (dias, mínimo 90)', i.warranty), field('Descrição', i.description, 'wide'), field('Observações', i.notes, 'wide'), catList, supList);
  return modal({ title: product ? 'Editar produto' : 'Novo produto', size: 'wide', content: fields, buttons: [{
    label: 'Salvar produto', kind: 'primary', onClick: async (close) => {
      const body = { name: i.name.value, category: i.category.value, brand: i.brand.value, model: i.model.value, barcode: i.barcode.value,
        barcode_internal: i.internal.checked, sku: i.sku.value, supplier: i.supplier.value, price_cents: i.price.cents(), min_qty: +i.min_qty.value || 0,
        location: i.location.value, description: i.description.value, notes: i.notes.value, warranty_days: +i.warranty.value || 90 };
      if (costAllowed) body.cost_cents = i.cost.cents();
      if (Number.isNaN(body.price_cents) || (costAllowed && Number.isNaN(body.cost_cents))) { toast('Confira os valores em reais.', 'bad'); return; }
      if (!product) body.qty = +i.qty.value || 0;
      const saved = product ? await api.put('/api/products/' + product.id, body) : await api.post('/api/products', body);
      toast('Produto salvo.', 'good'); close(saved);
    } }] });
}

export async function customerDialog(c = null) {
  const i = { name: h('input', { value: c?.name || '' }), phone: h('input', { value: c?.phone || '', placeholder: '(00) 00000-0000' }), email: h('input', { type: 'email', value: c?.email || '' }),
    doc: h('input', { value: c?.doc || '', placeholder: 'Opcional' }), notes: h('textarea', {}, c?.notes || '') };
  return modal({ title: c ? 'Editar cliente' : 'Novo cliente', content: h('div', { class: 'fields' },
    field('Nome *', i.name, 'wide'), field('Telefone', i.phone), field('E-mail (opcional)', i.email), field('CPF/CNPJ (opcional)', i.doc, 'wide'), field('Observações', i.notes, 'wide')),
    buttons: [{ label: 'Salvar', kind: 'primary', onClick: async (close) => {
      const body = { name: i.name.value, phone: i.phone.value, email: i.email.value, doc: i.doc.value, notes: i.notes.value };
      if (c) { await api.put('/api/customers/' + c.id, body); close({ ...c, ...body }); }
      else { const r = await api.post('/api/customers', body); close({ id: r.id, ...body }); }
      toast('Cliente salvo.', 'good');
    } }] });
}

export function customerPicker() {
  const input = h('input', { placeholder: 'Nome, telefone ou CPF/CNPJ', autocomplete: 'off' });
  const out = h('div', { class: 'results' });
  let closeFn = () => {};
  const search = debounce(async () => {
    clear(out);
    try {
      const rows = await api.get('/api/customers' + qs({ q: input.value.trim() }));
      if (!rows.length) out.append(h('div', { class: 'empty' }, 'Nenhum cliente encontrado.'));
      rows.slice(0, 15).forEach((r) => { const b = h('button', { type: 'button' }, h('span', {}, r.name), h('span', { class: 'muted' }, r.phone || '')); b.addEventListener('click', () => closeFn(r)); out.append(b); });
    } catch (e) { toast(e.message, 'bad'); }
  }, 200);
  input.addEventListener('input', search);
  search();
  return modal({ title: 'Selecionar cliente', content: [field('Buscar cliente', input), out], onOpen: (close) => { closeFn = close; },
    buttons: [{ label: 'Novo cliente', onClick: async (close) => { const c = await customerDialog(); if (c) close(c); } }] });
}

export async function loadMethods() { return api.get('/api/me').then((m) => m.payment_methods); }
export { select };
