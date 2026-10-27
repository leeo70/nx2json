# samples/example_json_dump/

Synthetic fixture of a `_json_dump/` folder. All identifiers, names,
addresses and documents are fake and do not correspond to any real
person or business. Useful to try the pipeline without a `.nx1` capture.

Quick test:

```bash
# From the repo root
python json_to_sqlite.py samples/example_json_dump samples/example_json_dump/dados.sqlite
python validar_dump.py samples/example_json_dump --sqlite
```

Expected: 3 products, 2 customers, 2 sales, 3 sale lines, 100% product
resolution rate, and 1 parse error for `TEF_Config.nx1` (expected per the
known limitations section of the README).

The generated `dados.sqlite` is ignored by `.gitignore` and should not be
committed.
