"""Validacao rapida de um _json_dump gerado pelo rodar_dump.py.

Mostra contagens das tabelas-chave, a taxa de item->produto resolvido e as
tabelas que falharam, para conferir em campo antes de sair do cliente.

Uso:
  python validar_dump.py <pasta _json_dump>           # modo JSON (default)
  python validar_dump.py <arquivo.sqlite> --sqlite    # modo SQLite
  python validar_dump.py <pasta _json_dump> --sqlite  # usa <pasta>/dados.sqlite
"""
import sys
import os
import json
import sqlite3


CHAVE = ["Produto", "Cliente", "Caixa", "Tran", "MovEst", "ITran",
         "Categoria", "Subcategoria", "Marca"]


def load(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Modo JSON (original)
# ---------------------------------------------------------------------------
def validar_json(d):
    print(f"validando (JSON): {d}\n")

    print("== tabelas-chave (nº de registros) ==")
    for name in CHAVE:
        p = os.path.join(d, name + ".json")
        if os.path.exists(p):
            arr = load(p)
            n = len(arr) if isinstance(arr, list) else "?"
            print(f"  {name:<14} {n}")
        else:
            print(f"  {name:<14} (ausente)")

    vi = os.path.join(d, "vendas_itens.json")
    if os.path.exists(vi):
        arr = load(vi) or []
        n = len(arr)
        res = sum(1 for x in arr if x.get("produto_resolvido"))
        print("\n== item -> produto (vendas_itens.json) ==")
        print(f"  linhas: {n}")
        if n:
            print(f"  resolvido via cadastro: {res} ({100*res/n:.1f}%)")
            print(f"  via nome snapshot     : {n-res} ({100*(n-res)/n:.1f}%)")
        sem_nome = sum(1 for x in arr if not x.get("produto_nome"))
        print(f"  SEM nome de produto   : {sem_nome}")

    cp = os.path.join(d, "catalogo_produtos.json")
    if os.path.exists(cp):
        arr = load(cp) or []
        print(f"\n== catalogo_produtos.json: {len(arr)} produtos ==")

    s = os.path.join(d, "_summary.json")
    if os.path.exists(s):
        summ = load(s) or []
        errs = [x for x in summ if x.get("status") == "error"]
        vazias = [x for x in summ if x.get("status") == "ok" and x.get("records") == 0]
        print(f"\n== status do dump ==")
        print(f"  ok: {sum(1 for x in summ if x.get('status')=='ok')}  erro: {len(errs)}")
        if errs:
            print("  tabelas com ERRO (esperado p/ algumas - ver LEIAME secao 5):")
            for x in errs:
                print(f"    - {x['file']}")
        print(f"  tabelas vazias (0 registros): {len(vazias)}")

    print("\nOK. Confira os números com o cliente antes de sair.")


# ---------------------------------------------------------------------------
# Modo SQLite
# ---------------------------------------------------------------------------
def _count(cur, table):
    try:
        cur.execute(f'SELECT COUNT(*) FROM "{table}"')
        return cur.fetchone()[0]
    except sqlite3.OperationalError:
        return None


def validar_sqlite(db_path):
    print(f"validando (SQLite): {db_path}\n")
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Metadados da extracao
        try:
            meta = {r["key"]: r["value"] for r in cur.execute('SELECT key,value FROM _meta')}
            print("== metadados ==")
            for k in ("schema_version", "tool_version", "extracted_at",
                      "source_dir", "nx1_count"):
                if k in meta:
                    print(f"  {k:<16} {meta[k]}")
            print()
        except sqlite3.OperationalError:
            print("  (_meta ausente)\n")

        print("== tabelas-chave (nº de registros) ==")
        for name in CHAVE:
            n = _count(cur, name)
            if n is None:
                print(f"  {name:<14} (ausente)")
            else:
                print(f"  {name:<14} {n}")

        # vendas_itens
        n_vi = _count(cur, "vendas_itens")
        if n_vi is not None:
            print("\n== item -> produto (vendas_itens) ==")
            print(f"  linhas: {n_vi}")
            if n_vi:
                cur.execute(
                    'SELECT SUM(CASE WHEN produto_resolvido THEN 1 ELSE 0 END) r, '
                    'SUM(CASE WHEN produto_nome IS NULL OR produto_nome=\'\' '
                    'THEN 1 ELSE 0 END) sn FROM vendas_itens'
                )
                r, sn = cur.fetchone()
                r = r or 0
                sn = sn or 0
                print(f"  resolvido via cadastro: {r} ({100*r/n_vi:.1f}%)")
                print(f"  via nome snapshot     : {n_vi-r} ({100*(n_vi-r)/n_vi:.1f}%)")
                print(f"  SEM nome de produto   : {sn}")

        # catalogo
        n_cat = _count(cur, "catalogo_produtos")
        if n_cat is not None:
            print(f"\n== catalogo_produtos: {n_cat} produtos ==")

        # status
        try:
            cur.execute('SELECT COUNT(*) FROM _extract_summary WHERE status=\'ok\'')
            ok = cur.fetchone()[0]
            cur.execute(
                'SELECT file FROM _extract_summary WHERE status=\'error\' ORDER BY file'
            )
            errs = [r["file"] for r in cur.fetchall()]
            cur.execute(
                'SELECT COUNT(*) FROM _extract_summary '
                'WHERE status=\'ok\' AND records=0'
            )
            vazias = cur.fetchone()[0]
            print(f"\n== status do dump ==")
            print(f"  ok: {ok}  erro: {len(errs)}")
            if errs:
                print("  tabelas com ERRO (esperado p/ algumas - ver LEIAME secao 5):")
                for name in errs:
                    print(f"    - {name}")
            print(f"  tabelas vazias (0 registros): {vazias}")
        except sqlite3.OperationalError:
            print("\n  (_extract_summary ausente)")

        print("\nOK. Confira os números com o cliente antes de sair.")
    finally:
        conn.close()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}

    if not args:
        print(__doc__)
        sys.exit(1)

    target = os.path.abspath(args[0])
    use_sqlite = "--sqlite" in flags

    if use_sqlite:
        if os.path.isdir(target):
            db = os.path.join(target, "dados.sqlite")
        else:
            db = target
        if not os.path.isfile(db):
            print(f"ERRO: SQLite nao encontrado: {db}")
            sys.exit(1)
        validar_sqlite(db)
    else:
        if not os.path.isdir(target):
            print(f"ERRO: pasta nao existe: {target}")
            sys.exit(1)
        validar_json(target)


if __name__ == "__main__":
    main()
