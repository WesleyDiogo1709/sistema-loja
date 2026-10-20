-- Esquema do banco de dados (SQLite) - Sistema de Gestão para Loja de Eletrônicos
-- Convenções:
--   * Valores monetários em CENTAVOS (INTEGER), nunca em ponto flutuante.
--   * Datas/horas em texto 'AAAA-MM-DD HH:MM:SS' (hora local); a interface exibe DD/MM/AAAA.
--   * Estoque só é alterado através de stock_movements (histórico completo).

CREATE TABLE users (
    id                   INTEGER PRIMARY KEY,
    username             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name                 TEXT NOT NULL,
    password_hash        TEXT NOT NULL,
    role                 TEXT NOT NULL CHECK (role IN ('administrador','gerente','vendedor','tecnico')),
    active               INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- Permissões configuráveis por perfil (o administrador sempre possui todas).
CREATE TABLE role_permissions (
    role       TEXT NOT NULL,
    permission TEXT NOT NULL,
    PRIMARY KEY (role, permission)
);

CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE customers (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    phone      TEXT,
    email      TEXT,
    doc        TEXT,            -- CPF/CNPJ opcional
    notes      TEXT,
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE products (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    category     TEXT,
    brand        TEXT,
    model        TEXT,
    barcode      TEXT UNIQUE,           -- EAN-13, EAN-8, UPC-A ou código interno (NULL se não houver)
    barcode_type TEXT,
    sku          TEXT UNIQUE,           -- código interno
    description  TEXT,
    supplier     TEXT,
    cost_cents   INTEGER NOT NULL DEFAULT 0 CHECK (cost_cents >= 0),   -- custo médio ponderado
    price_cents  INTEGER NOT NULL DEFAULT 0 CHECK (price_cents >= 0),
    qty          INTEGER NOT NULL DEFAULT 0,   -- só muda via movimentação; negativo apenas com autorização
    min_qty      INTEGER NOT NULL DEFAULT 0,
    warranty_days INTEGER NOT NULL DEFAULT 90 CHECK (warranty_days >= 90),  -- garantia legal mínima (CDC art. 26)
    location     TEXT,
    notes        TEXT,
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_products_name ON products(name);
CREATE INDEX idx_products_category ON products(category);

CREATE TABLE stock_movements (
    id              INTEGER PRIMARY KEY,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    kind            TEXT NOT NULL,   -- entrada_inicial, entrada, saida, perda, avaria, troca, ajuste, venda, cancelamento_venda
    qty_delta       INTEGER NOT NULL,
    qty_before      INTEGER NOT NULL,
    qty_after       INTEGER NOT NULL,
    unit_cost_cents INTEGER,
    reason          TEXT,
    user_id         INTEGER REFERENCES users(id),
    authorized_by   INTEGER REFERENCES users(id),
    ref_type        TEXT,            -- 'sale', ...
    ref_id          INTEGER,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_movements_product ON stock_movements(product_id, created_at);
CREATE INDEX idx_movements_ref ON stock_movements(ref_type, ref_id);

CREATE TABLE cash_sessions (
    id             INTEGER PRIMARY KEY,
    opened_by      INTEGER NOT NULL REFERENCES users(id),
    opened_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    opening_cents  INTEGER NOT NULL CHECK (opening_cents >= 0),
    closed_by      INTEGER REFERENCES users(id),
    closed_at      TEXT,
    expected_cents INTEGER,          -- dinheiro esperado no fechamento
    counted_cents  INTEGER,          -- dinheiro contado
    notes          TEXT
);
-- No máximo UM caixa aberto por vez.
CREATE UNIQUE INDEX idx_one_open_cash ON cash_sessions((1)) WHERE closed_at IS NULL;

CREATE TABLE cash_movements (
    id           INTEGER PRIMARY KEY,
    session_id   INTEGER NOT NULL REFERENCES cash_sessions(id),
    kind         TEXT NOT NULL CHECK (kind IN ('sangria','reforco','devolucao')),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    reason       TEXT NOT NULL,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE sales (
    id              INTEGER PRIMARY KEY,        -- número da venda
    client_token    TEXT NOT NULL UNIQUE,       -- idempotência: impede venda duplicada por clique repetido
    cash_session_id INTEGER REFERENCES cash_sessions(id),
    user_id         INTEGER NOT NULL REFERENCES users(id),
    customer_id     INTEGER REFERENCES customers(id),
    subtotal_cents  INTEGER NOT NULL,
    discount_cents  INTEGER NOT NULL DEFAULT 0,
    total_cents     INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'concluida' CHECK (status IN ('concluida','cancelada')),
    authorized_by   INTEGER REFERENCES users(id),
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    cancelled_at    TEXT,
    cancelled_by    INTEGER REFERENCES users(id),
    cancel_auth_by  INTEGER REFERENCES users(id),
    cancel_reason   TEXT
);
CREATE INDEX idx_sales_created ON sales(created_at);

CREATE TABLE sale_items (
    id               INTEGER PRIMARY KEY,
    sale_id          INTEGER NOT NULL REFERENCES sales(id),
    product_id       INTEGER REFERENCES products(id),     -- NULL quando o item é um aparelho individual
    device_id        INTEGER REFERENCES devices(id),
    product_name     TEXT NOT NULL,             -- cópia do nome no momento da venda
    qty              INTEGER NOT NULL CHECK (qty > 0),
    unit_price_cents INTEGER NOT NULL,
    unit_cost_cents  INTEGER NOT NULL,          -- custo real da unidade no momento da venda
    discount_cents   INTEGER NOT NULL DEFAULT 0,
    total_cents      INTEGER NOT NULL,          -- qty*preço - desconto
    warranty_days    INTEGER NOT NULL DEFAULT 90,
    warranty_ends    TEXT,                      -- AAAA-MM-DD
    CHECK (product_id IS NOT NULL OR device_id IS NOT NULL)
);
CREATE INDEX idx_sale_items_sale ON sale_items(sale_id);
CREATE INDEX idx_sale_items_product ON sale_items(product_id);

CREATE TABLE sale_payments (
    id             INTEGER PRIMARY KEY,
    sale_id        INTEGER NOT NULL REFERENCES sales(id),
    method         TEXT NOT NULL,
    amount_cents   INTEGER NOT NULL CHECK (amount_cents > 0),   -- valor aplicado à venda
    received_cents INTEGER NOT NULL,                            -- valor entregue (dinheiro pode ser maior)
    change_cents   INTEGER NOT NULL DEFAULT 0,
    installments   INTEGER NOT NULL DEFAULT 1,
    fee_cents      INTEGER NOT NULL DEFAULT 0,    -- taxa estimada do cartão (conforme cadastro na data da venda)
    net_cents      INTEGER NOT NULL DEFAULT 0,    -- valor líquido estimado a receber
    rec_days       INTEGER NOT NULL DEFAULT 0,    -- prazo para o 1º recebimento (dias)
    acquirer       TEXT
);
CREATE INDEX idx_sale_payments_sale ON sale_payments(sale_id);

CREATE TABLE audit_log (
    id            INTEGER PRIMARY KEY,
    user_id       INTEGER REFERENCES users(id),
    authorized_by INTEGER REFERENCES users(id),
    action        TEXT NOT NULL,
    entity        TEXT NOT NULL,
    entity_id     INTEGER,
    before_json   TEXT,
    after_json    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_audit_created ON audit_log(created_at);

-- ============================================================ Etapa 4 e 5

CREATE TABLE suppliers (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    phone      TEXT,
    email      TEXT,
    doc        TEXT,
    notes      TEXT,
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- Aparelhos individuais (iPhones seminovos etc.): um registro por unidade.
CREATE TABLE devices (
    id             INTEGER PRIMARY KEY,
    code           TEXT UNIQUE,                 -- código interno (ex.: APL000001), pode ser lido no leitor
    brand          TEXT NOT NULL,
    model          TEXT NOT NULL,
    storage        TEXT,
    color          TEXT,
    imei1          TEXT UNIQUE,
    imei2          TEXT UNIQUE,
    serial         TEXT UNIQUE,
    battery_health INTEGER CHECK (battery_health IS NULL OR battery_health BETWEEN 0 AND 100),
    condition      TEXT,
    origin         TEXT,
    cost_cents     INTEGER NOT NULL DEFAULT 0 CHECK (cost_cents >= 0),
    price_cents    INTEGER NOT NULL DEFAULT 0 CHECK (price_cents >= 0),
    supplier       TEXT,
    entry_date     TEXT NOT NULL,
    warranty_days  INTEGER NOT NULL DEFAULT 90 CHECK (warranty_days >= 90),
    status         TEXT NOT NULL DEFAULT 'disponivel'
                   CHECK (status IN ('disponivel','reservado','vendido','em_teste','em_manutencao','devolvido')),
    reserved_for   TEXT,
    notes          TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_devices_status ON devices(status);

CREATE TABLE device_events (
    id         INTEGER PRIMARY KEY,
    device_id  INTEGER NOT NULL REFERENCES devices(id),
    event      TEXT NOT NULL,
    status     TEXT,
    user_id    INTEGER REFERENCES users(id),
    note       TEXT,
    ref_type   TEXT,
    ref_id     INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_device_events ON device_events(device_id);

CREATE TABLE service_orders (
    id               INTEGER PRIMARY KEY,           -- número da OS
    customer_id      INTEGER REFERENCES customers(id),
    customer_name    TEXT NOT NULL,
    customer_phone   TEXT,
    brand            TEXT NOT NULL,
    model            TEXT NOT NULL,
    imei             TEXT,
    serial           TEXT,
    defect           TEXT NOT NULL,
    physical_state   TEXT,
    accessories      TEXT,
    diagnosis        TEXT,
    services_done    TEXT,
    labor_cents      INTEGER NOT NULL DEFAULT 0 CHECK (labor_cents >= 0),
    discount_cents   INTEGER NOT NULL DEFAULT 0 CHECK (discount_cents >= 0),
    approved         INTEGER NOT NULL DEFAULT 0,    -- cliente autorizou o orçamento
    approved_at      TEXT,
    approved_note    TEXT,
    deadline         TEXT,                          -- AAAA-MM-DD
    technician_id    INTEGER REFERENCES users(id),
    entry_at         TEXT NOT NULL,
    completed_at     TEXT,
    delivered_at     TEXT,
    warranty_days    INTEGER NOT NULL DEFAULT 90 CHECK (warranty_days >= 90),
    status           TEXT NOT NULL DEFAULT 'recebido'
                     CHECK (status IN ('recebido','em_diagnostico','aguardando_aprovacao','aguardando_peca',
                                       'em_reparo','em_testes','pronto_retirada','entregue','cancelado')),
    notes            TEXT,
    created_by       INTEGER REFERENCES users(id),
    client_token     TEXT UNIQUE
);
CREATE INDEX idx_os_status ON service_orders(status);
CREATE INDEX idx_os_imei ON service_orders(imei);

CREATE TABLE service_order_parts (
    id               INTEGER PRIMARY KEY,
    order_id         INTEGER NOT NULL REFERENCES service_orders(id),
    product_id       INTEGER NOT NULL REFERENCES products(id),
    name             TEXT NOT NULL,
    qty              INTEGER NOT NULL CHECK (qty > 0),
    unit_cost_cents  INTEGER NOT NULL,
    unit_price_cents INTEGER NOT NULL,
    removed_at       TEXT
);
CREATE INDEX idx_os_parts ON service_order_parts(order_id);

CREATE TABLE service_order_events (
    id         INTEGER PRIMARY KEY,
    order_id   INTEGER NOT NULL REFERENCES service_orders(id),
    status     TEXT,
    note       TEXT,
    user_id    INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_os_events ON service_order_events(order_id);

CREATE TABLE service_payments (
    id              INTEGER PRIMARY KEY,
    order_id        INTEGER NOT NULL REFERENCES service_orders(id),
    method          TEXT NOT NULL,
    amount_cents    INTEGER NOT NULL CHECK (amount_cents > 0),
    received_cents  INTEGER NOT NULL,
    change_cents    INTEGER NOT NULL DEFAULT 0,
    installments    INTEGER NOT NULL DEFAULT 1,
    fee_cents       INTEGER NOT NULL DEFAULT 0,
    net_cents       INTEGER NOT NULL DEFAULT 0,
    rec_days        INTEGER NOT NULL DEFAULT 0,
    acquirer        TEXT,
    cash_session_id INTEGER REFERENCES cash_sessions(id),
    user_id         INTEGER REFERENCES users(id),
    voided_at       TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_service_pay_order ON service_payments(order_id);

-- Taxas de cartão por adquirente, modalidade (chave da forma de pagamento) e nº de parcelas.
CREATE TABLE card_fees (
    id           INTEGER PRIMARY KEY,
    acquirer     TEXT NOT NULL,
    method       TEXT NOT NULL,
    installments INTEGER NOT NULL CHECK (installments >= 1),
    fee_bp       INTEGER NOT NULL CHECK (fee_bp >= 0 AND fee_bp <= 10000),   -- centésimos de % (199 = 1,99%)
    days         INTEGER NOT NULL DEFAULT 30 CHECK (days >= 0),              -- prazo do 1º recebimento
    UNIQUE (acquirer, method, installments)
);

-- Contas a pagar / despesas / compras de mercadoria.
CREATE TABLE payables (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL CHECK (kind IN ('compra','fixa','variavel')),
    description  TEXT NOT NULL,
    supplier     TEXT,
    category     TEXT,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    due_date     TEXT NOT NULL,                 -- AAAA-MM-DD
    paid_at      TEXT,
    paid_cents   INTEGER,
    pay_method   TEXT,
    notes        TEXT,
    user_id      INTEGER REFERENCES users(id),
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_payables_due ON payables(due_date);

-- Contas a receber manuais (ex.: pendências combinadas com clientes).
CREATE TABLE receivables (
    id           INTEGER PRIMARY KEY,
    customer_id  INTEGER REFERENCES customers(id),
    description  TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    due_date     TEXT NOT NULL,
    received_at  TEXT,
    received_cents INTEGER,
    receive_method TEXT,
    notes        TEXT,
    user_id      INTEGER REFERENCES users(id),
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE returns (
    id             INTEGER PRIMARY KEY,
    sale_id        INTEGER NOT NULL REFERENCES sales(id),
    kind           TEXT NOT NULL CHECK (kind IN ('devolucao','troca')),
    reason         TEXT NOT NULL,
    refund_method  TEXT,
    refund_cents   INTEGER NOT NULL DEFAULT 0,
    user_id        INTEGER NOT NULL REFERENCES users(id),
    authorized_by  INTEGER REFERENCES users(id),
    notes          TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_returns_sale ON returns(sale_id);

CREATE TABLE return_items (
    id           INTEGER PRIMARY KEY,
    return_id    INTEGER NOT NULL REFERENCES returns(id),
    sale_item_id INTEGER NOT NULL REFERENCES sale_items(id),
    qty          INTEGER NOT NULL CHECK (qty > 0),
    amount_cents INTEGER NOT NULL,              -- valor devolvido ao cliente referente a estes itens
    cost_cents   INTEGER NOT NULL,              -- custo das unidades devolvidas
    restock      INTEGER NOT NULL DEFAULT 1,    -- 1 = volta ao estoque; 0 = perda/avaria
    condition_note TEXT
);
CREATE INDEX idx_return_items_si ON return_items(sale_item_id);

CREATE TABLE warranty_claims (
    id             INTEGER PRIMARY KEY,
    sale_id        INTEGER REFERENCES sales(id),
    sale_item_id   INTEGER REFERENCES sale_items(id),
    order_id       INTEGER REFERENCES service_orders(id),
    device_id      INTEGER REFERENCES devices(id),
    customer_name  TEXT,
    customer_phone TEXT,
    item_desc      TEXT NOT NULL,
    defect         TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'aberta' CHECK (status IN ('aberta','em_analise','resolvida','negada')),
    diagnosis      TEXT,
    solution       TEXT,
    resolution     TEXT CHECK (resolution IS NULL OR resolution IN ('reparo','troca','reembolso','negada')),
    cost_cents     INTEGER NOT NULL DEFAULT 0 CHECK (cost_cents >= 0),
    in_warranty    INTEGER NOT NULL DEFAULT 1,
    responsible_id INTEGER REFERENCES users(id),
    opened_by      INTEGER REFERENCES users(id),
    opened_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    closed_at      TEXT
);
CREATE INDEX idx_claims_sale ON warranty_claims(sale_id);

CREATE TABLE inventory_counts (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'aberto' CHECK (status IN ('aberto','finalizado','cancelado')),
    created_by  INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    finished_at TEXT,
    finished_by INTEGER REFERENCES users(id)
);

CREATE TABLE inventory_count_items (
    id           INTEGER PRIMARY KEY,
    count_id     INTEGER NOT NULL REFERENCES inventory_counts(id),
    product_id   INTEGER NOT NULL REFERENCES products(id),
    counted_qty  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (count_id, product_id)
);
