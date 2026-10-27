"""Converte um _json_dump (saida do rodar_dump.py) para um unico SQLite.

Le os .json gerados pelas etapas 1-3 do pipeline e materializa em um banco
SQLite com schema tipado para as tabelas-chave da migracao e schema dinamico
para as demais. O JSON continua existindo lado a lado; este passo e aditivo.

Uso:
    python json_to_sqlite.py <pasta _json_dump> [saida.sqlite]

Se <saida.sqlite> for omitida, cria "dados.sqlite" dentro de <pasta _json_dump>.
"""
import os
import sys
import json
import sqlite3
import datetime


SCHEMA_VERSION = 1
TOOL_VERSION = "nx2json/json_to_sqlite@1"


# ---------------------------------------------------------------------------
# Schemas tipados das tabelas-chave da migracao.
# Cada entrada mapeia nome_do_arquivo (sem .json) para:
#   columns: lista de (nome_col, tipo_sql, chave_no_json_ou_None_se_mesmo_nome)
#   primary_key: lista de nomes de coluna
#   indexes: lista de listas (cada sublista = colunas de um indice)
# Campos nao listados nas columns vao para a coluna _raw como JSON.
# ---------------------------------------------------------------------------
KNOWN_SCHEMAS = {
    "Produto": {
        "columns": [
            ("ID", "INTEGER", None),
            ("UID", "TEXT", None),
            ("Codigo", "TEXT", None),
            ("Descricao", "TEXT", None),
            ("Preco", "REAL", None),
            ("Categoria", "TEXT", None),
            ("uid_categoria", "TEXT", None),
            ("NCM", "TEXT", None),
            ("EstoqueAtual", "REAL", None),
        ],
        "primary_key": ["ID"],
        "indexes": [["Codigo"], ["Descricao"], ["UID"]],
    },
    "Cliente": {
        "columns": [
            ("ID", "INTEGER", None),
            ("UID", "TEXT", None),
            ("Nome", "TEXT", None),
            ("CpfCnpj", "TEXT", None),
            ("Telefone", "TEXT", None),
            ("Email", "TEXT", None),
            ("Endereco", "TEXT", None),
            ("Cidade", "TEXT", None),
            ("UF", "TEXT", None),
            ("CEP", "TEXT", None),
            ("Obs", "TEXT", None),
        ],
        "primary_key": ["ID"],
        "indexes": [["Nome"], ["CpfCnpj"], ["UID"]],
    },
    "Caixa": {
        "columns": [
            ("ID", "INTEGER", None),
            ("UID", "TEXT", None),
            ("DataHora", "TEXT", None),
            ("Valor", "REAL", None),
            ("Tipo", "TEXT", None),
            ("Descricao", "TEXT", None),
        ],
        "primary_key": ["ID"],
        "indexes": [["DataHora"], ["UID"]],
    },
    "Tran": {
        "columns": [
            ("ID", "INTEGER", None),
            ("UID", "TEXT", None),
            ("DataHora", "TEXT", None),
            ("Cliente", "INTEGER", None),
            ("Total", "REAL", None),
            ("TotLiq", "REAL", None),
            ("Desconto", "REAL", None),
            ("TipoTran", "TEXT", None),
            ("Cancelado", "INTEGER", None),
            ("Descricao", "TEXT", None),
            ("Obs", "TEXT", None),
        ],
        "primary_key": ["ID"],
        "indexes": [["DataHora"], ["Cliente"], ["UID"]],
    },
    "MovEst": {
        "columns": [
            ("uid_itran", "TEXT", None),
            ("Tran", "INTEGER", None),
            ("Item", "INTEGER", None),
            ("Produto", "INTEGER", None),
            ("uid_produto", "TEXT", None),
            ("Descr", "TEXT", None),
            ("Categoria", "TEXT", None),
            ("Quant", "REAL", None),
            ("Unitario", "REAL", None),
            ("Desconto", "REAL", None),
            ("Total", "REAL", None),
            ("TotLiq", "REAL", None),
            ("CustoU", "REAL", None),
            ("TipoTran", "TEXT", None),
            ("Cancelado", "INTEGER", None),
            ("Pend", "INTEGER", None),
            ("DataHora", "TEXT", None),
            ("Obs", "TEXT", None),
        ],
        "primary_key": ["Tran", "Item"],
        "indexes": [["Produto"], ["DataHora"], ["uid_itran"]],
    },
    "Categoria": {
        "columns": [
            ("ID", "INTEGER", None),
            ("UID", "TEXT", None),
            ("Descricao", "TEXT", None),
        ],
        "primary_key": ["ID"],
        "indexes": [["Descricao"]],
    },
    "vendas_itens": {
        "columns": [
            ("venda_id", "INTEGER", None),
            ("item", "INTEGER", None),
            ("uid_itran", "TEXT", None),
            ("produto_id", "INTEGER", None),
            ("produto_uid", "TEXT", None),
            ("produto_nome", "TEXT", None),
            ("produto_codigo", "TEXT", None),
            ("categoria", "TEXT", None),
            ("quantidade", "REAL", None),
            ("unitario", "REAL", None),
            ("desconto", "REAL", None),
            ("total", "REAL", None),
            ("total_liq", "REAL", None),
            ("custo_unit", "REAL", None),
            ("obs", "TEXT", None),
            ("pendente", "INTEGER", None),
            ("tipo_tran", "TEXT", None),
            ("cancelado", "INTEGER", None),
            ("data_hora", "TEXT", None),
            ("produto_resolvido", "INTEGER", None),
        ],
        "primary_key": ["venda_id", "item"],
        "indexes": [["produto_id"], ["data_hora"], ["produto_codigo"]],
    },
}


