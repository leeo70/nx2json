"""Leitor de tabelas NexusDB .nx1 -> registros Python/JSON.

Cobre: schema (layout fisico), varredura de blocos NXDH, decodificacao por tipo.
Blobs (nxtBlob*) sao resolvidos do heap NXHD quando possivel.
"""
import struct, datetime, importlib.util, os, json, sys, base64

# --- schema --------------------------------------------------------------
_spec_src = open(os.path.join(os.path.dirname(__file__), "nxschema.py")).read().split("if __name__")[0]
_ns = {}
exec(_spec_src, _ns)
parse_fields = _ns["parse_fields"]

BS = 4096
EPOCH = datetime.datetime(1899, 12, 30)

def guid(s):
    if s == b"\x00" * 16:
        return None
    d1, d2, d3 = struct.unpack_from("<IHH", s, 0)
    r = s[8:]
    return f"{{{d1:08X}-{d2:04X}-{d3:04X}-{r[:2].hex().upper()}-{r[2:].hex().upper()}}}"

def ansi_str(buf):
    z = buf.find(b"\x00")
    if z >= 0: buf = buf[:z]
    return buf.decode("latin1", "replace")

def wide_str(buf):
    # NexusDB WideString: buffer fixo UTF-16-LE terminado em nulo (sem prefixo)
    s = buf.decode("utf-16-le", "replace")
    z = s.find("\x00")
    return s[:z] if z >= 0 else s

def decode_field(rec, f, heap):
    o, sz, t = f["offset"], f["size"], f["type"]
    raw = rec[o:o + sz]
    if t in ("nxtByte",):                 return raw[0]
    if t in ("nxtBoolean",):              return raw[0] != 0
    if t == "nxtWord16":                  return struct.unpack_from("<H", raw, 0)[0]
    if t == "nxtWord32":                  return struct.unpack_from("<I", raw, 0)[0]
    if t == "nxtAutoInc":                 return struct.unpack_from("<i", raw, 0)[0]
    if t == "nxtInt32":                   return struct.unpack_from("<i", raw, 0)[0]
    if t == "nxtGuid":                    return guid(raw)
    if t == "nxtCurrency":                return struct.unpack_from("<q", raw, 0)[0] / 10000.0
    if t == "nxtDouble":                  return struct.unpack_from("<d", raw, 0)[0]
    if t == "nxtDateTime":
        # NexusDB: double = milissegundos desde 0001-01-01
        ms = struct.unpack_from("<d", raw, 0)[0]
        if ms == 0 or not (1e11 < ms < 7e13): return None
        try: return (datetime.datetime(1, 1, 1) + datetime.timedelta(milliseconds=ms) - datetime.timedelta(days=2)).isoformat()
        except Exception: return None
    if t == "nxtDate":
        # double = milissegundos desde 0001-01-01 (parte de data)
        ms = struct.unpack_from("<d", raw, 0)[0] if sz == 8 else struct.unpack_from("<i", raw, 0)[0] * 86400000.0
        if ms == 0 or not (1e11 < ms < 7e13): return None
        try: return (datetime.datetime(1, 1, 1) + datetime.timedelta(milliseconds=ms) - datetime.timedelta(days=2)).date().isoformat()
        except Exception: return None
    if t in ("nxtNullString",):           return ansi_str(raw)
    if t in ("nxtWideString",):           return wide_str(raw)
    if t.startswith("nxtBlob"):
        # referencia de blob (8 bytes): id(u32, local ao bloco) + bloco(u32)
        blobid, block = struct.unpack_from("<II", raw, 0)
        if blobid == 0:
            return None
        return resolve_blob(heap, blobid, block, t)
    return raw.hex()

def valid_guid(s):
    """GUID plausivel: versao (byte 7, nibble alto) 1..5 e variante RFC (byte 8 = 10xx)."""
    if s == b"\x00" * 16:
        return False
    return (s[7] >> 4) in (1, 2, 3, 4, 5) and (s[8] & 0xC0) == 0x80

def record_score(rec, fields, uid_off):
    """Pontua o quao plausivel e que 'rec' comece um registro real (validador generico)."""
    if uid_off is not None and not valid_guid(rec[uid_off:uid_off + 16]):
        return -1
    s = 1
    for f in fields:
        t, o, sz = f["type"], f["offset"], f["size"]
        if o + sz > len(rec):
            continue
        raw = rec[o:o + sz]
        if t == "nxtCurrency":
            v = struct.unpack_from("<q", raw, 0)[0] / 10000.0
            if abs(v) > 1e9:
                return -1
            s += 1
        elif t == "nxtDateTime":
            ms = struct.unpack_from("<d", raw, 0)[0]
            if ms != 0 and not (1e11 < ms < 7e13):
                return -1
            s += 1
        elif t == "nxtBoolean":
            if raw[0] not in (0, 1, 255):
                return -1
            s += 1
        elif t == "nxtGuid":
            g = raw
            if g != b"\x00" * 16 and not valid_guid(g):
                return -1
            s += 1
    return s

