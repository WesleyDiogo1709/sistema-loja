import { api, qs } from '../api.js';
import { h, clear, money, moneyInput, dateInput, field, select, modal, toast, errorToast, table, badge, fmtDate, todayISO, monthStartISO, tabs, confirmBox } from '../ui.js';
import { state, can, methodLabel } from '../state.js';

const stat = (l, v, s, kind) => h('div', { class: 'card stat' + (kind === 'bad' ? ' alert' : '') }, h('div', { class: 'l' }, l), h('div', { class: 'v' }, v), s ? h('div', { class: 's' }, s) : null);
const row = (label, value, opts = {}) => h('tr', { style: opts.bold ? { fontWeight: 700, background: '#f6f7f4' } : {} }, h('td', { style: { paddingLeft: opts.indent ? '24px' : '10px', color: opts.muted ? 'var(--muted)' : '' } }, label), h('td', { class: 'num' }, value));

export default async function ({ el }) {
  const box = h('div'); let current = 'resumo';
  el.append(tabs([['resumo', 'Resumo'], ['fluxo', 'Fluxo de caixa'], ['pagar', 'Contas a pagar'], ['receber', 'Contas a receber']], (k) => { current = k; draw(); }, current), box);
  async function draw() { clear(box); ({ resumo, fluxo, pagar, receber })[current]().catch(errorToast); }

  async function resumo() {
    const p = await api.get('/api/finance/periods');
    const hasProfit = p.day.gross_profit_cents !== undefined;
    box.append(h('div', { class: 'cards' }, stat('Faturamento de hoje', money(p.day.revenue_cents), `recebido: ${money(p.day.received_cents)}`), stat('Faturamento da semana', money(p.week.revenue_cents), `recebido: ${money(p.week.received_cents)}`), stat('Faturamento do mês', money(p.month.revenue_cents), `recebido: ${money(p.month.received_cents)}`),
      hasProfit ? stat('Resultado do mês (lucro estimado)', money(p.month.result_cents), 'após custos, taxas, despesas e garantia', p.month.result_cents < 0 ? 'bad' : '') : null));
    const from = dateInput(monthStartISO()), to = dateInput(todayISO()), out = h('div');
    const run = async () => { clear(out); const f = from.iso(), t = to.iso(); if (!f || !t) { toast('Informe datas válidas (DD/MM/AAAA).', 'bad'); return; }
      const s = await api.get('/api/finance/summary' + qs({ from: f, to: t }));
      const t1 = h('table', { class: 't' }, h('tbody', {},
        row('Vendas concluídas', money(s.sales_total_cents)), row(`${s.sales_count} venda(s); descontos concedidos ${money(s.discounts_cents)}`, '', { indent: true, muted: true }),
        row('(−) Devoluções', '−' + money(s.returns_cents)), row(`(+) Serviços entregues (${s.services_count})`, money(s.services_total_cents)), row('FATURAMENTO', money(s.revenue_cents), { bold: true }),
        hasProfit ? [row('(−) Custo real das mercadorias e peças vendidas', '−' + money(s.cost_cents)), row('LUCRO BRUTO', money(s.gross_profit_cents), { bold: true })] : null,
        row('(−) Taxas de cartão (estimadas)', '−' + money(s.card_fees_cents)), row('(−) Despesas fixas', '−' + money(s.expenses_fixed_cents)), row('(−) Despesas variáveis', '−' + money(s.expenses_variable_cents)), row('(−) Custo de garantias', '−' + money(s.warranty_cost_cents)),
        hasProfit ? row('RESULTADO DO PERÍODO', money(s.result_cents), { bold: true }) : null));
      const rec = Object.entries(s.received_by_method);
      out.append(h('div', { class: 'grid2' }, h('div', {}, h('h3', {}, 'Demonstrativo'), t1), h('div', {}, h('h3', {}, 'Recebimentos (dinheiro que entrou)'),
        table([{ label: 'Forma', render: (r) => methodLabel(r[0]) }, { label: 'Valor', render: (r) => money(r[1]), num: true }], rec, { empty: 'Sem recebimentos.' }), h('p', {}, h('b', {}, 'Total recebido: '), money(s.received_cents)),
        h('p', { class: 'muted' }, `Compras de mercadoria com vencimento no período: ${money(s.purchases_cents)} (não são despesa: viram estoque e entram no custo quando vendidas).`))),
        h('div', { class: 'alertbox', style: { marginTop: '14px' } }, 'Como ler: faturamento é o que foi vendido (vendas − devoluções + serviços entregues); recebimentos é o dinheiro que realmente entrou; lucro bruto desconta o custo real de cada unidade vendida e os descontos já estão fora do faturamento; o resultado ainda desconta taxas de cartão, despesas e garantia. Valores de cartão são estimativas conforme as taxas cadastradas.')); };
    box.append(h('h3', { style: { margin: '16px 0 8px' } }, 'Resultado por período'), h('div', { class: 'toolbar' }, field('De', from), field('Até', to), h('button', { class: 'btn primary', onclick: () => run().catch(errorToast) }, 'Calcular')), out);
    await run();
  }

  async function fluxo() {
    const from = dateInput(todayISO(-29)), to = dateInput(todayISO()), out = h('div');
    const run = async () => { clear(out); const r = await api.get('/api/finance/cashflow' + qs({ from: from.iso(), to: to.iso() }));
      out.append(h('div', { class: 'cards' }, stat('Entradas', money(r.in_cents)), stat('Saídas', money(r.out_cents)), stat('Saldo do período', money(r.in_cents - r.out_cents), '', r.in_cents - r.out_cents < 0 ? 'bad' : '')),
        table([{ label: 'Dia', render: (d) => fmtDate(d.date) }, { label: 'Entradas', render: (d) => money(d.in_cents), num: true }, { label: 'Saídas', render: (d) => (d.out_cents ? '−' + money(d.out_cents) : ''), num: true }, { label: 'Saldo acumulado', render: (d) => money(d.balance_cents), num: true },
          { label: 'Detalhe', render: (d) => [...Object.entries(d.in_detail).map(([k, v]) => `+ ${k} ${money(v)}`), ...Object.entries(d.out_detail).map(([k, v]) => `− ${k} ${money(v)}`)].join(' · ') }], r.days, { empty: 'Sem movimentação no período.' }),
        h('p', { class: 'muted' }, 'Sangrias e reforços são transferências de caixa e não entram aqui. Entradas = vendas e serviços recebidos + contas a receber recebidas; saídas = contas pagas + devoluções ao cliente.')); };
    box.append(h('div', { class: 'toolbar' }, field('De', from), field('Até', to), h('button', { class: 'btn primary', onclick: () => run().catch(errorToast) }, 'Atualizar')), out); await run();
  }

  async function pagar() {
    const st = select([['abertas', 'Em aberto'], ['pagas', 'Pagas'], ['todas', 'Todas']], 'abertas'), kind = select([['', 'Todos os tipos'], ['compra', 'Compras de mercadoria'], ['fixa', 'Despesas fixas'], ['variavel', 'Despesas variáveis']], ''), out = h('div');
    const load = async () => { const rows = await api.get('/api/payables' + qs({ status: st.value, kind: kind.value })); clear(out);
      const open = rows.filter((r) => !r.paid_at); out.append(h('p', { class: 'muted' }, `${rows.length} conta(s) · em aberto ${money(open.reduce((a, r) => a + r.amount_cents, 0))}`),
        table([{ label: 'Vencimento', render: (r) => h('span', {}, fmtDate(r.due_date), ' ', r.overdue ? badge('Vencida', 'bad') : r.due_soon ? badge('Próxima', 'warn') : null) }, { label: 'Tipo', key: 'kind_label' }, { label: 'Descrição', key: 'description' }, { label: 'Fornecedor', render: (r) => r.supplier || '' },
          { label: 'Valor', render: (r) => money(r.amount_cents), num: true }, { label: 'Situação', render: (r) => (r.paid_at ? badge('Paga em ' + fmtDate(r.paid_at), 'good') : badge('Em aberto', 'warn')) },
          { label: '', render: (r) => (can('gerenciar_financeiro') ? h('span', {}, !r.paid_at ? h('button', { class: 'btn small', onclick: () => payIt(r) }, 'Pagar') : '', ' ', !r.paid_at ? h('button', { class: 'btn small', onclick: async () => { if (await confirmBox('Excluir este lançamento?', { danger: true, okLabel: 'Excluir' })) { await api.del('/api/payables/' + r.id); load(); } } }, 'Excluir') : '') : '') }], rows, { empty: 'Nenhuma conta neste filtro.' })); };
    async function payIt(r) { const v = moneyInput(r.amount_cents), m = h('input', { placeholder: 'PIX, dinheiro, boleto...' }), d = dateInput(todayISO());
      await modal({ title: 'Registrar pagamento', size: 'narrow', content: [h('div', {}, r.description), field('Valor pago (R$)', v), field('Data do pagamento', d), field('Forma', m)], buttons: [{ label: 'Confirmar pagamento', kind: 'primary', onClick: async (close) => { await api.post(`/api/payables/${r.id}/pay`, { paid_cents: v.cents(), method: m.value, paid_date: d.iso() }); toast('Pagamento registrado.', 'good'); close(true); load(); } }] }); }
    async function add() { const k = select([['compra', 'Compra de mercadoria'], ['fixa', 'Despesa fixa (aluguel, internet...)'], ['variavel', 'Despesa variável']], 'fixa'), desc = h('input'), sup = h('input'), v = moneyInput(0), due = dateInput(todayISO(7)), rep = h('input', { type: 'number', min: 1, max: 36, value: 1 });
      await modal({ title: 'Nova conta a pagar', content: h('div', { class: 'fields' }, field('Tipo', k), field('Descrição *', desc), field('Fornecedor / credor', sup), field('Valor (R$)', v), field('Vencimento', due), field('Repetir mensalmente (vezes)', rep)),
        buttons: [{ label: 'Lançar', kind: 'primary', onClick: async (close) => { await api.post('/api/payables', { kind: k.value, description: desc.value, supplier: sup.value, amount_cents: v.cents(), due_date: due.iso(), repeat_months: +rep.value }); toast('Conta lançada.', 'good'); close(true); load(); } }] }); }
    box.append(h('div', { class: 'toolbar' }, field('Situação', st), field('Tipo', kind), can('gerenciar_financeiro') ? h('button', { class: 'btn primary', onclick: add }, '+ Nova conta') : null), out);
    st.addEventListener('change', load); kind.addEventListener('change', load); await load();
  }

  async function receber() {
    const r = await api.get('/api/finance/receivables');
    box.append(h('div', { class: 'cards' }, stat('Cartão a receber (líquido)', money(r.totals.cards_cents), 'previsão pelas taxas e prazos cadastrados'), stat('Serviços entregues com saldo', money(r.totals.service_pending_cents)), stat('Outras contas a receber', money(r.totals.manual_cents))),
      h('h3', {}, 'Pendências de serviços'), table([{ label: 'OS', render: (o) => '#' + o.id }, { label: 'Cliente', key: 'customer_name' }, { label: 'Telefone', render: (o) => o.customer_phone || '' }, { label: 'Saldo', render: (o) => money(o.balance_cents), num: true }], r.service_pending, { empty: 'Nenhuma pendência.' }),
      h('div', { class: 'row between', style: { margin: '16px 0 8px' } }, h('h3', { style: { margin: 0 } }, 'Outras contas a receber'), can('gerenciar_financeiro') ? h('button', { class: 'btn', onclick: addRec }, '+ Lançar conta a receber') : null),
      table([{ label: 'Vencimento', render: (x) => h('span', {}, fmtDate(x.due_date), ' ', x.overdue ? badge('Vencida', 'bad') : null) }, { label: 'Cliente', render: (x) => x.customer_name || '' }, { label: 'Descrição', key: 'description' }, { label: 'Valor', render: (x) => money(x.amount_cents), num: true },
        { label: '', render: (x) => (can('gerenciar_financeiro') ? h('button', { class: 'btn small', onclick: async () => { if (await confirmBox('Marcar como recebida?', { okLabel: 'Marcar como recebida' })) { await api.post(`/api/receivables/${x.id}/receive`, {}); draw(); } } }, 'Receber') : '') }], r.manual, { empty: 'Nenhuma conta lançada.' }),
      h('h3', { style: { margin: '16px 0 8px' } }, 'Previsão de recebimento de cartão (por parcela)'),
      table([{ label: 'Data prevista', render: (c) => fmtDate(c.due_date) }, { label: 'Origem', render: (c) => (c.origin === 'venda' ? 'Venda #' : 'OS #') + c.ref }, { label: 'Forma', render: (c) => methodLabel(c.method) }, { label: 'Parcela', key: 'installment' }, { label: 'Adquirente', render: (c) => c.acquirer || '—' }, { label: 'Valor líquido', render: (c) => money(c.amount_cents), num: true }], r.cards.slice(0, 200), { empty: 'Nenhum recebimento de cartão previsto. Cadastre as taxas em Configurações para estimar o valor líquido.' }));
  }
  async function addRec() {
    const desc = h('input'), v = moneyInput(0), due = dateInput(todayISO(15)), cname = h('input', { placeholder: 'Nome do cliente (opcional)' });
    await modal({ title: 'Nova conta a receber', content: [field('Descrição *', desc), field('Valor (R$)', v), field('Vencimento', due), field('Observação / cliente', cname)], buttons: [{ label: 'Lançar', kind: 'primary', onClick: async (close) => { await api.post('/api/receivables', { description: desc.value, amount_cents: v.cents(), due_date: due.iso(), notes: cname.value }); toast('Lançado.', 'good'); close(true); draw(); } }] });
  }
  await draw();
}