# ---------------------------------------------------------------------------
# Helpers de normalizacao
# ---------------------------------------------------------------------------
def _coerce(value, sql_type):
    """Converte valor JSON para o tipo SQL alvo sem quebrar na migracao."""
    if value is None:
        return None
    # Blobs base64 e marcadores "<blob#...>" nao viram colunas tipadas;
    # ficam preservados no _raw. Aqui retornamos None para a coluna tipada.
    if isinstance(value, dict) and "__blob_b64__" in value:
        return None
    if isinstance(value, str) and value.startswith("<blob#"):
        return None
    try:
        if sql_type == "INTEGER":
            if isinstance(value, bool):
                return 1 if value else 0
            if isinstance(value, (int,)):
                return value
            if isinstance(value, float):
                return int(value)
            if isinstance(value, str):
                s = value.strip()
                if not s:
                    return None
                return int(float(s))
            return None
        if sql_type == "REAL":
            if isinstance(value, bool):
                return 1.0 if value else 0.0
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                s = value.strip()
                if not s:
                    return None
                return float(s)
            return None
        if sql_type == "TEXT":
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False, default=str)
            return str(value)
    except (TypeError, ValueError):
        return None
    return None


def _sanitize_col_name(name):
    """Nome de coluna seguro para SQLite dinamico (preserva o original no _raw)."""
    out = []
    for ch in name:
        if ch.isalnum() or ch == "_":
            out.append(ch)
        else:
            out.append("_")
    s = "".join(out) or "col"
    if s[0].isdigit():
        s = "_" + s
    return s


def _quote_ident(name):
    return '"' + name.replace('"', '""') + '"'


# ---------------------------------------------------------------------------
# Writer: tabela conhecida (schema tipado)
# ---------------------------------------------------------------------------
def _create_known_table(cur, table, spec):
    cols_sql = []
    for col, typ, _ in spec["columns"]:
        cols_sql.append(f"{_quote_ident(col)} {typ}")
    cols_sql.append('"_raw" TEXT')
    pk = spec.get("primary_key") or []
    if pk:
        pk_cols = ", ".join(_quote_ident(c) for c in pk)
        cols_sql.append(f"PRIMARY KEY ({pk_cols})")
    cur.execute(
        f'CREATE TABLE IF NOT EXISTS {_quote_ident(table)} ({", ".join(cols_sql)})'
    )
    for idx in spec.get("indexes") or []:
        idx_name = f"idx_{table.lower()}_" + "_".join(c.lower() for c in idx)
        cols = ", ".join(_quote_ident(c) for c in idx)
        cur.execute(
            f'CREATE INDEX IF NOT EXISTS {_quote_ident(idx_name)} '
            f'ON {_quote_ident(table)} ({cols})'
        )


def _insert_known_table(cur, table, spec, rows):
    typed_cols = [c for c, _, _ in spec["columns"]]
    all_cols = typed_cols + ["_raw"]
    placeholders = ", ".join("?" for _ in all_cols)
    col_list = ", ".join(_quote_ident(c) for c in all_cols)
    sql = (
        f'INSERT OR REPLACE INTO {_quote_ident(table)} '
        f'({col_list}) VALUES ({placeholders})'
    )
    typed_col_set = set(typed_cols)
    typed_col_by_name = {c: (c, t) for c, t, _ in spec["columns"]}
    batch = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        tuple_vals = []
        for col, typ, _ in spec["columns"]:
            v = row.get(col)
            tuple_vals.append(_coerce(v, typ))
        # _raw guarda os campos nao modelados (sem repetir os ja tipados)
        extra = {k: v for k, v in row.items() if k not in typed_col_set}
        raw_text = json.dumps(extra, ensure_ascii=False, default=str) if extra else None
        tuple_vals.append(raw_text)
        batch.append(tuple(tuple_vals))
        if len(batch) >= 1000:
            cur.executemany(sql, batch)
            batch.clear()
    if batch:
        cur.executemany(sql, batch)


