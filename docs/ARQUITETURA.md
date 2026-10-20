# Arquitetura

## Decisão tecnológica

| Camada | Escolha | Motivo |
|---|---|---|
| Aplicação | **Python 3 + Flask**, servidor **Waitress** | Roda no Windows sem instalar banco de dados; fácil de manter e atualizar |
| Banco de dados | **SQLite** (modo WAL) | Arquivo único, transações ACID, funciona offline, backup simples |
| Interface | HTML + CSS + JavaScript puro, aberto no navegador local (`http://127.0.0.1:5000`) | Sem dependência de internet (nenhum CDN), rápida, ideal para o balcão |
| Empacotamento | **PyInstaller** (`build_exe.bat`) | Gera `SistemaLoja.exe`; opcional |

Por que sistema web local e não desktop clássico? Leitores de código de barras HID funcionam como teclado: o navegador recebe os dígitos como digitação normal, sem driver. A interface fica moderna e fácil de evoluir.

## Camadas

```
navegador  ──HTTP/JSON──▶  loja/app.py (rotas, autenticação, permissões)
                               │
                               ▼
                       loja/services.py (regras de negócio, transações)
                               │
                               ▼
                       loja/db.py ──▶ dados/loja.db (SQLite)
```

- **Dinheiro** sempre em centavos inteiros (sem erros de arredondamento).
- **Estoque** só muda por `stock_movements`, que guarda quantidade antes/depois, usuário e motivo.
- **Venda atômica**: uma transação `BEGIN IMMEDIATE` valida estoque, baixa, grava itens e pagamentos. Se qualquer passo falhar, nada é gravado.
- **Venda duplicada**: cada venda carrega um `client_token` único; reenviar o mesmo token devolve a venda já criada.
- **Custo real**: cada item vendido grava o custo unitário vigente (custo médio ponderado) para o cálculo correto do lucro.
- **Segurança**: senhas com hash (scrypt/PBKDF2 do Werkzeug), cookie de sessão HttpOnly + SameSite=Strict, cabeçalho anti-CSRF, limite de tentativas de login, auditoria de ações sensíveis. Escuta apenas em `127.0.0.1` por padrão.

## Módulos (backend em `loja/`)

| Arquivo | Responsabilidade |
|---|---|
| `schema.sql`, `db.py` | 27 tabelas, conexão, transações, migrações por `PRAGMA user_version` |
| `barcode.py` | Normalização e validação EAN-13/EAN-8/UPC-A, variantes (UPC-A = EAN-13 com 0) |
| `services.py` | Permissões, configurações, venda, cancelamento, caixa, dashboard, taxas de cartão |
| `devices.py` | Aparelhos individuais: IMEI (Luhn), série, status, histórico |
| `service_orders.py` | Ordens de serviço, peças com baixa automática, aprovação, pagamentos parciais |
| `after_sales.py` | Devoluções/trocas, garantias e acionamentos |
| `finance.py` | Contas a pagar/receber, previsão de cartão, fluxo de caixa, resultado |
| `registry.py` | Clientes, fornecedores, produtos (busca/histórico/transferência), inventário |
| `reports.py` | 16 relatórios, exportação CSV (`;` + BOM) e Excel (.xlsx real) |
| `backup.py` | Backup (API do SQLite), validação, restauração com cópia de segurança |
| `app.py` | Rotas, autenticação, permissões, CSRF, impressão |

## Regras importantes

- **Autorização de supervisor**: operações sensíveis (desconto acima do limite, cancelamento, estoque negativo, ajustes) devolvem `403 authorization_required`; a interface pede usuário/senha de um supervisor e repete a mesma operação. Fica gravado `authorized_by`.
- **Aparelhos**: só viram "vendido" por uma venda; indisponíveis não entram no carrinho; IMEI/série únicos.
- **Garantia**: mínimo de 90 dias para produtos (CDC art. 26), garantido no schema (`CHECK`) e no código.
- **Taxas de cartão**: percentuais por maquininha/modalidade/parcelas e prazo de recebimento; taxa, líquido e prazo ficam gravados em cada pagamento. O recebimento previsto de cada parcela é estimativa (data + prazo + 30 dias por parcela).
- **Definições financeiras**: faturamento = vendas − devoluções + serviços entregues; lucro bruto = faturamento − custo real; resultado = lucro bruto − taxas de cartão − despesas − custo de garantia. Compras de estoque não são despesa; recebimentos aparecem separados.
- **Backup**: automático ao iniciar, a cada 6 h e ao fechar o caixa; mantém as N últimas cópias (configurável). Restaurar valida integridade, cria cópia de segurança e encerra as sessões.
- **Dados de demonstração** ficam em `dados_demo/`, nunca misturados com `dados/`.

## Limites conhecidos

- Sem integração com maquininhas/PIX/gateways (pagamento é registrado manualmente) e sem emissão fiscal (NFC-e/NF-e).
- PDF via impressão do navegador ("Salvar como PDF"). Cupom térmico via página 80/58 mm do navegador; ESC/POS direto não foi implementado.
- Leitor: precisa operar como teclado (HID) com o layout correto; a tela "Teste do leitor" ajuda a diagnosticar.
