import { api, qs } from '../api.js';
import { h, clear, money, dateInput, field, select, modal, toast, errorToast, table, badge, fmtDateTime, fmtDate, tabs, confirmBox, todayISO } from '../ui.js';
import { state, can, canAny } from '../state.js';
import { refreshMe } from '../main.js';

const ROLE = { administrador: 'Administrador', gerente: 'Gerente', vendedor: 'Vendedor', tecnico: 'Técnico' };

export default async function ({ el }) {
  const items = [];
  if (can('gerenciar_config')) items.push(['loja', 'Loja e leitor'], ['pagamentos', 'Pagamentos e taxas']);
  if (can('gerenciar_usuarios')) items.push(['usuarios', 'Usuários'], ['permissoes', 'Permissões']);
  if (can('gerenciar_backup')) items.push(['backup', 'Backup e restauração']);
  if (can('gerenciar_config')) items.push(['diagnostico', 'Diagnóstico']);
  if (can('ver_auditoria')) items.push(['auditoria', 'Auditoria']);
  const box = h('div'); let cur = items[0][0];
  el.append(tabs(items, (k) => { cur = k; draw(); }, cur), box);
  const draw = async () => { clear(box); try { await ({ loja, pagamentos, usuarios, permissoes, backup, auditoria, diagnostico })[cur](); } catch (e) { errorToast(e); } };

  async function loja() {
    const { settings: s } = await api.get('/api/settings');
    const i = { name: h('input', { value: s.store_name }), info: h('textarea', {}, s.store_info), foot: h('textarea', {}, s.receipt_footer), suffix: select([['enter', 'Enter (padrão da maioria dos leitores)'], ['tab', 'Tab'], ['nenhum', 'Nenhum (detectar pela velocidade de digitação)']], s.scanner_suffix),
      minlen: h('input', { type: 'number', min: 3, value: s.scanner_min_length }), auto: h('input', { type: 'checkbox', checked: s.auto_print_receipt === '1' }), warranty: h('input', { type: 'number', min: 90, value: s.default_warranty_days }),
      inactive: h('input', { type: 'number', min: 1, value: s.inactive_days }), osdays: h('input', { type: 'number', min: 1, value: s.os_term_days }), keep: h('input', { type: 'number', min: 1, value: s.backup_keep }), inst: h('input', { type: 'number', min: 1, max: 24, value: s.max_installments }) };
    box.append(h('div', { class: 'card', style: { maxWidth: '860px' } }, h('div', { class: 'fields' }, field('Nome da loja', i.name, 'wide'), field('Endereço / CNPJ / telefone (aparece nos comprovantes)', i.info, 'wide'), field('Rodapé do comprovante', i.foot, 'wide'),
      field('O leitor termina a leitura com', i.suffix), field('Tamanho mínimo do código (sem sufixo)', i.minlen), field('Garantia padrão (dias, mínimo 90)', i.warranty), field('Dias sem venda para "produto parado"', i.inactive), field('Dias para "aparelho não retirado"', i.osdays),
      field('Máximo de parcelas no cartão', i.inst), field('Backups automáticos mantidos', i.keep), h('label', { class: 'check wide' }, i.auto, 'Imprimir o comprovante automaticamente ao concluir a venda')),
      h('div', { class: 'row', style: { marginTop: '14px' } }, h('button', { class: 'btn primary', onclick: async () => {
        await api.put('/api/settings', { settings: { store_name: i.name.value, store_info: i.info.value, receipt_footer: i.foot.value, scanner_suffix: i.suffix.value, scanner_min_length: i.minlen.value, auto_print_receipt: i.auto.checked ? '1' : '0',
          default_warranty_days: i.warranty.value, inactive_days: i.inactive.value, os_term_days: i.osdays.value, backup_keep: i.keep.value, max_installments: i.inst.value } });
        await refreshMe(); toast('Configurações salvas.', 'good'); } }, 'Salvar'), h('a', { class: 'btn', href: '#/leitor' }, 'Testar leitor de código de barras'))));
  }

  async function diagnostico() {
    const d = await api.get('/api/diagnostico');
    const yn = (v, ok, bad) => badge(v ? ok : bad, v ? 'good' : 'bad');
    const kb = (n) => (n == null ? '—' : n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.round(n / 1024) + ' KB');
    box.append(h('div', { class: 'card', style: { maxWidth: '720px' } }, h('h3', {}, 'Estado do sistema'),
      h('dl', { class: 'kv' },
        h('dt', {}, 'Aplicação'), h('dd', {}, yn(d.online, 'Online', 'Indisponível')),
        h('dt', {}, 'Banco de dados'), h('dd', {}, yn(d.database_ok, 'Acessível e íntegro', 'Com problema')),
        h('dt', {}, 'Conexão segura (HTTPS)'), h('dd', {}, yn(d.https, 'Ativa', 'Não está em HTTPS')),
        h('dt', {}, 'Cookie de sessão seguro'), h('dd', {}, yn(d.cookie_seguro, 'Sim', 'Não (modo local)')),
        h('dt', {}, 'Ambiente'), h('dd', {}, d.environment),
        h('dt', {}, 'Versão publicada'), h('dd', {}, d.version + ' (esquema ' + d.schema_version + ')'),
        h('dt', {}, 'Usuário conectado'), h('dd', {}, d.user),
        h('dt', {}, 'Última atividade gravada'), h('dd', {}, d.last_activity ? fmtDateTime(d.last_activity) : '—'),
        h('dt', {}, 'Hora do servidor'), h('dd', {}, fmtDateTime(d.server_time)),
        h('dt', {}, 'Último backup'), h('dd', {}, (d.last_backup ? fmtDateTime(d.last_backup) : 'nenhum') + ' (' + d.backup_count + ' guardados)'),
        h('dt', {}, 'Tamanho do banco'), h('dd', {}, kb(d.db_size)),
        h('dt', {}, 'Tentativas de login falhas (24 h)'), h('dd', {}, String(d.failed_logins_24h)))),
      h('p', { class: 'muted' }, 'Importante: baixe uma cópia do backup para o seu computador com frequência. O backup que fica só no servidor não protege contra problemas no próprio servidor.'));
  }

  async function pagamentos() {
    const { settings: s, card_fees: fees } = await api.get('/api/settings');
    const methods = JSON.parse(s.payment_methods);
    const mBox = h('div', { style: { display: 'grid', gap: '8px' } });
    const mRows = [];
    const addM = (m = { label: '', type: 'other' }) => {
      const label = h('input', { value: m.label, placeholder: 'Nome (ex.: Vale-troca)' }), type = select([['cash', 'Dinheiro'], ['card', 'Cartão'], ['other', 'Outro (PIX, transferência...)']], m.type), inst = h('input', { type: 'checkbox', checked: !!m.installments });
      const r = { key: m.key, label, type, inst }; const row = h('div', { class: 'row' }, h('div', { style: { width: '240px' } }, label), h('div', { style: { width: '260px' } }, type), h('label', { class: 'check' }, inst, 'permite parcelas'), h('button', { class: 'btn small', onclick: () => { mRows.splice(mRows.indexOf(r), 1); row.remove(); } }, 'Remover'));
      mRows.push(r); mBox.append(row); };
    methods.forEach(addM);
    const fBox = h('div', { style: { display: 'grid', gap: '8px' } }); const fRows = [];
    const cardKeys = () => methods.filter((m) => m.type === 'card').map((m) => [m.key, m.label]);
    const addF = (f = { acquirer: s.default_acquirer || '', method: cardKeys()[0]?.[0], installments: 1, fee_bp: 0, days: 30 }) => {
      const acq = h('input', { value: f.acquirer, placeholder: 'Adquirente (ex.: Stone)' }), met = select(cardKeys(), f.method), ins = h('input', { type: 'number', min: 1, max: 24, value: f.installments }), pct = h('input', { value: String(f.fee_bp / 100).replace('.', ','), placeholder: '0,00' }), days = h('input', { type: 'number', min: 0, value: f.days });
      const r = { acq, met, ins, pct, days }; const row = h('div', { class: 'row' }, h('div', { style: { width: '170px' } }, acq), h('div', { style: { width: '190px' } }, met), field('Parcelas', ins), field('Taxa (%)', pct), field('Recebe em (dias)', days), h('button', { class: 'btn small', onclick: () => { fRows.splice(fRows.indexOf(r), 1); row.remove(); } }, 'Remover'));
      fRows.push(r); fBox.append(row); };
    fees.forEach(addF);
    const acquirer = h('input', { value: s.default_acquirer, placeholder: 'Adquirente padrão' });
    box.append(h('div', { class: 'card', style: { marginBottom: '16px' } }, h('h3', {}, 'Formas de pagamento'), h('p', { class: 'muted' }, 'Formas já usadas em vendas não podem ser removidas (apenas renomeadas).'), mBox, h('div', { class: 'row', style: { marginTop: '10px' } }, h('button', { class: 'btn', onclick: () => addM() }, '+ Forma de pagamento'))),
      h('div', { class: 'card' }, h('h3', {}, 'Taxas de cartão (para estimar o valor líquido)'), h('p', { class: 'muted' }, 'Informe as taxas do contrato com a maquininha. Para crédito parcelado, cadastre uma linha por número de parcelas (se faltar, vale a linha de menos parcelas mais próxima). Sem taxas cadastradas, o sistema considera 0%.'),
        field('Adquirente padrão', acquirer), fBox, h('div', { class: 'row', style: { marginTop: '10px' } }, h('button', { class: 'btn', onclick: () => addF() }, '+ Taxa'))),
      h('div', { style: { marginTop: '14px' } }, h('button', { class: 'btn primary', onclick: async () => {
        const pm = mRows.map((r) => ({ key: r.key, label: r.label.value, type: r.type.value, installments: r.inst.checked }));
        const cf = fRows.map((r) => ({ acquirer: r.acq.value, method: r.met.value, installments: +r.ins.value, fee_percent: r.pct.value || '0', days: +r.days.value }));
        await api.put('/api/settings', { settings: { default_acquirer: acquirer.value }, payment_methods: pm, card_fees: cf }); await refreshMe(); toast('Pagamentos e taxas salvos.', 'good'); draw(); } }, 'Salvar pagamentos e taxas')));
  }

  async function usuarios() {
    const rows = await api.get('/api/users');
    async function form(u = null) {
      const i = { name: h('input', { value: u?.name || '' }), username: h('input', { value: u?.username || '', disabled: !!u }), role: select(Object.entries(ROLE), u?.role || 'vendedor'), pass: h('input', { type: 'password', placeholder: u ? 'Deixe em branco para manter' : 'Senha provisória' }), active: h('input', { type: 'checkbox', checked: u ? !!u.active : true }) };
      await modal({ title: u ? 'Editar usuário' : 'Novo usuário', size: 'narrow', content: [field('Nome', i.name), field('Usuário (login)', i.username), field('Perfil', i.role), field(u ? 'Redefinir senha' : 'Senha provisória (será trocada no 1º acesso)', i.pass), u ? h('label', { class: 'check' }, i.active, 'Usuário ativo') : null],
        buttons: [{ label: 'Salvar', kind: 'primary', onClick: async (close) => {
          if (u) await api.put('/api/users/' + u.id, { name: i.name.value, role: i.role.value, active: i.active.checked, password: i.pass.value || undefined });
          else await api.post('/api/users', { name: i.name.value, username: i.username.value, role: i.role.value, password: i.pass.value });
          toast('Usuário salvo.', 'good'); close(true); draw(); } }] });
    }
    box.append(h('div', { class: 'toolbar' }, h('button', { class: 'btn primary', onclick: () => form() }, '+ Novo usuário')), table([{ label: 'Nome', key: 'name' }, { label: 'Usuário', key: 'username' }, { label: 'Perfil', render: (u) => ROLE[u.role] }, { label: 'Situação', render: (u) => badge(u.active ? 'Ativo' : 'Inativo', u.active ? 'good' : 'bad') },
      { label: '', render: (u) => (u.must_change_password ? badge('Senha provisória', 'warn') : '') }], rows, { onRow: form }));
  }

  async function permissoes() {
    const { permissions, roles } = await api.get('/api/permissions'); const editable = ['gerente', 'vendedor', 'tecnico']; const boxes = {};
    const tbody = h('tbody', {}, Object.entries(permissions).map(([k, label]) => h('tr', {}, h('td', {}, label), h('td', { class: 'center' }, '✔'), editable.map((r) => { const c = h('input', { type: 'checkbox', checked: roles[r].includes(k), style: { width: 'auto' } }); (boxes[r] = boxes[r] || {})[k] = c; return h('td', { class: 'center' }, c); }))));
    box.append(h('p', { class: 'muted' }, 'O administrador sempre tem todas as permissões. Quem não tem uma permissão pode pedir a autorização de um supervisor que a tenha (desconto, cancelamento, estoque negativo, devoluções).'),
      h('table', { class: 't' }, h('thead', {}, h('tr', {}, h('th', {}, 'Permissão'), h('th', { class: 'center' }, 'Administrador'), editable.map((r) => h('th', { class: 'center' }, ROLE[r])))), tbody),
      h('div', { style: { marginTop: '14px' } }, h('button', { class: 'btn primary', onclick: async () => { const out = {}; editable.forEach((r) => { out[r] = Object.entries(boxes[r]).filter(([, c]) => c.checked).map(([k]) => k); }); await api.put('/api/permissions', { roles: out }); toast('Permissões salvas.', 'good'); } }, 'Salvar permissões')));
  }

  async function backup() {
    const rows = await api.get('/api/backups'); const kb = (n) => (n / 1024 < 1024 ? Math.round(n / 1024) + ' KB' : (n / 1048576).toFixed(1) + ' MB');
    const file = h('input', { type: 'file', accept: '.db,.sqlite,.sqlite3' });
    async function restore(name) {
      const confirm = h('input', { placeholder: 'Digite RESTAURAR' }), pass = h('input', { type: 'password' });
      await modal({ title: 'Restaurar backup', content: [h('div', { class: 'alertbox bad' }, 'Atenção: os dados atuais serão SUBSTITUÍDOS pelos do backup. Antes disso o sistema guarda uma cópia de segurança do estado atual. Todos os usuários terão de entrar novamente.'), h('div', {}, name ? `Backup: ${name}` : `Arquivo: ${file.files[0]?.name}`), field('Confirme digitando RESTAURAR', confirm), field('Sua senha', pass)],
        buttons: [{ label: 'Restaurar agora', kind: 'danger', onClick: async (close) => { const fd = new FormData(); fd.append('confirm', confirm.value); fd.append('password', pass.value); if (name) fd.append('name', name); else fd.append('file', file.files[0]);
          const r = await api.upload('/api/backups/restore', fd); close(true); await modal({ title: 'Backup restaurado', noCancel: true, content: `Cópia de segurança do estado anterior: ${r.safety_backup}. Entre novamente.`, buttons: [{ label: 'Entrar', kind: 'primary', onClick: () => location.reload() }] }); } }] });
    }
    box.append(h('div', { class: 'grid2' }, h('div', { class: 'card' }, h('h3', {}, 'Fazer backup agora'), h('p', { class: 'muted' }, 'O sistema também faz backup automático ao abrir, a cada 6 horas e ao fechar o caixa. Copie os arquivos para um pendrive ou nuvem com frequência: um backup só no mesmo computador não protege contra perda do computador.'),
      h('button', { class: 'btn primary', onclick: async () => { const r = await api.post('/api/backups'); toast('Backup criado: ' + r.name, 'good'); draw(); } }, 'Criar backup')),
      h('div', { class: 'card' }, h('h3', {}, 'Restaurar de um arquivo'), field('Arquivo de backup (.db)', file), h('div', { style: { marginTop: '10px' } }, h('button', { class: 'btn danger', onclick: () => { if (!file.files[0]) { toast('Escolha o arquivo de backup.', 'bad'); return; } restore(null); } }, 'Restaurar do arquivo')))),
      h('h3', { style: { margin: '18px 0 8px' } }, 'Backups guardados neste computador'), table([{ label: 'Arquivo', key: 'name' }, { label: 'Tipo', key: 'kind' }, { label: 'Data', render: (b) => fmtDateTime(b.created_at) }, { label: 'Tamanho', render: (b) => kb(b.size), num: true },
        { label: '', render: (b) => h('span', {}, h('a', { class: 'btn small', href: `/api/backups/${b.name}/download` }, 'Baixar'), ' ', h('button', { class: 'btn small', onclick: () => restore(b.name) }, 'Restaurar')) }], rows, { empty: 'Nenhum backup ainda.' }));
  }

  async function auditoria() {
    const from = dateInput(todayISO(-7)), to = dateInput(todayISO()), q = h('input', { placeholder: 'ação, tela ou usuário' }), out = h('div');
    const run = async () => { const rows = await api.get('/api/audit' + qs({ from: from.iso(), to: to.iso(), q: q.value.trim() })); clear(out);
      out.append(table([{ label: 'Data', render: (a) => fmtDateTime(a.created_at) }, { label: 'Usuário', render: (a) => a.user_name || '—' }, { label: 'Ação', key: 'action' }, { label: 'Registro', render: (a) => `${a.entity}${a.entity_id ? ' #' + a.entity_id : ''}` }, { label: 'Antes', render: (a) => h('code', {}, (a.before_json || '').slice(0, 120)) },
        { label: 'Depois', render: (a) => h('code', {}, (a.after_json || '').slice(0, 120)) }, { label: 'Autorizado por', render: (a) => a.authorized_name || '' }], rows, { empty: 'Nada registrado neste período.' })); };
    box.append(h('div', { class: 'toolbar' }, field('De', from), field('Até', to), field('Buscar', q, 'grow'), h('button', { class: 'btn primary', onclick: () => run().catch(errorToast) }, 'Filtrar')), out); await run();
  }
  await draw();
}