def detect_layout(data, fields, reclen, uid_off):
    """Detecta (base, slot) usando o validador generico de registros."""
    from collections import Counter
    slot_votes, base_votes = Counter(), Counter()
    seen = 0
    for i in range(len(data) // BS):
        o = i * BS
        if data[o:o + 4] != b"NXDH":
            continue
        b = data[o:o + BS]
        starts = [p for p in range(0, BS - reclen)
                  if record_score(b[p:p + reclen], fields, uid_off) >= 3]
        for k in range(len(starts) - 1):
            slot_votes[starts[k + 1] - starts[k]] += 1
        for p in starts:
            base_votes[p] += 1
        if starts:
            seen += 1
        if seen >= 300:
            break
    if not slot_votes:
        # 1 registro por bloco: nao ha gaps p/ inferir o slot. Usa a posicao
        # inicial mais comum como base e o proprio reclen como passo.
        if not base_votes:
            return 0, max(reclen, 1)
        base = base_votes.most_common(1)[0][0]
        return base, max(reclen, 1)
    slot = slot_votes.most_common(1)[0][0]
    base = Counter(p % slot for p in base_votes).most_common(1)[0][0]
    return base, slot

def read_table(path, want_heap=True):
    data = open(path, "rb").read()
    fields = parse_fields(data)
    reclen = max(f["offset"] + f["size"] for f in fields)
    uid_off = next((f["offset"] for f in fields if f["name"].upper() == "UID"), None)
    heap = read_heap(data) if want_heap else {}
    base, slot = detect_layout(data, fields, reclen, uid_off)
    recs = []
    for i in range(len(data) // BS):
        o = i * BS
        if data[o:o + 4] != b"NXDH":
            continue
        b = data[o:o + BS]
        p = base
        while p + reclen <= BS:
            rec = b[p:p + reclen]
            if record_score(rec, fields, uid_off) >= 3:
                recs.append({f["name"]: decode_field(rec, f, heap) for f in fields})
            p += slot
    return fields, reclen, recs, (base, slot)

# tamanho de payload que indica chunk "cheio" -> blob continua no proximo bloco.
# bloco de 4096: header(20) + len(2) + dados(<=4060) + pad. Chunks cheios tem 4060.
CHUNK_FULL = 4060

def parse_heap_block(blk):
    """Decodifica um bloco NXHD em lista de entradas na ordem (id = indice+1).

    Cada entrada e (flag, length, payload) onde payload sao os bytes apos o
    byte de flag (length-1 bytes). off16 do bloco guarda o numero de entradas.
    """
    n = struct.unpack_from("<I", blk, 16)[0]
    entries = []
    p = 20
    for _ in range(n):
        if p + 3 > BS:
            break
        length = struct.unpack_from("<H", blk, p)[0]
        if length == 0 or p + 2 + length > BS:
            break
        flag = blk[p + 2]
        payload = blk[p + 3:p + 2 + length]   # length-1 bytes (sem o flag)
        entries.append((flag, length, payload))
        # avanca: alinha a offset par, depois pula terminadores/padding NUL (pares 00 00)
        p += 2 + length
        if p & 1:
            p += 1
        while p + 2 <= BS and blk[p] == 0 and blk[p + 1] == 0:
            p += 2
    return entries

def read_heap(data):
    """Le o heap de blobs: mapa bloco -> lista de entradas (id local = indice+1)."""
    heap = {}
    for i in range(len(data) // BS):
        o = i * BS
        if data[o:o + 4] == b"NXHD":
            heap[i] = parse_heap_block(data[o:o + BS])
    return heap

def resolve_blob(heap, blobid, block, ftype):
    """Resolve (id, bloco) para o valor do blob, encadeando blocos para blobs grandes."""
    entries = heap.get(block) if heap else None
    if not entries or blobid - 1 >= len(entries) or blobid < 1:
        return f"<blob#{blobid}@{block}?>"
    flag, length, payload = entries[blobid - 1]
    chunks = [payload]
    # blob grande: chunk que preenche o bloco (len ~= 4060) continua no proximo
    # bloco NXHD (que e dedicado, com uma unica entrada).
    nb = block
    while length >= CHUNK_FULL and (nb + 1) in heap and len(heap[nb + 1]) == 1:
        nb += 1
        f2, l2, p2 = heap[nb][0]
        chunks.append(p2)
        length = l2
    blob = b"".join(chunks)
    if ftype == "nxtBlobWideMemo":
        # quando o len da entrada e par, ha 1 byte de padding apos a flag p/
        # alinhar o UTF-16; isso deixa o payload com tamanho impar -> descarta-lo.
        if len(blob) & 1:
            blob = blob[1:]
        return blob.decode("utf-16-le", "replace").rstrip("\x00")
    if ftype == "nxtBlobMemo":
        return blob.decode("latin1", "replace").rstrip("\x00")
    # graficos / binarios: base64 (best-effort; pode incluir 1 byte de flag por chunk)
    return {"__blob_b64__": base64.b64encode(blob).decode("ascii"), "bytes": len(blob)}

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else r"C:/Nex/Dados/Tran.nx1"
    fields, reclen, recs, (base, slot) = read_table(path)
    print(f"{os.path.basename(path)}: campos={len(fields)} reclen={reclen} "
          f"base={base} slot={slot} registros={len(recs)}")
    out = os.path.join(os.path.dirname(__file__), os.path.basename(path).replace(".nx1", ".json"))
    json.dump(recs, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)
    print("JSON:", out)
    if recs:
        print(json.dumps(recs[0], ensure_ascii=False, indent=2, default=str)[:1500])
