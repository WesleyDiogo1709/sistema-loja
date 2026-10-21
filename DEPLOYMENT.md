# Publicação (passo a passo)

> Estado: o projeto está **preparado**, mas **não foi publicado** por quem o desenvolveu: isso exige a sua conta e o seu pagamento. Nada abaixo foi executado em seu nome.

## Por que não Vercel/Netlify/Supabase
O sistema é um servidor Python que grava num arquivo SQLite. Vercel e Netlify rodam funções sem disco; o banco seria apagado. Supabase é PostgreSQL e exigiria reescrever a camada de dados. A hospedagem certa é uma que rode o contêiner e ofereça **disco persistente**.

## Opção recomendada: Render (plano pago com disco)
Custo aproximado de US$ 7/mês + ~US$ 0,25/GB do disco (**confirme no site**, preços mudam).

1. Conta em render.com (entre com o GitHub).
2. **New → Blueprint** → escolha o repositório `sistema-loja`. O `render.yaml` cria o serviço Docker com o disco `/data`.
3. Quando pedir `LOJA_ADMIN_PASSWORD`, digite uma senha inicial de 10+ caracteres (só vale na criação do banco).
4. Aguarde o deploy. O Render mostra o endereço `https://sistema-loja-xxxx.onrender.com` (HTTPS já incluso).
5. Abra, entre com `admin` e a senha do passo 3. O sistema obriga a trocar a senha.
6. Em **Configurações → Usuários** crie os usuários (vendedor, técnico) e um **segundo administrador**.
7. (Opcional) Variável `LOJA_PUBLIC_URL` com o endereço final.

Alternativas equivalentes com o mesmo `Dockerfile`: Railway (volume em `/data`), Fly.io (volume em `/data`), VPS.
**Atenção:** planos gratuitos/testes costumam pausar deploys ou apagar arquivos. Sem disco persistente em `/data`, **os dados são perdidos a cada atualização**.

## Variáveis de ambiente
Veja `.env.example`. Obrigatórias em produção: `LOJA_ENV=production`, `LOJA_DATA_DIR=/data`, `LOJA_ADMIN_PASSWORD` (apenas no primeiro start). O servidor se recusa a iniciar, com mensagem clara, se faltarem.

## Build e execução
- Contêiner: `docker build -t sistema-loja .` e `docker run -p 8080:8080 -v dados:/data -e LOJA_ADMIN_PASSWORD=... sistema-loja`.
- Sem Docker: `pip install -r requirements.txt` e `LOJA_ENV=production LOJA_DATA_DIR=... python run.py`.
- Não há etapa de build do front-end (HTML/JS puro; diretório estático `loja/static`).
- Rotas: o front usa `#/rota`, então atualizar a página em qualquer tela funciona sem regras de reescrita.

## Domínio próprio (opcional)
1. No Render: Settings → Custom Domains → adicione `loja.seudominio.com.br`.
2. No provedor do domínio, crie o registro **CNAME** `loja` apontando para o endereço `.onrender.com` indicado. Para o domínio raiz use o registro A/ALIAS que o Render informar.
3. Espere o certificado HTTPS ser emitido (automático). HTTP é redirecionado para HTTPS.
4. Defina `LOJA_PUBLIC_URL=https://loja.seudominio.com.br`.

## Atualizar
Envie o código novo ao GitHub (`git push`); com `autoDeploy` o Render publica sozinho. Os dados no disco `/data` são preservados e as sessões continuam válidas. Confira a versão em Configurações → Diagnóstico.

## Reverter (rollback)
No Render: aba **Events/Deploys** → escolha o deploy anterior → **Rollback**. Se uma atualização alterar o banco de forma incompatível, restaure também o backup feito antes (o sistema faz backup ao iniciar).

## Backup e restauração
- Automático: ao iniciar, a cada 6 h e ao fechar o caixa (últimas N cópias em `/data/backups`).
- **Cópia externa (obrigatória na prática):** em Configurações → Backup e restauração, baixe o arquivo e guarde no seu computador ou nuvem, no mínimo toda semana. Backup só dentro do servidor não protege contra falha do servidor.
- Restaurar: Configurações → Backup → escolha a cópia (ou envie o arquivo). O sistema valida, guarda uma cópia de segurança do estado atual e encerra as sessões.
