import { api, qs } from '../api.js';
import { h, clear, field, money, badge } from '../ui.js';
import { state } from '../state.js';

export default async function ({ el }) {
  const input = h('input', { placeholder: 'Clique aqui e passe o leitor em qualquer código de barras', autocomplete: 'off', style: { fontSize: '20px', padding: '14px', border: '2px solid var(--accent)' } });
  const log = h('div', { class: 'scanner-log' }, 'Aguardando leitura...');
  const result = h('div');
  let times = [], buf = '';
  const keys = [];
  input.addEventListener('keydown', async (e) => {
    const t = performance.now(); times.push(t); keys.push(`${e.key === ' ' ? 'Espaço' : e.key}`);
    if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault(); const code = input.value.trim(); input.value = '';
      const gaps = times.slice(1).map((v, i) => v - times[i]).filter((g) => g > 0); const avg = gaps.length ? gaps.reduce((a, b) => a + b, 0) / gaps.length : 0;
      const kind = code.length >= 4 && avg > 0 && avg < 40 ? 'leitor (digitação muito rápida)' : 'digitação manual (lenta)';
      const terminator = e.key === 'Enter' ? 'Enter' : 'Tab';
      log.textContent = [`Leitura: ${code || '(vazia)'}`, `Caracteres: ${code.length}`, `Terminador enviado: ${terminator}`, `Intervalo médio entre teclas: ${avg.toFixed(1)} ms → ${kind}`, `Teclas recebidas: ${keys.join(' ')}`].join('\n');
      times = []; keys.length = 0; clear(result); if (!code) return;
      if (/[^0-9A-Za-z\-]/.test(code)) result.append(h('div', { class: 'alertbox bad' }, 'Atenção: o código contém caracteres estranhos. Isso costuma indicar que o leitor está configurado com outro layout de teclado. Consulte as instruções do leitor para escolher "Português Brasil/ABNT2" ou "US", conforme o teclado do Windows.'));
      try {
        const chk = await api.get('/api/barcode/check' + qs({ code })); const lk = await api.get('/api/lookup' + qs({ code }));
        result.append(h('div', { class: 'card' }, h('dl', { class: 'kv' }, h('dt', {}, 'Tipo'), h('dd', {}, chk.valid ? chk.type : 'Inválido'), chk.valid ? null : [h('dt', {}, 'Aviso'), h('dd', {}, chk.message)],
          h('dt', {}, 'No sistema'), h('dd', {}, lk.found === 'product' ? `Produto: ${lk.product.name} — ${money(lk.product.price_cents)} (estoque ${lk.product.qty})` : lk.found === 'device' ? `Aparelho: ${lk.device.brand} ${lk.device.model} [${lk.device.code}]` : 'Não cadastrado'))));
      } catch (ex) { result.append(h('div', { class: 'alertbox bad' }, ex.message)); }
    }
  });
  el.append(h('div', { class: 'card', style: { maxWidth: '760px' } }, h('h3', {}, 'Teste do leitor de código de barras'),
    h('p', { class: 'muted' }, 'Leitores USB e Bluetooth que funcionam como teclado (HID) não precisam de driver. Esta tela mostra exatamente o que o leitor envia. Configurado para terminar com: ',
      h('b', {}, ({ enter: 'Enter', tab: 'Tab', nenhum: 'nenhum sufixo (detecção por velocidade)' })[state.settings.scanner_suffix] || 'Enter'), '. Altere em Configurações.'),
    field('Campo de teste', input), h('div', { style: { height: '10px' } }), log, h('div', { style: { height: '10px' } }), result));
  input.focus();
}
