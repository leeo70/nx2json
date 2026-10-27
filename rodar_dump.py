"""Runner unico para uso em campo: roda todo o pipeline de extracao de um
backup de .nx1 do NexusDB para JSON (e opcionalmente para SQLite).

Faz, em ordem:
  1. dump de TODAS as tabelas .nx1 -> JSON (dump_all)
  2. reconstrucao das linhas de venda com produto (build_vendas_itens)
  3. extracao do catalogo de produtos (extract_catalog) -- secundario
  4. conversao dos JSONs gerados para um SQLite unico (json_to_sqlite)
     -- pulado se o argumento --no-sqlite for passado

Uso:
  python rodar_dump.py <pasta_com_nx1> [pasta_saida] [--no-sqlite]

Se <pasta_saida> for omitida, cria "_json_dump" dentro da pasta de origem.
O SQLite e gravado em "<pasta_saida>/dados.sqlite".
"""
import sys, os, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}

    if not args:
        print(__doc__)
        sys.exit(1)
    src = os.path.abspath(args[0])
    out = os.path.abspath(args[1]) if len(args) > 1 else os.path.join(src, "_json_dump")
    make_sqlite = "--no-sqlite" not in flags

    if not os.path.isdir(src):
        print(f"ERRO: pasta de origem nao existe: {src}")
        sys.exit(1)
    nx1 = [f for f in os.listdir(src) if f.lower().endswith(".nx1")]
    if not nx1:
        print(f"ERRO: nenhum arquivo .nx1 encontrado em {src}")
        sys.exit(1)
    os.makedirs(out, exist_ok=True)
    print(f"origem : {src}  ({len(nx1)} arquivos .nx1)")
    print(f"saida  : {out}")
    print(f"sqlite : {'sim' if make_sqlite else 'nao (--no-sqlite)'}\n")

    t0 = time.time()
    total = 4 if make_sqlite else 3

    print("=" * 60)
    print(f"[1/{total}] DUMP de todas as tabelas .nx1 -> JSON")
    print("=" * 60)
    import dump_all
    sys.argv = ["dump_all.py", src, out]
    dump_all.main()

    print("\n" + "=" * 60)
    print(f"[2/{total}] Reconstruindo linhas de venda (item -> produto)")
    print("=" * 60)
    try:
        import build_vendas_itens
        sys.argv = ["build_vendas_itens.py", src, out]
        build_vendas_itens.main()
    except Exception as e:
        print(f"  (pulado) MovEst/Produto indisponivel: {e!r}")

    print("\n" + "=" * 60)
    print(f"[3/{total}] Extraindo catalogo de produtos (secundario)")
    print("=" * 60)
    cat = os.path.join(src, "catalogo_json.nx1")
    if os.path.exists(cat):
        try:
            import extract_catalog
            sys.argv = ["extract_catalog.py", cat, os.path.join(out, "catalogo_produtos.json")]
            extract_catalog.main()
        except Exception as e:
            print(f"  (pulado) erro: {e!r}")
    else:
        print("  catalogo_json.nx1 nao encontrado - pulado")

    if make_sqlite:
        print("\n" + "=" * 60)
        print(f"[4/{total}] Consolidando JSONs em SQLite")
        print("=" * 60)
        try:
            import json_to_sqlite
            sqlite_path = os.path.join(out, "dados.sqlite")
            totals, path = json_to_sqlite.convert(out, sqlite_path)
            size_mb = os.path.getsize(path) / 1e6
            print(f"  sqlite: {path}  ({size_mb:.1f} MB, {totals['rows']} linhas)")
            print(f"  tabelas tipadas={totals['known']}  "
                  f"dinamicas={totals['dynamic']}  catalogo={totals['catalog']}")
        except Exception as e:
            print(f"  (pulado) erro no SQLite: {e!r}")

    print(f"\nCONCLUIDO em {time.time()-t0:.0f}s. Saida em: {out}")


if __name__ == "__main__":
    main()
