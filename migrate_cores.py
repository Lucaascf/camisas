"""Migração: adiciona cor/cor_hex a product_variant e cor a order_item."""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'ferrato.db')


def migrar():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # --- 1. Verificar se já foi migrado ---
    cur.execute("PRAGMA table_info(product_variant)")
    colunas = [row['name'] for row in cur.fetchall()]
    if 'cor' in colunas:
        print("product_variant já possui coluna 'cor' — migração já aplicada.")
    else:
        print("Recriando tabela product_variant com cor + cor_hex...")

        cur.executescript("""
            BEGIN;

            CREATE TABLE product_variant_new (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id  INTEGER NOT NULL REFERENCES product(id),
                tamanho     VARCHAR(10) NOT NULL DEFAULT '',
                cor         VARCHAR(50) NOT NULL DEFAULT '',
                cor_hex     VARCHAR(7)  NOT NULL DEFAULT '',
                estoque     INTEGER     NOT NULL DEFAULT 0,
                ativo       BOOLEAN     NOT NULL DEFAULT 1,
                criado_em   DATETIME,
                UNIQUE (product_id, tamanho, cor)
            );

            INSERT INTO product_variant_new
                (id, product_id, tamanho, cor, cor_hex, estoque, ativo, criado_em)
            SELECT id, product_id, tamanho, '', '', estoque, ativo, criado_em
            FROM product_variant;

            DROP TABLE product_variant;

            ALTER TABLE product_variant_new RENAME TO product_variant;

            COMMIT;
        """)
        print("  product_variant recriada com sucesso.")

    # --- 2. order_item: adicionar coluna cor ---
    cur.execute("PRAGMA table_info(order_item)")
    colunas_oi = [row['name'] for row in cur.fetchall()]
    if 'cor' in colunas_oi:
        print("order_item já possui coluna 'cor' — sem ação necessária.")
    else:
        print("Adicionando coluna 'cor' a order_item...")
        cur.execute("ALTER TABLE order_item ADD COLUMN cor VARCHAR(50) DEFAULT NULL")
        conn.commit()
        print("  Coluna 'cor' adicionada a order_item.")

    conn.close()
    print("\nMigração concluída com sucesso.")


if __name__ == '__main__':
    migrar()
