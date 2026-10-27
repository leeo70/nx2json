"""Dump completo de todos os .nx1 de um diretorio para JSON.

Uso: python dump_all.py <dir_origem> <dir_saida>
"""
import os, sys, json, time, traceback
import nxread

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else print("falta diretorio de origem")
    out = sys.argv[2] if len(sys.argv) > 2 else print("falta diretorio de saida")
    os.makedirs(out, exist_ok=True)

    files = sorted(f for f in os.listdir(src) if f.lower().endswith(".nx1"))
    total = len(files)
    print(f"[dump] {total} arquivos .nx1 em {src}", flush=True)

    summary = []
    ok = err = 0
    t0 = time.time()
    for i, name in enumerate(files, 1):
        path = os.path.join(src, name)
        size = os.path.getsize(path)
        t = time.time()
        try:
            fields, reclen, recs, (base, slot) = nxread.read_table(path)
            dst = os.path.join(out, name.replace(".nx1", ".json").replace(".NX1", ".json"))
            json.dump(recs, open(dst, "w", encoding="utf-8"),
                      ensure_ascii=False, default=str)
            dt = time.time() - t
            print(f"[{i:>3}/{total}] OK  {name:<32} campos={len(fields):<3} "
                  f"reg={len(recs):<8} {size/1e6:7.1f}MB {dt:6.1f}s", flush=True)
            summary.append({"file": name, "fields": len(fields), "reclen": reclen,
                            "records": len(recs), "base": base, "slot": slot,
                            "size_bytes": size, "status": "ok"})
            ok += 1
        except Exception as e:
            print(f"[{i:>3}/{total}] ERR {name:<32} {e!r}", flush=True)
            summary.append({"file": name, "status": "error",
                            "error": repr(e), "trace": traceback.format_exc()})
            err += 1

    json.dump(summary, open(os.path.join(out, "_summary.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n[dump] concluido em {time.time()-t0:.0f}s  ok={ok} err={err}  "
          f"saida={out}", flush=True)

if __name__ == "__main__":
    main()