# ---------------------------------------------------------------------------
# Writer: tabela desconhecida (schema dinamico)
# ---------------------------------------------------------------------------
def _create_dynamic_table(cur, table, rows):
    """Para tabela sem schema conhecido: cria colunas TEXT inferidas dos registros."""
    cols = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for k in row.keys():
            san = _sanitize_col_name(k)
            if san in seen:
                continue
            seen.add(san)
            cols.append((k, san))
    cols_sql = [f'{_quote_ident(san)} TEXT' for _, san in cols]
    cols_sql.append('"_raw" TEXT')
    cur.execute(
        f'CREATE TABLE IF NOT EXISTS {_quote_ident(table)} ({", ".join(cols_sql)})'
    )
    return cols  # lista de (nome_original, nome_sanitizado)


def _insert_dynamic_table(cur, table, cols, rows):
    if not cols and not rows:
        return
    all_cols = [san for _, san in cols] + ["_raw"]
    placeholders = ", ".join("?" for _ in all_cols)
    col_list = ", ".join(_quote_ident(c) for c in all_cols)
    sql = (
        f'INSERT INTO {_quote_ident(table)} ({col_list}) VALUES ({placeholders})'
    )
    batch = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        tuple_vals = []
        for orig, _ in cols:
            v = row.get(orig)
            tuple_vals.append(_coerce(v, "TEXT"))
        tuple_vals.append(
            json.dumps(row, ensure_ascii=False, default=str) if row else None
        )
        batch.append(tuple(tuple_vals))
        if len(batch) >= 1000:
            cur.executemany(sql, batch)
            batch.clear()
    if batch:
        cur.executemany(sql, batch)


# ---------------------------------------------------------------------------
# Catalogo e meta
# ---------------------------------------------------------------------------
def _create_catalogo_table(cur):
    cur.execute(
        'CREATE TABLE IF NOT EXISTS catalogo_produtos ('
        '"ProductId" TEXT PRIMARY KEY,'
        '"ProductName" TEXT,'
        '"ProductCode" TEXT,'
        '"ShopCode" TEXT,'
        '"Price" REAL,'
        '"_raw" TEXT'
        ')'
    )
    cur.execute(
        'CREATE INDEX IF NOT EXISTS idx_catalogo_name '
        'ON catalogo_produtos ("ProductName")'
    )


def _insert_catalogo(cur, rows):
    sql = (
        'INSERT OR REPLACE INTO catalogo_produtos '
        '("ProductId","ProductName","ProductCode","ShopCode","Price","_raw") '
        'VALUES (?,?,?,?,?,?)'
    )
    typed = {"ProductId", "ProductName", "ProductCode", "ShopCode", "Price"}
    batch = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        extra = {k: v for k, v in row.items() if k not in typed}
        raw_text = json.dumps(extra, ensure_ascii=False, default=str) if extra else None
        batch.append((
            _coerce(row.get("ProductId"), "TEXT"),
            _coerce(row.get("ProductName"), "TEXT"),
            _coerce(row.get("ProductCode"), "TEXT"),
            _coerce(row.get("ShopCode"), "TEXT"),
            _coerce(row.get("Price"), "REAL"),
            raw_text,
        ))
        if len(batch) >= 1000:
            cur.executemany(sql, batch)
            batch.clear()
    if batch:
        cur.executemany(sql, batch)


def _write_meta(cur, src_dir, nx1_summary):
    cur.execute(
        'CREATE TABLE IF NOT EXISTS _meta ("key" TEXT PRIMARY KEY, "value" TEXT)'
    )
    meta = {
        "schema_version": str(SCHEMA_VERSION),
        "tool_version": TOOL_VERSION,
        "extracted_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_dir": src_dir,
        "nx1_count": str(len(nx1_summary)) if nx1_summary else "0",
    }
    cur.executemany(
        'INSERT OR REPLACE INTO _meta ("key","value") VALUES (?,?)',
        list(meta.items()),
    )


