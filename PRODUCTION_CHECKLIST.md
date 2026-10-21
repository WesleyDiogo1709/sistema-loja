# Checklist de produção

Antes de abrir para a equipe:
- [ ] Disco persistente montado em `/data` (reinicie o serviço e confirme que os dados continuam).
- [ ] `LOJA_ENV=production` e `LOJA_ADMIN_PASSWORD` definidos (senha inicial já trocada).
- [ ] Endereço abre em **HTTPS** e `http://` redireciona.
- [ ] Configurações → Diagnóstico: banco "Acessível e íntegro", HTTPS "Ativa", cookie seguro "Sim".
- [ ] Dois administradores criados; senhas anotadas em local seguro.
- [ ] Vendedores/técnicos com o perfil certo (vendedor não vê custo/lucro).
- [ ] Taxas de cartão cadastradas (Configurações → Pagamentos e taxas).
- [ ] Venda de teste feita no celular e conferida no computador; depois cancelada com motivo.
- [ ] Primeiro backup baixado para o seu computador; rotina semanal combinada.
- [ ] Monitor de disponibilidade (ex.: UptimeRobot, gratuito) apontando para `/api/health` com alerta por e-mail.
- [ ] Nenhum `.env`, `dados/` ou `secret.key` no Git (o `.gitignore` já bloqueia).
