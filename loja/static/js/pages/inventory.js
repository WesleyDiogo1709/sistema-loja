import { api } from '../api.js';
import { h, clear, field, table, modal, toast, errorToast, badge, fmtDateTime, confirmBox, askText } from '../ui.js';

export default async function ({ el }) {
  const box = h('div'); el.append(box);
  async function list() {
    clear(box);
    const rows = await api.get('/api/inventory');
    const open = rows.find((r) => r.status === 'aberto');
    box.append(h('div', { class: 'toolbar' }, open ? h('button', { class: 'btn primary', onclick: () => count(open.id) }, 'Continuar inventário aberto') : h('button', { class: 'btn primary', onclick: async () => {
      const name = await askText('Novo inventário', 'Nome (ex.: Inventário de outubro)', { required: false, okLabel: 'Iniciar' }); if (name === undefined) return;
      const r = await api.post('/api/inventory', { name }); count(r.id); } }, 'Iniciar novo inventário')),
      h('p', { class: 'muted' }, 'Conte os produtos passando cada unidade no leitor de código de barras. Nada muda no estoque até você finalizar o inventário.'),
      table([{ label: 'Nº', key: 'id' }, { label: 'Nome', key: 'name' }, { label: 'Início', render: (r) => fmtDateTime(r.created_at) }, { label: 'Responsável', key: 'user_name' },
        { label: 'Situação', render: (r) => badge(r.status, r.status === 'aberto' ? 'warn' : r.status === 'finalizado' ? 'good' : '') }], rows, { onRow: (r) => count(r.id), empty: 'Nenhum inventário realizado.' }));
  }
  async function count(id) {
    clear(box);
    const d = await api.get('/api/inventory/' + id);
    const isOpen = d.count.status === 'aberto';
    const scan = h('input', { placeholder: 'Passe o leitor aqui (cada leitura soma 1 unidade)', autocomplete: 'off', style: { fontSize: '18px', padding: '12px', border: '2px solid var(--accent)' } });
    const msg = h('div', { class: 'scan-msg' });
    const tbl = h('div');
    const draw = (data) => {
      clear(tbl);
      tbl.append(h('h3', {}, `Contados (${data.items.length})`), table([{ label: 'Produto', key: 'name' }, { label: 'Sistema', key: 'system_qty', num: true }, { label: 'Contado', key: 'counted_qty', num: true },
        { label: 'Diferença', render: (r) => badge(r.diff === 0 ? 'Confere' : (r.diff > 0 ? '+' : '') + r.diff, r.diff === 0 ? 'good' : 'bad'), num: true },
        isOpen ? { label: '', render: (r) => h('button', { class: 'btn small', onclick: async () => { const v = await askText('Corrigir contagem', 'Quantidade contada para ' + r.name, { min: 1, value: String(r.counted_qty) }); if (v === null || v === undefined) return; const q = parseInt(v, 10); if (!(q >= 0)) { toast('Informe um número inteiro maior ou igual a zero.', 'bad'); return; } await api.put(`/api/inventory/${id}/item`, { product_id: r.product_id, qty: q }); count(id); } }, 'Corrigir') } : null].filter(Boolean), data.items, { empty: 'Nenhum produto lido ainda.' }),
        h('h3', { style: { marginTop: '16px' } }, `Ainda não lidos (${data.uncounted.length})`), table([{ label: 'Produto', key: 'name' }, { label: 'Sistema', key: 'system_qty', num: true }], data.uncounted, { empty: 'Todos os produtos com saldo foram lidos.' }));
    };
    box.append(h('div', { class: 'row between' }, h('h3', {}, `${d.count.name} — ${d.count.status}`), h('button', { class: 'btn', onclick: list }, '← Voltar')));
    if (isOpen) {
      box.append(field('Leitura de código de barras', scan), msg);
      scan.addEventListener('keydown', async (e) => {
        if (e.key !== 'Enter') return; e.preventDefault(); const code = scan.value.trim(); scan.value = ''; if (!code) return;
        try { const r = await api.post(`/api/inventory/${id}/scan`, { code }); msg.className = 'scan-msg good'; msg.textContent = `${r.product.name}: ${r.counted_qty} contado(s) (sistema: ${r.system_qty})`; draw(await api.get('/api/inventory/' + id)); }
        catch (ex) { msg.className = 'scan-msg bad'; msg.textContent = ex.message; }
        scan.focus();
      });
      box.append(h('div', { class: 'row', style: { margin: '10px 0' } }, h('button', { class: 'btn primary', onclick: async () => {
        const zero = d.uncounted.length ? await confirmBox(`Há ${d.uncounted.length} produto(s) com saldo que não foram lidos. Considerá-los como ZERO no estoque? (Escolha "Cancelar" para manter o saldo deles.)`, { title: 'Produtos não lidos', okLabel: 'Sim, zerar não lidos' }) : false;
        if (!(await confirmBox('Finalizar o inventário e ajustar o estoque conforme a contagem? Esta ação gera movimentações de ajuste.', { okLabel: 'Finalizar e ajustar' }))) return;
        const r = await api.post(`/api/inventory/${id}/finish`, { zero_uncounted: zero }); toast(`Inventário finalizado: ${r.adjusted} produto(s) ajustado(s).`, 'good'); list(); } }, 'Finalizar e ajustar estoque'),
        h('button', { class: 'btn', onclick: async () => { if (await confirmBox('Cancelar este inventário? A contagem será descartada.', { danger: true, okLabel: 'Cancelar inventário' })) { await api.post(`/api/inventory/${id}/cancel`); list(); } } }, 'Cancelar inventário')));
      scan.focus(); setTimeout(() => scan.focus(), 50);
    }
    box.append(tbl); draw(d);
  }
  await list();
}
