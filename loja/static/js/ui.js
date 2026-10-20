// Utilitários de interface (sem innerHTML: todo texto é inserido como texto, evitando XSS).
import { api } from './api.js';

export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'value' || k === 'checked' || k === 'disabled' || k === 'selected') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  append(el, kids);
  return el;
}
function append(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k === null || k === undefined || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
}
export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

// ---------- formatação (pt-BR) ----------
export function money(cents) {
  const n = (cents || 0) / 100;
  return 'R$ ' + n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
export function parseMoney(str) {
  let s = String(str ?? '').replace(/R\$|\s/g, '');
  if (!s) return 0;
  if (s.includes(',')) s = s.replace(/\./g, '').replace(',', '.');
  else if (/^\d+\.\d{1,2}$/.test(s)) { /* 12.50 digitado com ponto */ }
  else s = s.replace(/\./g, '');
  const n = parseFloat(s);
  return Number.isFinite(n) ? Math.round(n * 100) : NaN;
}
export function fmtDate(v) {
  if (!v) return '';
  const m = String(v).match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : v;
}
export function fmtDateTime(v) {
  if (!v) return '';
  const m = String(v).match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}` : fmtDate(v);
}
export function todayISO(offsetDays = 0) {
  const d = new Date(); d.setDate(d.getDate() + offsetDays);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
export function monthStartISO() { return todayISO().slice(0, 8) + '01'; }

// ---------- campos ----------
export function moneyInput(cents = 0, attrs = {}) {
  const el = h('input', { inputmode: 'decimal', placeholder: '0,00', autocomplete: 'off', ...attrs });
  el.value = cents ? (cents / 100).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '';
  el.addEventListener('blur', () => {
    if (el.value.trim() === '') return;
    const c = parseMoney(el.value);
    el.value = Number.isNaN(c) ? el.value : (c / 100).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  });
  el.addEventListener('focus', () => el.select());
  el.cents = () => { const c = parseMoney(el.value); return c; };
  el.setCents = (c) => { el.value = c ? (c / 100).toLocaleString('pt-BR', { minimumFractionDigits: 2 }) : ''; };
  return el;
}
export function dateInput(iso = '', attrs = {}) {
  const el = h('input', { placeholder: 'DD/MM/AAAA', inputmode: 'numeric', maxlength: 10, autocomplete: 'off', ...attrs });
  el.value = fmtDate(iso);
  el.addEventListener('input', () => {
    const d = el.value.replace(/\D/g, '').slice(0, 8);
    el.value = d.length > 4 ? `${d.slice(0, 2)}/${d.slice(2, 4)}/${d.slice(4)}` : d.length > 2 ? `${d.slice(0, 2)}/${d.slice(2)}` : d;
  });
  el.iso = () => {
    const m = el.value.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
    if (!m) return '';
    const dt = new Date(+m[3], +m[2] - 1, +m[1]);
    if (dt.getFullYear() !== +m[3] || dt.getMonth() !== +m[2] - 1 || dt.getDate() !== +m[1]) return null;
    return `${m[3]}-${m[2]}-${m[1]}`;
  };
  el.setISO = (v) => { el.value = fmtDate(v); };
  return el;
}
export function field(label, input, extraClass) { return h('label', { class: extraClass || '' }, label, input); }
export function select(options, value, attrs = {}) {
  const el = h('select', attrs);
  options.forEach((o) => {
    const [v, l] = Array.isArray(o) ? o : [o, o];
    el.append(h('option', { value: v, selected: String(v) === String(value) }, l));
  });
  return el;
}

// ---------- avisos e diálogos ----------
export function toast(msg, kind = '') {
  const t = h('div', { class: 'toast ' + kind }, msg);
  document.getElementById('toasts').append(t);
  setTimeout(() => t.remove(), kind === 'bad' ? 7000 : 3500);
}
export function errorToast(e) { toast(e && e.message ? e.message : String(e), 'bad'); }

export function modal({ title, content, size = '', buttons = [], cancelLabel = 'Cancelar', noCancel = false, onOpen = null }) {
  return new Promise((resolve) => {
    const root = document.getElementById('modal-root');
    const overlay = h('div', { class: 'overlay' });
    const previous = document.activeElement;
    let closed = false;
    const close = (value) => {
      if (closed) return; closed = true;
      overlay.remove(); document.removeEventListener('keydown', onKey, true);
      if (previous && previous.focus) previous.focus();
      resolve(value);
    };
    const foot = h('div', { class: 'modal-foot' });
    if (!noCancel) foot.append(h('button', { class: 'btn', type: 'button', onclick: () => close(undefined) }, cancelLabel));
    let primary = null;
    buttons.forEach((b) => {
      const btn = h('button', { class: 'btn ' + (b.kind || ''), type: 'button' }, b.label);
      btn.addEventListener('click', async () => {
        if (btn.disabled) return;
        btn.disabled = true;
        try { await b.onClick(close, btn); } catch (e) { errorToast(e); }
        finally { if (!closed) btn.disabled = false; }
      });
      if (b.kind === 'primary' || b.kind === 'danger') primary = btn;
      foot.append(btn);
    });
    const box = h('div', { class: 'modal ' + size, role: 'dialog', 'aria-modal': 'true' },
      h('div', { class: 'modal-head' }, h('h3', {}, title), h('button', { class: 'btn small', type: 'button', 'aria-label': 'Fechar', onclick: () => close(undefined) }, '✕')),
      h('div', { class: 'modal-body' }, content), foot);
    box.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && primary && e.target.tagName !== 'TEXTAREA' && e.target.tagName !== 'BUTTON') { e.preventDefault(); primary.click(); }
    });
    const onKey = (e) => { if (e.key === 'Escape' && root.lastChild === overlay) { e.stopPropagation(); close(undefined); } };
    document.addEventListener('keydown', onKey, true);
    overlay.append(box); root.append(overlay);
    const first = box.querySelector('input:not([type=hidden]), select, textarea') || primary;
    if (first) setTimeout(() => first.focus(), 30);
    if (onOpen) onOpen(close);
  });
}

export function confirmBox(message, { title = 'Confirmar', okLabel = 'Confirmar', danger = false } = {}) {
  return modal({ title, size: 'narrow', content: h('p', { style: { margin: 0 } }, message),
    buttons: [{ label: okLabel, kind: danger ? 'danger' : 'primary', onClick: (close) => close(true) }] }).then((v) => !!v);
}
export function askText(title, label, { required = true, min = 3, value = '', multiline = false, okLabel = 'Confirmar' } = {}) {
  const input = multiline ? h('textarea', {}, value) : h('input', { value });
  return modal({ title, size: 'narrow', content: field(label, input),
    buttons: [{ label: okLabel, kind: 'primary', onClick: (close) => {
      const v = input.value.trim();
      if (required && v.length < min) { toast(`Preencha este campo (mínimo ${min} caracteres).`, 'bad'); input.focus(); return; }
      close(v);
    } }] });
}
export function authDialog(message) {
  const u = h('input', { autocomplete: 'off', placeholder: 'usuário do supervisor' });
  const p = h('input', { type: 'password', autocomplete: 'off', placeholder: 'senha' });
  return modal({ title: 'Autorização necessária', size: 'narrow',
    content: [h('p', { style: { margin: 0 } }, message || 'Esta operação precisa da autorização de um supervisor.'), field('Usuário', u), field('Senha', p)],
    buttons: [{ label: 'Autorizar', kind: 'primary', onClick: (close) => {
      if (!u.value.trim() || !p.value) { toast('Informe usuário e senha do supervisor.', 'bad'); return; }
      close({ username: u.value.trim(), password: p.value });
    } }] });
}
// Executa fn(auth). Se o servidor pedir autorização, abre o diálogo e repete a MESMA operação.
export async function withAuth(fn, message) {
  try { return await fn(null); }
  catch (e) {
    if (e.code !== 'authorization_required') throw e;
    const auth = await authDialog(message || e.message);
    if (!auth) return undefined;
    return fn(auth);
  }
}

// ---------- tabelas ----------
export function table(columns, rows, { onRow, footer, empty = 'Nada para mostrar.', cls = '' } = {}) {
  if (!rows || !rows.length) return h('div', { class: 'empty' }, empty);
  const head = h('tr', {}, columns.map((c) => h('th', { class: c.num ? 'num' : '' }, c.label)));
  const body = h('tbody', {}, rows.map((r) => {
    const tr = h('tr', { class: onRow ? 'click' : '' }, columns.map((c) => {
      const v = c.render ? c.render(r) : r[c.key];
      return h('td', { class: c.num ? 'num' : (c.cls || '') }, v === null || v === undefined ? '' : v);
    }));
    if (onRow) tr.addEventListener('click', (e) => { if (!e.target.closest('button, a, input')) onRow(r); });
    return tr;
  }));
  const t = h('table', { class: 't ' + cls }, h('thead', {}, head), body);
  if (footer) t.append(h('tfoot', {}, h('tr', {}, columns.map((c, i) => h('td', { class: c.num ? 'num' : '' }, footer[c.key] !== undefined ? footer[c.key] : (i === 0 ? 'Total' : ''))))));
  return h('div', { class: 'tablewrap' }, t);
}
export function badge(text, kind = '') { return h('span', { class: 'badge ' + kind }, text); }
export function tabs(items, onSelect, current) {
  const wrap = h('div', { class: 'tabs' });
  items.forEach(([key, label]) => {
    const b = h('button', { type: 'button', class: key === current ? 'active' : '' }, label);
    b.addEventListener('click', () => { [...wrap.children].forEach((c) => c.classList.remove('active')); b.classList.add('active'); onSelect(key); });
    wrap.append(b);
  });
  return wrap;
}
export function debounce(fn, ms = 250) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
export function openPrint(url) { window.open(url, '_blank', 'width=420,height=720'); }
export function formFields(spec) {
  // spec: [{key,label,input,wide}] -> retorna {el, inputs}
  const inputs = {};
  const el = h('div', { class: 'fields' }, spec.map((s) => { inputs[s.key] = s.input; return field(s.label, s.input, s.wide ? 'wide' : ''); }));
  return { el, inputs };
}
export const STATUS_DEVICE = { disponivel: ['Disponível', 'good'], reservado: ['Reservado', 'warn'], vendido: ['Vendido', ''], em_teste: ['Em teste', 'info'], em_manutencao: ['Em manutenção', 'warn'], devolvido: ['Devolvido', 'bad'] };
export { api };
