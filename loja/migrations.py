"""Migrações do banco. Cada função recebe a conexão já dentro de uma transação e deve preservar os dados existentes."""
import json

DEFAULT_WARRANTY_TERMS = (
    "TERMO DE GARANTIA DO SERVIÇO\n\n"
    "A garantia cobre defeitos relacionados ao serviço executado e às peças fornecidas pela assistência, "
    "conforme o serviço realizado e a legislação aplicável.\n\n"
    "O prazo de garantia e sua data de término deverão constar nesta ordem de serviço, de acordo com o serviço "
    "prestado e as normas aplicáveis.\n\n"
    "A garantia não exclui os direitos assegurados ao consumidor por lei. A análise de eventuais defeitos será "
    "realizada pela assistência técnica, considerando o serviço executado e as condições do aparelho.\n\n"
    "Danos decorrentes de quedas, contato com líquidos, mau uso ou intervenções posteriores somente poderão ser "
    "considerados para avaliação da cobertura quando houver relação com o defeito reclamado e fundamento técnico "
    "e legal para tanto.\n\n"
    "Ao receber o aparelho, o cliente declara ter conferido as informações registradas nesta ordem de serviço."
)

DEFAULT_SERVICE_CONDITIONS = (
    "Apresente este documento para retirar o aparelho. Aparelhos prontos e não retirados poderão ser alvo de "
    "cobrança de armazenagem somente se isso estiver previsto em contrato assinado pelo cliente. "
    "O orçamento aprovado só pode ser alterado com nova autorização do cliente."
)

# Prazos iniciais por tipo de serviço. São um PONTO DE PARTIDA: o administrador revisa conforme a política da loja.
# 90 dias é o menor prazo aceito pelo sistema (prazo legal para bens e serviços duráveis, CDC art. 26, II); a loja pode conceder mais.
DEFAULT_WARRANTY_TYPES = [
    {"key": "tela", "label": "Troca de tela", "days": 90},
    {"key": "bateria", "label": "Troca de bateria", "days": 90},
    {"key": "conector", "label": "Conector / dock de carga", "days": 90},
    {"key": "placa", "label": "Reparo de placa", "days": 90},
    {"key": "software", "label": "Software / desbloqueio", "days": 90},
    {"key": "outros", "label": "Outros serviços", "days": 90},
]

NEW_SETTINGS = {
    "os_warranty_terms": DEFAULT_WARRANTY_TERMS,
    "os_service_conditions": DEFAULT_SERVICE_CONDITIONS,
    "os_warranty_types": json.dumps(DEFAULT_WARRANTY_TYPES, ensure_ascii=False),
    "os_print_default": "termico",      # termico | a4
    "os_thermal_width_mm": "72",        # largura útil da bobina de 80 mm na Epson TM-T20 (ajustável)
}


def seed_new_settings(conn):
    for k, v in NEW_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?,?)", (k, v))


def _v2_pecas_avulsas_custos_garantia(conn):
    """Ordem de serviço: peças avulsas (sem cadastro no estoque), custo que pode ficar pendente, custos extras e garantia por OS."""
    conn.execute("""
        CREATE TABLE service_order_parts_new (
            id               INTEGER PRIMARY KEY,
            order_id         INTEGER NOT NULL REFERENCES service_orders(id),
            product_id       INTEGER REFERENCES products(id),
            kind             TEXT NOT NULL DEFAULT 'estoque' CHECK (kind IN ('estoque','avulsa')),
            name             TEXT NOT NULL,
            compat           TEXT,
            qty              INTEGER NOT NULL CHECK (qty > 0),
            unit_cost_cents  INTEGER CHECK (unit_cost_cents IS NULL OR unit_cost_cents >= 0),
            unit_price_cents INTEGER NOT NULL DEFAULT 0 CHECK (unit_price_cents >= 0),
            part_status      TEXT CHECK (part_status IS NULL OR part_status IN
                                 ('aguardando_compra','encomendada','recebida','instalada','cancelada')),
            supplier         TEXT,
            notes            TEXT,
            cancel_after_purchase INTEGER NOT NULL DEFAULT 0,
            cost_updated_by  INTEGER REFERENCES users(id),
            cost_updated_at  TEXT,
            created_by       INTEGER REFERENCES users(id),
            created_at       TEXT,
            removed_at       TEXT,
            CHECK ((kind = 'estoque' AND product_id IS NOT NULL) OR (kind = 'avulsa' AND product_id IS NULL))
        )""")
    conn.execute(
        "INSERT INTO service_order_parts_new(id, order_id, product_id, kind, name, qty, unit_cost_cents, unit_price_cents, removed_at)"
        " SELECT id, order_id, product_id, 'estoque', name, qty, unit_cost_cents, unit_price_cents, removed_at FROM service_order_parts")
    conn.execute("DROP TABLE service_order_parts")
    conn.execute("ALTER TABLE service_order_parts_new RENAME TO service_order_parts")
    conn.execute("CREATE INDEX idx_os_parts ON service_order_parts(order_id)")

    conn.execute("ALTER TABLE service_orders ADD COLUMN warranty_type TEXT")
    conn.execute("ALTER TABLE service_orders ADD COLUMN warranty_start TEXT")
    conn.execute("ALTER TABLE service_orders ADD COLUMN warranty_end TEXT")
    conn.execute("ALTER TABLE service_orders ADD COLUMN warranty_terms TEXT")
    conn.execute("ALTER TABLE service_orders ADD COLUMN other_cost_cents INTEGER NOT NULL DEFAULT 0 CHECK (other_cost_cents >= 0)")
    conn.execute("ALTER TABLE service_orders ADD COLUMN other_cost_note TEXT")
    # Garantia de OS já entregues passa a ficar registrada (mesma conta que o sistema já fazia: entrega + dias).
    conn.execute("UPDATE service_orders SET warranty_start=date(delivered_at),"
                 " warranty_end=date(delivered_at, '+' || warranty_days || ' day') WHERE delivered_at IS NOT NULL")
    seed_new_settings(conn)


MIGRATIONS = {2: _v2_pecas_avulsas_custos_garantia}
