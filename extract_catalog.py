"""Extrator robusto do catalogo de produtos (catalogo_json.nx1).

Os JSONs de produto sao WideMemo no heap NXHD; produtos maiores cruzam blocos
(fragmentacao com descritores flag 0x05). Em vez de remontar fragmento a
fragmento, concatenamos a regiao de dados de todos os blocos NXHD, decodificamos
como UTF-16-LE e extraimos os objetos JSON por balanceamento de chaves.

Uso: python extract_catalog.py <catalogo_json.nx1> [saida.json]
"""
import struct, json, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nxread

BS = 4096


def decode_blocks(data):
    """Concatena os bytes de payload das entradas de texto (flag 0x04) de todos os
    blocos NXHD, na ordem do arquivo, e decodifica como UTF-16-LE. Isso remonta os
    JSONs que foram fragmentados entre blocos consecutivos."""
    buf = bytearray()
    for i in range(len(data) // BS):
        o = i * BS
        if data[o:o + 4] != b"NXHD":
            continue
        for flag, length, payload in nxread.parse_heap_block(data[o:o + BS]):
            if flag != 0x04:
                continue
            # payload = length-1 bytes; se impar, ha 1 byte de padding inicial
            if len(payload) & 1:
                payload = payload[1:]
            buf += payload
    return buf.decode("utf-16-le", "replace")


def extract_objects(text):
    """Extrai objetos JSON de produto por contagem de chaves."""
    out = []
    for m in re.finditer(r'\{ "(?:ProductId|ShopCode)"', text):
        s = m.start()
        depth = 0
        instr = False
        esc = False
        end = None
        for j in range(s, min(s + 8000, len(text))):
            c = text[j]
            if esc:
                esc = False
                continue
            if c == "\\":
                esc = True
                continue
            if c == '"':
                instr = not instr
                continue
            if instr:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        if end:
            try:
                out.append(json.loads(text[s:end]))
            except Exception:
                pass
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else print("falta arquivo catalogo_json.nx1")
    out = sys.argv[2] if len(sys.argv) > 2 else print("falta diretorio de saida")
    data = open(path, "rb").read()
    text = decode_blocks(data)
    objs = extract_objects(text)
    prods = {o["ProductId"]: o for o in objs if "ProductId" in o}
    json.dump(list(prods.values()), open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"objetos extraidos={len(objs)} produtos_unicos={len(prods)}")
    print(f"saida: {out}")
    for pid in list(prods)[:6]:
        print(f"  {pid} -> {prods[pid].get('ProductName')!r} cod={prods[pid].get('ProductCode')!r}")


if __name__ == "__main__":
    main()
