import { api } from '../api.js';
import { h, clear, money, moneyInput, field, modal, toast, errorToast, table, badge, fmtDateTime, select, confirmBox } from '../ui.js';
import { state, can, methodLabel } from '../state.js';
import { refreshMe } from '../main.js';

export default async function ({ el }) {
  const box = h('div'); el.append(box);
  async function draw() {
    clear(box);
    const c = await api.get('/api/cash');
    if (!c.open) {
      const v = moneyInput(0);
      box.append(h('div', { class: 'card', style: { maxWidth: '460px' } }, h('h3', {}, 'Caixa fechado'), h('p', {}, 'Informe o dinheiro que está na gaveta para começar o dia.'),
        field('Valor inicial / troco (R$)', v), h('div', { style: { marginTop: '12px' } }, can('gerenciar_caixa') ? h('button', { class: 'btn primary', onclick: async () => {
          try { const n = v.cents(); if (Number.isNaN(n)) throw new Error('Valor inválido.'); await api.post('/api/cash/open', { opening_cents: n }); await refreshMe(); toast('Caixa aberto.', 'good'); draw(); } catch (e) { errorToast(e); } } }, 'Abrir caixa') : 'Você não tem permissão para abrir o caixa.')));
      if (can('ver_financeiro')) { const rows = await api.get('/api/cash/sessions'); box.append(h('h3', { style: { margin: '20px 0 8px' } }, 'Caixas anteriores'), sessionsTable(rows)); }
      return;
    }
    if (c.expected_cash_cents === undefined) { box.append(h('div', { class: 'alertbox good' }, 'Caixa aberto.')); return; }
    const methods = Object.entries(c.by_method);
    box.append(h('div', { class: 'cards' },
      h('div', { class: 'card stat' }, h('div', { class: 'l' }, 'Dinheiro esperado na gaveta'), h('div', { class: 'v' }, money(c.expected_cash_cents)), h('div', { class: 's' }, `aberto em ${fmtDateTime(c.opened_at)} por ${c.opened_by}`)),
      h('div', { class: 'card stat' }, h('div', { class: 'l' }, 'Vendas no caixa'), h('div', { class: 'v' }, money(c.sales_total_cents)), h('div', { class: 's' }, `${c.sales_count} venda(s) · serviços recebidos ${money(c.service_received_cents)}`)),
      h('div', { class: 'card stat' }, h('div', { class: 'l' }, 'Sangrias / reforços / devoluções'), h('div', { class: 'v' }, `${money(c.sangria_cents)}`), h('div', { class: 's' }, `reforço ${money(c.reforco_cents)} · devoluções em dinheiro ${money(c.refunds_cents)}`))),
      h('div', { class: 'grid2' },
        h('div', { class: 'card' }, h('h3', {}, 'Recebido por forma de pagamento'), table([{ label: 'Forma', render: (r) => methodLabel(r[0]) }, { label: 'Total', render: (r) => money(r[1]), num: true }], methods, { empty: 'Sem recebimentos ainda.' }),
          h('p', { class: 'muted' }, 'Apenas "dinheiro" entra no valor esperado da gaveta.')),
        h('div', { class: 'card' }, h('h3', {}, 'Movimentações'), table([{ label: 'Hora', render: (r) => fmtDateTime(r.created_at) }, { label: 'Tipo', render: (r) => ({ sangria: 'Sangria', reforco: 'Reforço', devolucao: 'Devolução' })[r.kind] }, { label: 'Valor', render: (r) => money(r.amount_cents), num: true }, { label: 'Motivo', key: 'reason' }, { label: 'Usuário', key: 'user_name' }], c.movements, { empty: 'Nenhuma sangria ou reforço.' }))),
      can('gerenciar_caixa') ? h('div', { class: 'row', style: { marginTop: '16px' } }, h('button', { class: 'btn', onclick: () => move('sangria') }, 'Sangria (retirar dinheiro)'), h('button', { class: 'btn', onclick: () => move('reforco') }, 'Reforço (colocar dinheiro)'),
        h('button', { class: 'btn danger', onclick: () => closeCash(c) }, 'Fechar caixa')) : null);
  }
  function sessionsTable(rows) {
    return table([{ label: 'Nº', key: 'id' }, { label: 'Abertura', render: (r) => fmtDateTime(r.opened_at) }, { label: 'Fechamento', render: (r) => fmtDateTime(r.closed_at) || badge('Aberto', 'warn') }, { label: 'Operador', key: 'opener' },
      { label: 'Esperado', render: (r) => (r.expected_cents == null ? '' : money(r.expected_cents)), num: true }, { label: 'Contado', render: (r) => (r.counted_cents == null ? '' : money(r.counted_cents)), num: true },
      { label: 'Diferença', render: (r) => { if (r.counted_cents == null) return ''; const d = r.counted_cents - r.expected_cents; return badge(d === 0 ? 'Confere' : (d > 0 ? 'Sobra ' : 'Falta ') + money(Math.abs(d)), d === 0 ? 'good' : 'bad'); } }, { label: 'Obs.', key: 'notes' }], rows);
  }
  async function move(kind) {
    const v = moneyInput(0), why = h('input', { placeholder: kind === 'sangria' ? 'Ex.: depósito no banco' : 'Ex.: troco extra' });
    await modal({ title: kind === 'sangria' ? 'Sangria de caixa' : 'Reforço de caixa', size: 'narrow', content: [field('Valor (R$)', v), field('Motivo', why)],
      buttons: [{ label: 'Registrar', kind: 'primary', onClick: async (close) => { await api.post('/api/cash/movement', { kind, amount_cents: v.cents(), reason: why.value }); toast('Movimentação registrada.', 'good'); close(true); draw(); } }] });
  }
  async function closeCash(c) {
    const counted = moneyInput(0), notes = h('textarea', { placeholder: 'Obrigatório se houver diferença' }), diff = h('div', { class: 'alertbox' }, 'Conte o dinheiro da gaveta e informe o valor.');
    counted.addEventListener('input', () => { const n = counted.cents(); if (Number.isNaN(n) || counted.value === '') return; const d = n - c.expected_cash_cents;
      diff.className = 'alertbox ' + (d === 0 ? 'good' : 'bad'); diff.textContent = d === 0 ? 'O valor confere com o esperado.' : `${d > 0 ? 'Sobra' : 'Falta'} de ${money(Math.abs(d))} em relação ao esperado (${money(c.expected_cash_cents)}).`; });
    await modal({ title: 'Fechar caixa', content: [h('p', { style: { margin: 0 } }, `Dinheiro esperado: `, h('b', {}, money(c.expected_cash_cents))), field('Valor contado na gaveta (R$)', counted), diff, field('Observações', notes)],
      buttons: [{ label: 'Fechar caixa', kind: 'danger', onClick: async (close) => {
        if (counted.value === '' || Number.isNaN(counted.cents())) { toast('Informe o valor contado.', 'bad'); return; }
        if (!(await confirmBox('Fechar o caixa agora? Depois disso não será possível vender até abrir um novo caixa.', { okLabel: 'Fechar caixa', danger: true }))) return;
        const r = await api.post('/api/cash/close', { counted_cents: counted.cents(), notes: notes.value });
        await refreshMe(); toast(r.difference_cents === 0 ? 'Caixa fechado. Valores conferem.' : `Caixa fechado com diferença de ${money(r.difference_cents)}.`, r.difference_cents === 0 ? 'good' : ''); close(true); draw(); } }] });
  }
  await draw();
}
