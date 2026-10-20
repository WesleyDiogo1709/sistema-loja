# Sistema da Loja — acessórios, iPhones seminovos e assistência técnica

Sistema local, offline, em português (R$, DD/MM/AAAA), com banco SQLite real. Roda no Windows.

## Instalação (Windows)
1. Instale o **Python 3.10 ou superior** (python.org), marcando *Add Python to PATH*.
2. Dê dois cliques em `instalar.bat` (precisa de internet só nesta etapa).
3. Dê dois cliques em `iniciar.bat`. O navegador abre em `http://127.0.0.1:5000`.
4. Primeiro acesso: usuário `admin`, senha `admin123`. **O sistema exige trocar a senha na hora.**

Demonstração com dados fictícios (separados dos reais): `iniciar_demo.bat` — login `admin` / `Demo@1234` (também `gerente`, `vendedor`, `tecnico`).

Executável único (opcional): `build_exe.bat` gera `dist\SistemaLoja\SistemaLoja.exe`.

## Onde ficam os dados
Pasta `dados\` (arquivo `loja.db` e subpasta `backups\`). Para mudar: variável `LOJA_DATA_DIR`. Outras: `LOJA_PORT`, `LOJA_HOST=0.0.0.0` (liberar outros computadores da rede local).

## Leitor de código de barras
- Leitores USB/Bluetooth que funcionam como teclado não precisam de driver.
- No PDV o campo de leitura fica sempre focado: leu um código cadastrado, o item entra no carrinho. Prefixo `3*codigo` adiciona 3 unidades.
- Configurações → Loja e leitor: terminador (Enter/Tab/nenhum). Sem terminador, o sistema detecta a digitação rápida.
- Menu **Teste do leitor** mostra o que o aparelho envia (teclas, tempo, layout errado).
- Código não cadastrado: o sistema avisa e oferece cadastrar o produto com o código já preenchido.

## Backup e restauração
Configurações → Backup. Automático ao iniciar, a cada 6 h e ao fechar o caixa. Para segurança real, copie a pasta `dados\backups` para um pendrive ou nuvem com frequência. Restaurar cria antes uma cópia de segurança do estado atual.

## Impressão
- Comprovante e OS: abrem uma página formatada; use a impressão do navegador (A4 ou bobina 80 mm/58 mm — largura em Configurações → Loja e leitor).
- PDF: na janela de impressão, escolha "Salvar como PDF".
- Impressão direta ESC/POS **não** está implementada.

## O que depende de configuração sua
- **Taxas de cartão** (Configurações → Pagamentos e taxas): cadastre os percentuais e prazos reais da sua maquininha. Nenhum valor padrão é inventado.
- Impressora, layout do teclado do leitor, dados da loja no cupom.
- Termos de garantia/troca: configuráveis, com mínimo legal de 90 dias.

## Não incluído
Integração com maquininha/PIX/gateway, nota fiscal (NFC-e/NF-e), envio de WhatsApp/e-mail. Pagamentos são registrados manualmente.

## Testes
`python -m unittest discover -s tests -t .` (77 testes: venda, leitor, estoque, cancelamento, devolução, taxas, caixa, permissões, backup/restauração, venda duplicada, concorrência). Documentação técnica: `docs/ARQUITETURA.md`.
