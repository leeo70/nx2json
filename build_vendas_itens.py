"""Reconstroi as linhas de venda (item -> produto) a partir das tabelas .nx1.

Cadeia: Tran (venda) <-Tran- MovEst (linha) -Produto-> Produto (mestre).
MovEst e a tabela de linhas: tem Produto (id), Descr (nome snapshot), Quant,
Unitario, Total, uid_itran. O produto resolve por MovEst.Produto -> Produto.ID
(99,8%); quando nao casa, usa-se o nome em MovEst.Descr.

Uso: python build_vendas_itens.py <dir_nx1> [dir_saida]
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nxread


def ne(v):
    return v not in (None, "", 0, 0.0, False, "{00000000-0000-0000-0000-000000000000}")


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else print("falta diretorio de origem")
    out = sys.argv[2] if len(sys.argv) > 2 else print("falta diretorio de saida")
    os.makedirs(out, exist_ok=True)

    _, _, prod, _ = nxread.read_table(os.path.join(src, "Produto.nx1"))
    prod_by_id = {int(p["ID"]): p for p in prod if p.get("ID") is not None}

    _, _, mov, _ = nxread.read_table(os.path.join(src, "MovEst.nx1"))

    itens = []
    linked = via_descr = 0
    for m in mov:
        pid = int(m["Produto"]) if ne(m.get("Produto")) else None
        p = prod_by_id.get(pid)
        if p:
            linked += 1
            nome = p["Descricao"]
            codigo = p.get("Codigo")
            uid_prod = p.get("UID")
            categoria = p.get("Categoria")
        else:
            via_descr += 1
            nome = m.get("Descr")
            codigo = None
            uid_prod = m.get("uid_produto") if ne(m.get("uid_produto")) else None
            categoria = m.get("Categoria")
        itens.append({
            "venda_id": m.get("Tran"),
            "item": m.get("Item"),
            "uid_itran": m.get("uid_itran"),
            "produto_id": pid,
            "produto_uid": uid_prod,
            "produto_nome": nome,
            "produto_codigo": codigo,
            "categoria": categoria,
            "quantidade": m.get("Quant"),
            "unitario": m.get("Unitario"),
            "desconto": m.get("Desconto"),
            "total": m.get("Total"),
            "total_liq": m.get("TotLiq"),
            "custo_unit": m.get("CustoU"),
            # observacao digitada no item da venda (servico/pendencia). Ignora
            # marcadores de blob nao resolvido.
            "obs": (m.get("Obs") if isinstance(m.get("Obs"), str)
                    and not m.get("Obs", "").startswith("<blob#") else None),
            "pendente": bool(m.get("Pend")),
            "tipo_tran": m.get("TipoTran"),
            "cancelado": bool(m.get("Cancelado")),
            "data_hora": m.get("DataHora"),
            "produto_resolvido": p is not None,
        })

    dst = os.path.join(out, "vendas_itens.json")
    json.dump(itens, open(dst, "w", encoding="utf-8"), ensure_ascii=False, default=str)
    n = len(itens)
    print(f"linhas={n}  produto_via_cadastro={linked} ({100*linked/n:.1f}%)  "
          f"via_descr_snapshot={via_descr} ({100*via_descr/n:.1f}%)")
    print(f"saida: {dst}")
    for it in itens[:5]:
        print(f"  venda {it['venda_id']} | {it['quantidade']}x {it['produto_nome']!r} "
              f"(cod {it['produto_codigo']}) = {it['total']}")


if __name__ == "__main__":
    main()
