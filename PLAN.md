# PLAN — Acesso remoto

## Diagnóstico inicial
- O sistema é **Flask + SQLite** (não React/Next/Supabase). Não existia banco remoto, e sim um arquivo local; não havia sincronização entre bancos nem configuração de hospedagem.
- Já existiam: login por sessão, permissões no servidor, anti-CSRF, limite de login, auditoria, venda idempotente (`client_token`), backup/restauração.
- Pontos que impediam o uso online: cookie sem `Secure`; HTTP sem redirecionamento; senha inicial fixa conhecida (`admin123`); IP do cliente incorreto atrás de proxy (limite de login travaria todos juntos); porta e disco fixos; sessões derrubadas a cada reinício; sem PWA; layout só para desktop; sem diagnóstico; `fetch` sem indicação de conexão.
- Nenhuma URL `localhost` embutida no front (chamadas relativas). Recuperação de senha por e-mail e confirmação de e-mail: **não existem** (sem serviço de e-mail).

## Estratégia
Manter a arquitetura (sem migrar banco) e hospedar o mesmo código num contêiner com **disco persistente**. Vercel/Netlify/Supabase descartados por incompatibilidade (ver DEPLOYMENT.md).

## Alterações realizadas
- Configuração de produção (`LOJA_ENV`): falha clara sem `LOJA_DATA_DIR`/`LOJA_ADMIN_PASSWORD`; cookie Secure; redirecionamento HTTPS; HSTS; ProxyFix; validação de origem; senha mínima de 10; porta via `PORT`.
- Sessões persistentes entre reinícios (`session.epoch`), invalidadas na restauração de backup.
- `/api/health` mínimo e público; `/api/diagnostico` (administrador) e aba **Diagnóstico**.
- Indicador Online/Sem conexão, faixa de aviso e mensagem "operação NÃO confirmada".
- PWA: manifest, ícones, service worker sem cache de dados, página de indisponibilidade.
- Layout responsivo (menu em gaveta, campos 16 px no iPhone, sem rolagem horizontal).
- Correção: tela de troca obrigatória de senha não dispara mais erro de console.
- `Dockerfile`, `render.yaml`, `.dockerignore`, `.env.example`, documentação.

## Testes executados
- Suíte automatizada: testes originais + 18 de produção (`tests/test_production.py`): configuração obrigatória, HTTPS, cookies, origem, limite de login por IP real, rotas sem login, manifest/SW, diagnóstico e permissões, vendas entre dois usuários, reenvio idempotente, bloqueio de usuário, logout.
- Navegador real (Playwright/Chromium) com servidor em modo produção atrás de proxy HTTPS simulado, desktop 1366×768 e iPhone 13 ao mesmo tempo, 32 verificações: login e troca obrigatória, cookie, venda no celular → baixa no desktop → histórico, permissões do vendedor, sem rolagem horizontal, diagnóstico, queda do indicador, venda sem conexão não concluída, servidor fora do ar mostra aviso do service worker, sessão sobrevive a reinício, logout, rota interna sem login, console limpo.

## Pendências (dependem do proprietário ou não foram feitas)
- **Publicar:** exige conta e pagamento na hospedagem. Não publicado.
- Testar no **domínio real**, em Android e iPhone físicos e instalar o PWA (aqui só emulação de iPhone no Chromium; Safari/WebKit real não testado). Waitress não pôde ser instalado no ambiente de teste; testado com o servidor do Werkzeug.
- Teste de build do Docker: ver nota em DEPLOYMENT.md/relatório final.
- Domínio próprio (opcional), monitor de disponibilidade, cópia externa semanal do backup.
- Não implementados: 2FA, mascaramento de IMEI por perfil, recuperação de senha por e-mail, modo offline (por decisão).

## Critérios de conclusão
Acesso remoto só está concluído quando, no endereço público: HTTPS ativo; login e troca de senha; venda no celular visível no computador; permissões; PWA instalável; backup externo feito; checklist `PRODUCTION_CHECKLIST.md` completo.