def _write_extract_summary(cur, summary):
    cur.execute(
        'CREATE TABLE IF NOT EXISTS _extract_summary ('
        '"file" TEXT PRIMARY KEY,'
        '"fields" INTEGER,'
        '"reclen" INTEGER,'
        '"records" INTEGER,'
        '"base" INTEGER,'
        '"slot" INTEGER,'
        '"size_bytes" INTEGER,'
        '"status" TEXT,'
        '"error" TEXT'
        ')'
    )
    rows = []
    for s in summary or []:
        if not isinstance(s, dict):
            continue
        rows.append((
            s.get("file"),
            s.get("fields"),
            s.get("reclen"),
            s.get("records"),
            s.get("base"),
            s.get("slot"),
            s.get("size_bytes"),
            s.get("status"),
            s.get("error"),
        ))
    if rows:
        cur.executemany(
            'INSERT OR REPLACE INTO _extract_summary '
            '("file","fields","reclen","records","base","slot",'
            '"size_bytes","status","error") VALUES (?,?,?,?,?,?,?,?,?)',
            rows,
        )


# ---------------------------------------------------------------------------
# Orquestracao
# ---------------------------------------------------------------------------
def convert(json_dir, out_path):
    json_dir = os.path.abspath(json_dir)
    out_path = os.path.abspath(out_path)
    if not os.path.isdir(json_dir):
        raise FileNotFoundError(f"pasta nao existe: {json_dir}")

    # SQLite destino: sempre comeca limpo (idempotente).
    if os.path.exists(out_path):
        os.remove(out_path)

    conn = sqlite3.connect(out_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        cur = conn.cursor()

        summary_path = os.path.join(json_dir, "_summary.json")
        summary = None
        if os.path.exists(summary_path):
            with open(summary_path, encoding="utf-8") as f:
                summary = json.load(f)

        _write_meta(cur, json_dir, summary)
        _write_extract_summary(cur, summary)

        # Lista de .json candidatos (tudo o que nao comeca com "_")
        files = sorted(
            f for f in os.listdir(json_dir)
            if f.lower().endswith(".json") and not f.startswith("_")
        )
        totals = {"known": 0, "dynamic": 0, "catalog": 0, "empty": 0,
                  "skipped": 0, "rows": 0}

        for fname in files:
            table = os.path.splitext(fname)[0]
            path = os.path.join(json_dir, fname)
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                print(f"  (pulado) {fname}: {e!r}")
                totals["skipped"] += 1
                continue

            # catalogo_produtos tem schema proprio
            if table == "catalogo_produtos":
                _create_catalogo_table(cur)
                if isinstance(data, list) and data:
                    _insert_catalogo(cur, data)
                    totals["catalog"] += 1
                    totals["rows"] += len(data)
                    print(f"  catalogo_produtos: {len(data)} produtos")
                else:
                    totals["empty"] += 1
                continue

            if not isinstance(data, list):
                print(f"  (pulado) {fname}: nao e lista JSON")
                totals["skipped"] += 1
                continue

            if not data:
                # Mesmo vazia, cria a tabela se for conhecida (facilita queries).
                if table in KNOWN_SCHEMAS:
                    _create_known_table(cur, table, KNOWN_SCHEMAS[table])
                totals["empty"] += 1
                continue

            if table in KNOWN_SCHEMAS:
                spec = KNOWN_SCHEMAS[table]
                _create_known_table(cur, table, spec)
                _insert_known_table(cur, table, spec, data)
                totals["known"] += 1
                totals["rows"] += len(data)
                print(f"  {table}: {len(data)} registros (schema tipado)")
            else:
                cols = _create_dynamic_table(cur, table, data)
                _insert_dynamic_table(cur, table, cols, data)
                totals["dynamic"] += 1
                totals["rows"] += len(data)
                print(f"  {table}: {len(data)} registros (schema dinamico)")

        conn.commit()
    finally:
        conn.close()

    return totals, out_path


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    json_dir = os.path.abspath(sys.argv[1])
    if len(sys.argv) > 2:
        out_path = os.path.abspath(sys.argv[2])
    else:
        out_path = os.path.join(json_dir, "dados.sqlite")

    print(f"origem : {json_dir}")
    print(f"saida  : {out_path}\n")

    totals, path = convert(json_dir, out_path)
    size_mb = os.path.getsize(path) / 1e6
    print()
    print(f"CONCLUIDO: {path}  ({size_mb:.1f} MB)")
    print(f"  tabelas tipadas   : {totals['known']}")
    print(f"  tabelas dinamicas : {totals['dynamic']}")
    print(f"  catalogo          : {totals['catalog']}")
    print(f"  vazias            : {totals['empty']}")
    print(f"  puladas           : {totals['skipped']}")
    print(f"  linhas inseridas  : {totals['rows']}")


if __name__ == "__main__":
    main()
