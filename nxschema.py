"""Extrai o schema (layout físico de registro) de uma tabela NexusDB .nx1."""
import struct, re, json, sys

class Reader:
    def __init__(self, buf, pos=0):
        self.b = buf; self.p = pos
    def value(self):
        t = self.b[self.p]; self.p += 1
        if t == 0:   return ("null", None)
        if t == 1:
            items = []
            while self.b[self.p] != 0:
                items.append(self.value())
            self.p += 1
            return ("list", items)
        if t == 2:   v = self.b[self.p]; self.p += 1; return ("int", v)
        if t == 3:   v = struct.unpack_from("<h", self.b, self.p)[0]; self.p += 2; return ("int", v)
        if t == 4:   v = struct.unpack_from("<i", self.b, self.p)[0]; self.p += 4; return ("int", v)
        if t == 8:   return ("bool", False)
        if t == 9:   return ("bool", True)
        if t == 6:   n = self.b[self.p]; self.p += 1; s = self.b[self.p:self.p+n].decode("latin1"); self.p += n; return ("s", s)
        if t == 7:   n = self.b[self.p]; self.p += 1; s = self.b[self.p:self.p+n].decode("latin1"); self.p += n; return ("ident", s)
        if t == 10:  n = struct.unpack_from("<i", self.b, self.p)[0]; self.p += 4; raw = self.b[self.p:self.p+n]; self.p += n; return ("bin", raw)
        if t == 12:  n = struct.unpack_from("<i", self.b, self.p)[0]; self.p += 4; s = self.b[self.p:self.p+n].decode("latin1"); self.p += n; return ("s", s)
        if t == 18:  n = struct.unpack_from("<i", self.b, self.p)[0]; self.p += 4; s = self.b[self.p:self.p+n*2].decode("utf-16-le","replace"); self.p += n*2; return ("ws", s)
        if t == 19:  v = struct.unpack_from("<q", self.b, self.p)[0]; self.p += 8; return ("int", v)
        if t == 16:  v = struct.unpack_from("<q", self.b, self.p)[0]; self.p += 8; return ("int", v)
        raise ValueError(f"tag {t} @ {self.p-1}")

def parse_fields(data):
    MARKER = b"TnxFieldDescriptor"
    positions = [m.start() for m in re.finditer(re.escape(MARKER), data)]
    idx_stop = data.find(b"IndicesDescriptor")
    positions = [p for p in positions if p < idx_stop]
    fields = []
    for k, start in enumerate(positions):
        end = positions[k+1] if k+1 < len(positions) else idx_stop
        r = Reader(data, start + len(MARKER))
        vals = []
        while r.p < end:
            try:
                vals.append(r.value())
            except Exception:
                break
        name  = vals[0][1] if vals and vals[0][0] == "s" else None
        ftype = next((v for (kd, v) in vals if kd == "s" and v.startswith("nxt")), None)
        # offset/size: tras o 2o WideString vazio vem [3, offset, size]
        ws_idx = [i for i, (kd, _) in enumerate(vals) if kd == "ws"]
        offset = size = fid = None
        if len(ws_idx) >= 2:
            j = ws_idx[1]
            ints_after = [v for (kd, v) in vals[j+1:] if kd == "int"]
            if len(ints_after) >= 3:
                # ints_after = [3, offset, size, ...]
                offset, size = ints_after[1], ints_after[2]
            # field ordinal = int imediatamente antes do 2o ws
            before = [v for (kd, v) in vals[:j] if kd == "int"]
            fid = before[-1] if before else None
        if name and ftype and offset is not None:
            fields.append({"fid": fid, "name": name, "type": ftype,
                           "offset": offset, "size": size})
    return fields

if __name__ == "__main__":
    try:
        path = sys.argv[1] if len(sys.argv) > 1 else None
        if not path:
            raise ValueError("Ta faltando argumentos")
    except (IndexError, ValueError) as e:
        print(e)
        sys.exit(1)
    data = open(path, "rb").read()
    fields = parse_fields(data)
    reclen = max(f["offset"] + f["size"] for f in fields)
    for f in fields:
        print(f"{f['offset']:>4} +{f['size']:<3} {f['type']:<18} {f['name']}")
    print("N campos:", len(fields))
    print("Tamanho calculado do registro (sem header/nullmap):", reclen)
    json.dump(fields, open(r"C:/Nex/nx2json/tran_schema.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
