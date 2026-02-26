"""Migração: adiciona coluna `cor` às tabelas product_image e product_image_url."""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'ferrato.db')


def coluna_existe(cur, tabela, coluna):
    cur.execute(f"PRAGMA table_info({tabela})")
    return any(row[1] == coluna for row in cur.fetchall())


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for tabela in ('product_image', 'product_image_url'):
        if coluna_existe(cur, tabela, 'cor'):
            print(f"[OK] {tabela}.cor já existe — pulando.")
        else:
            cur.execute(f"ALTER TABLE {tabela} ADD COLUMN cor VARCHAR(50) NOT NULL DEFAULT ''")
            print(f"[OK] Coluna `cor` adicionada a {tabela}.")

    conn.commit()
    conn.close()
    print("Migração concluída.")


if __name__ == '__main__':
    main()
