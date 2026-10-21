# CLAUDE.md — Sistema da Loja

## Arquitetura
- **Backend:** Python 3 + Flask (`loja/app.py`), regras em `loja/*.py`. Servidor: Waitress (`run.py`), fallback Werkzeug.
- **Banco:** SQLite único (`LOJA_DATA_DIR/loja.db`, modo WAL). Dinheiro em centavos inteiros. Estoque só muda por `move_stock`.
- **Front-end:** HTML + JavaScript puro (módulos ES), sem build e sem CDN, em `loja/static`. Rotas por `#/rota`.
- **Autenticação:** sessão por cookie assinado (Flask), usuários na tabela `users`, hash scrypt, permissões por perfil configuráveis.
- **PWA:** `manifest.webmanifest` + `sw.js` (não faz cache de dados; mostra aviso offline).
- **Hospedagem:** contêiner (`Dockerfile`) com disco persistente em `/data`. Blueprint do Render em `render.yaml`. Não há serviço de banco separado.

## Comandos
- Rodar local: `python run.py` (http://127.0.0.1:5000). Demonstração: `python tools/demo_data.py` e `LOJA_DATA_DIR=dados_demo python run.py`.
- Testes: `python -m unittest discover -s tests -t .`
- Produção local simulada: `LOJA_ENV=production LOJA_DATA_DIR=/tmp/x LOJA_ADMIN_PASSWORD=... python run.py` (exige HTTPS via proxy; use `X-Forwarded-Proto: https`).
- Contêiner: `docker build -t sistema-loja .`

## Variáveis de ambiente (nomes; nunca valores)
`LOJA_ENV`, `LOJA_DATA_DIR`, `LOJA_ADMIN_PASSWORD`, `LOJA_SECRET_KEY`, `LOJA_PUBLIC_URL`, `LOJA_TRUST_PROXY`, `PORT`/`LOJA_PORT`, `LOJA_HOST`, `LOJA_NO_BROWSER`. Detalhes em `.env.example`.

## Regras de segurança
- Nunca commitar `.env`, `dados/`, `dados_demo/`, `*.db`, `secret.key`, backups. O `.gitignore` bloqueia; confira `git status` antes de cada commit.
- Nunca colocar senha, chave ou token em código, logs, testes de produção ou documentação.
- Toda rota nova usa o decorador `api(...)` (autenticação, permissão, CSRF, transação). Permissão é checada no servidor; o front só esconde botões.
- Em produção: cookie Secure, HTTPS obrigatório, validação de origem. Não relaxar.
- Service worker nunca deve guardar respostas (`cache.put`/`caches.open` são proibidos; há teste).
- Operação de venda/estoque/caixa só vale após confirmação do servidor. Não criar fila offline nem otimismo no front.

## Alterações futuras
1. Escreva/ajuste o teste (`tests/`), rode a suíte inteira (77 testes originais + `test_production.py`).
2. Mudou o esquema? Acrescente em `MIGRATIONS` (`loja/db.py`), aumente `SCHEMA_VERSION`; nunca apague dados.
3. Mudou o front? Teste em desktop e celular (largura 390 px, sem rolagem horizontal).
4. Atualize `APP_VERSION` em `loja/app.py` e os documentos afetados.
5. `git push` na `main` publica (autoDeploy no Render). Faça um backup antes de mudanças no banco.
