# Acesso remoto

O sistema é uma aplicação web (Flask + SQLite). Hospedado online, qualquer aparelho com navegador acessa o **mesmo banco**: não há segundo banco nem cópia. Uma venda feita no celular baixa o estoque que o computador da loja enxerga na próxima tela que abrir.

## Como acessar
| Aparelho | Como |
|---|---|
| Computador (Chrome, Edge, Firefox) | Abra o endereço HTTPS da hospedagem e entre com seu usuário e senha |
| Android (Chrome) | Abra o endereço → menu ⋮ → **Instalar app** (ou "Adicionar à tela inicial") |
| iPhone/iPad (Safari) | Abra o endereço → botão Compartilhar → **Adicionar à Tela de Início** |

## O que a versão instalada (PWA) faz e não faz
- Abre como aplicativo, em tela cheia, com ícone próprio.
- **Não guarda dados no aparelho e não funciona offline.** Sem internet aparece o aviso "Sem conexão" e nenhuma venda ou alteração é gravada. Isso é proposital: nunca mostrar estoque ou caixa antigos como se fossem atuais.
- O indicador **Online / Sem conexão** no topo consulta o servidor a cada 15 segundos.
- Uma venda só aparece como concluída depois da confirmação do servidor. Se a conexão cair no meio, o sistema avisa que a operação **não foi confirmada**; confira o *Histórico de vendas* antes de repetir. Se o botão for repetido, o servidor reconhece a mesma venda e não duplica.

## Segurança
- HTTPS obrigatório (HTTP é redirecionado) e cabeçalho HSTS.
- Cookie de sessão `Secure`, `HttpOnly`, `SameSite=Strict`; sessão de 12 h que sobrevive a atualizações do servidor e é encerrada ao restaurar um backup.
- Permissões sempre conferidas no servidor (perfis administrador, gerente, vendedor, técnico). Vendedor não vê custos, lucro, financeiro, relatórios, usuários nem backups.
- Limite de 5 tentativas de login por 5 minutos (por usuário e IP real). Falhas ficam na auditoria.
- Validação de origem em toda escrita e cabeçalho anti-CSRF.
- Senha mínima de 10 caracteres em produção; senha inicial do `admin` vem de variável de ambiente e precisa ser trocada no primeiro acesso.
- Tela **Configurações → Diagnóstico** (administrador): app, banco, HTTPS, último backup, tentativas de login falhas.

## Recuperação de senha
Não há envio de e-mail (não existe serviço de e-mail configurado). Quem esquecer a senha pede a um **administrador**: Configurações → Usuários → redefinir senha (o usuário troca no próximo acesso). Se o próprio administrador esquecer a senha e não houver outro, é preciso acesso ao servidor para redefinir; guarde a senha em local seguro e mantenha **dois administradores**.

## Limitações conhecidas
- Sem autenticação em dois fatores (não implementada).
- Sem modo offline (por decisão de segurança).
- Os dados de IMEI aparecem completos para quem tem acesso a aparelhos; não há mascaramento por perfil.
- Um único servidor/instância (SQLite). Atende bem uma loja pequena; para várias lojas seria preciso migrar para PostgreSQL.
