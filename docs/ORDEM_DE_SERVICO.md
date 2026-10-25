# Ordem de serviço — impressão térmica, peças avulsas, custos e garantia

## 1. Epson TM-T20 (papel 80 mm) no Windows

O sistema imprime pelo navegador (Chrome ou Edge). **Não há impressão direta ESC/POS**; o resultado depende do driver.

**Instalação do driver (uma vez)**
1. Baixe o driver *Epson Advanced Printer Driver (APD)* do site da Epson para o modelo TM-T20 (ou TM-T20II/III) e instale.
2. Conecte a impressora (USB/rede), ligue e confirme em *Configurações → Impressoras* que ela aparece.

**Preferências da impressora (Painel de Controle → Dispositivos e Impressoras → botão direito na TM-T20 → Preferências de impressão)**
- Tamanho do papel: o de bobina 80 mm do driver (ex.: *RP80 x 297 mm*, *Receipt 80 mm*, *80mm x 297mm*). Use "Papel contínuo / Roll paper" se existir.
- Margens do driver: **0** (ou o mínimo oferecido).
- Corte do papel: "Cortar ao final do documento" (*Paper Reduction / Cut: Cut at end of document*).
- Qualidade: padrão. Orientação: retrato.

**Janela de impressão do Chrome/Edge**
- Impressora: Epson TM-T20.
- Tamanho do papel: o mesmo de 80 mm do driver (o sistema já pede 80 mm).
- Margens: **Nenhuma**. Escala: **100 %** (não use "Ajustar à página").
- **Desmarque "Cabeçalhos e rodapés"** (o navegador imprime data/URL no papel se estiver marcado).
- Desmarque "Gráficos de segundo plano" se quiser economizar tinta térmica (opcional).

**Ajuste da largura útil**: a TM-T20 imprime cerca de 72 mm em papel de 80 mm. O padrão do sistema é 72 mm. Se as bordas saírem cortadas, reduza em *Configurações → Ordem de serviço e garantia → Largura útil da bobina* (ex.: 68) e imprima a página de teste de novo. Para bobina de 58 mm, use 48.

**Como o sistema ajusta a página**: o Chromium não aceita `@page { size: 80mm auto }`, então o sistema calcula a altura do cupom ao imprimir (`print.js`) e define `@page { size: 80mm <altura>mm; margin: 0 }`, gerando uma tira contínua. Se o seu driver ignorar o tamanho enviado, o papel escolhido no driver prevalece e o texto continua cabendo na largura.

## 2. Imprimir uma OS de teste
1. *Configurações → Ordem de serviço e garantia → Imprimir página de teste da térmica*: confira se a régua e a caixa aparecem inteiras (esquerda e direita).
2. Abra qualquer OS e clique em **Imprimir via do cliente (térmica 80 mm)**. A versão A4 continua em **Imprimir A4**.
3. A tela de impressão também aceita `?formato=a4` ou `?formato=termico` e `&largura=NN` na URL.

## 3. Peça avulsa (sob encomenda) e custo
1. Na OS, clique em **+ Peça avulsa / sob encomenda** e informe nome, modelo/compatibilidade, quantidade e valor cobrado. O custo pode ficar em branco.
2. A peça fica só naquela OS: **não cria produto no catálogo e não baixa estoque**.
3. Registre o orçamento e a autorização do cliente. Só depois mude a peça para *Encomendada* (a tela bloqueia antes da autorização).
4. Quando souber o custo real, use **Informar custo** (precisa da permissão "Ver custos"). Enquanto faltar custo, o lucro da OS aparece como **incompleto**, nunca como custo zero.
5. Atualize a situação: aguardando compra → encomendada → recebida → instalada. A OS não vira "pronta para retirada" com peça avulsa ainda pendente.
6. Cliente desistiu: antes da compra, **Remover**. Depois da compra, **Cancelar peça** (pede autorização de supervisor); o custo já pago continua no resultado e o cliente não é cobrado.
7. Outros custos (frete, insumos): botão de custos internos da OS.

Cálculos: custo total = custo das peças + outros custos; total cobrado = peças cobradas + mão de obra − desconto; lucro bruto = total cobrado − custo total.

**Valores na via do cliente**: aparece somente o valor único cobrado (total), sem discriminar peças, mão de obra, desconto ou pagamentos.

**Via do cliente**: montada por lista de permissão no servidor (`customer_document`). Não existe caminho de custo, lucro, fornecedor, observações internas ou situação de compra até o papel. Telas e APIs internas escondem custo/lucro de quem não tem "Ver custos"/"Ver lucros" (filtro no servidor).

## 4. Termo de garantia
- *Configurações → Ordem de serviço e garantia* (somente quem tem "Gerenciar configurações", o administrador por padrão).
- Edite o texto do termo e as condições de atendimento; separe parágrafos com linha em branco; a primeira linha é o título. **Restaurar texto padrão** volta ao termo original.
- Prazos por tipo de serviço/peça: tabela editável (mínimo de 90 dias). Confirme os prazos adequados a cada serviço antes de usar; o sistema não impõe um prazo único.
- A OS grava o tipo/prazo, a data inicial e final (a garantia começa quando o serviço está confirmado e o aparelho fica "pronto para retirada"; se a OS voltar para reparo, as datas são zeradas) e uma cópia do texto vigente quando fica pronta; mudar o termo depois não altera OS já emitidas (histórico).
- Revise o texto com sua assessoria jurídica; o modelo não é parecer jurídico.

## 5. Migração
Versão do esquema 2 (`loja/migrations.py`): reconstrói `service_order_parts` (peças antigas viram `estoque`, dados preservados), adiciona campos de garantia e de outros custos em `service_orders` e configurações novas. Cópia automática `pre-migracao` antes de migrar. Nenhum dado é apagado.

## 6. O que ainda precisa de teste físico
- Impressão real na Epson TM-T20 (largura útil, corte, densidade, comportamento do driver com altura variável).
- Conferir o texto jurídico e os prazos de garantia da sua loja.
