# nx2json

Field toolkit to migrate data out of NexusDB (`.nx1`) files from legacy POS /
ERP systems to open formats (JSON and SQLite). Pure Python, standard library
only, no `pip install` needed.

Built for the real workflow: show up at the client, close the running system,
copy the `.nx1` files, run one command, leave with a portable backup that is
ready to feed the new system.

## What it does

- **Reads** NexusDB `.nx1` tables (NXDH blocks + NXHD heap blobs) with a
  pragmatic layout detector. Handles `nxtGuid`, `nxtCurrency`, `nxtDateTime`,
  `nxtWideString`, `nxtBlobMemo`, `nxtBlobWideMemo` and the common integer /
  float / boolean / autoinc types.
- **Dumps** every table to one `.json` file (plus a `_summary.json` with
  per-table counts and parse status).
- **Rebuilds** sale lines (`vendas_itens.json`) by joining `MovEst → Produto`
  on `MovEst.Produto = Produto.ID` (~99.8% resolution on typical bases).
- **Extracts** a secondary product catalog from the `catalogo_json.nx1` blob
  stream (WideMemo entries fragmented across NXHD blocks).
- **Consolidates** everything into a single `dados.sqlite` with typed schema
  and indexes for the migration-critical tables, dynamic schema for the
  others, plus `_meta` and `_extract_summary` metadata tables.

## Install

```bash
git clone https://github.com/leeo70/nx2json.git
cd nx2json
# nothing else to install; stdlib only
```

Tested on Python 3.10 - 3.13 (Windows).

## Usage

End-to-end:

```powershell
# 1. On the client machine: stop the POS service, then copy the .nx1 files
#    to a safe folder (one folder per client, one per date).
#    Example layout:
#      C:\Nex\backups\acme\20260620\
#          *.nx1

# 2. Run the full pipeline.
python rodar_dump.py "C:\Nex\backups\acme\20260620"
```

What that single command does:

1. Dumps every `.nx1` to `_json_dump/<Table>.json` + `_json_dump/_summary.json`.
2. Rebuilds `_json_dump/vendas_itens.json` (sale lines with resolved product).
3. Extracts `_json_dump/catalogo_produtos.json` (secondary product catalog).
4. Builds `_json_dump/dados.sqlite` from the JSONs (typed + indexed schema).

Pass `--no-sqlite` to stop after step 3.

Validate the result:

```powershell
# JSON mode (default)
python validar_dump.py "C:\Nex\backups\acme\20260620\_json_dump"

# SQLite mode (equivalent checks, faster on large bases)
python validar_dump.py "C:\Nex\backups\acme\20260620\_json_dump" --sqlite
```

Regenerate only the SQLite from an existing JSON dump:

```powershell
python json_to_sqlite.py "C:\...\_json_dump" "C:\...\_json_dump\dados.sqlite"
```

Inspect a single table (useful for debugging a schema mismatch):

```powershell
python nxread.py Produto.nx1
python nxschema.py Produto.nx1
```

## SQLite schema

The `dados.sqlite` is the same content as the JSONs, but queryable. Tables:

- **Typed, indexed** (one per migration-critical entity):
  `Produto`, `Cliente`, `Tran`, `MovEst`, `Caixa`, `Categoria`,
  `vendas_itens`, `catalogo_produtos`.
  Fields not listed in the typed schema are preserved as JSON in the `_raw`
  column (lossless).
- **Dynamic** (one per unknown `.nx1`): all columns `TEXT` plus a `_raw`
  column holding the original JSON record.
- **Metadata**: `_meta` (schema_version, tool_version, extracted_at,
  source_dir) and `_extract_summary` (per-`.nx1` status, field count, record
  count, parse error if any).

Typical queries the migration consumer runs:

```sql
-- Top 20 best-selling products
SELECT produto_nome, SUM(quantidade) qty, SUM(total) revenue
FROM vendas_itens
GROUP BY produto_id
ORDER BY qty DESC
LIMIT 20;

-- Customers with contact info
SELECT ID, Nome, Telefone, Email FROM Cliente
WHERE Telefone IS NOT NULL OR Email IS NOT NULL;

-- Monthly revenue
SELECT substr(DataHora,1,7) AS month, SUM(Total) AS total
FROM Tran WHERE Cancelado = 0
GROUP BY month ORDER BY month;
```

The database opens in any SQLite tool: DBeaver, SQLiteStudio, DB Browser,
VS Code SQLite extensions, `sqlite3` CLI.

## Known limitations

- **6 tables fail schema parse** (`max() iterable argument is empty`):
  `MoedasCustom`, `ProdutoValidade`, `RegistrosRemovidos`, `TEF_Config`,
  `TEF_Tran`, `Usuario`. None of these are needed for the standard migration
  (products / customers / sales / sale lines). `Usuario` is pending a parser
  fix.
- **Large binary blobs** (product photos, customer photos, big documents)
  are not fully extracted yet. They appear as `<blob#...>` or partial base64.
  **Text blobs** (notes, embedded JSON, NF-e XML) extract correctly (~99.9%).
- **`RecDel.nx1` comes out empty** on purpose: it is a deletion log,
  irrelevant for migration.

## Files

| File                       | Purpose                                                          |
|----------------------------|------------------------------------------------------------------|
| `rodar_dump.py`            | **Entrypoint**. End-to-end pipeline for field use.               |
| `dump_all.py`              | Step 1: dump every `.nx1` to JSON.                               |
| `build_vendas_itens.py`    | Step 2: rebuild sale lines joining `MovEst → Produto`.           |
| `extract_catalog.py`       | Step 3: extract `catalogo_json.nx1` blob stream.                 |
| `json_to_sqlite.py`        | Step 4: consolidate JSONs into typed `dados.sqlite`.             |
| `validar_dump.py`          | Validation (counts, resolution rate). JSON or SQLite.            |
| `nxread.py`                | Library: read one `.nx1` to records (block + heap scanner).      |
| `nxschema.py`              | Library: parse NexusDB table layout (field types and offsets).   |
| `LEIAME.md`                | Portuguese version of this README (field manual).                |

## License

MIT. See [`LICENSE`](LICENSE).

## Contributing

The known limitations list is a roadmap. PRs welcome for:

- Fixing the `Usuario` / `TEF_*` / `MoedasCustom` schema parsers.
- Full extraction of binary blobs (write to a sidecar folder, cite in JSON).
- Additional typed schemas in `json_to_sqlite.KNOWN_SCHEMAS` for tables we
  have not seen yet.
- Reverse pipeline (write a `.nx1` back) — not planned, but documented need.

When filing an issue, include the output of `python nxschema.py <table>.nx1`
for the problematic table. Do not attach real client data.
