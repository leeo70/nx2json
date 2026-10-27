# nx2json — NexusDB (.nx1) → JSON

Manual de campo. Procedimento para, no cliente, copiar os `.nx1`, gerar os JSONs e
levar tudo para a migração.

---

## 0. Pré-requisitos

- **Python 3.10+** (testado no 3.13). Verifique: `python --version`.
- **Sem dependências externas** — só a biblioteca padrão. Não precisa de `pip install`.
- Os scripts podem ficar em `C:\Nex\nx2json\`.

---

## 1. No cliente: backup dos `.nx1`

Os dados ficam na pasta de dados do sistema NexAdmin (no caso conhecido: `C:\Nex\Dados`,
mas confirme no cliente). São vários arquivos `.nx1` (+ `.cfg`).

**IMPORTANTE: feche o sistema/serviço do cliente antes de copiar** (arquivo aberto pode
copiar pela metade). Copie **todos** os `.nx1` da pasta.

### Onde e como guardar

Padronize uma pasta por cliente e por data (assim nunca se confunde backup):

```
C:\Nex\backups\<CLIENTE>\<AAAAMMDD>\
    ├── *.nx1            <- cópia crua, NÃO MEXER (é o backup original)
    └── _json_dump\      <- gerado pelos scripts (passo 2)
```

Exemplo: `C:\Nex\backups\acme\20260620\`

Regras:
- Mantenha o `.nx1` **original intocado** (é a fonte da verdade; se algo der errado no
  dump, você reprocessa a partir dele).
- Nunca rode o dump sobrescrevendo a pasta original — o dump só escreve em `_json_dump`.
- Guarde também uma cópia do backup em outro lugar (HD externo / nuvem) antes de sair do
  cliente.

---

## 2. Gerar os JSONs (um comando só)

**Runner único**, apontando para a pasta com os `.nx1`:

```powershell
$env:PYTHONIOENCODING="utf-8"
python C:\Nex\nx2json\rodar_dump.py "C:\Nex\backups\<CLIENTE>\<AAAAMMDD>"
```

> O `PYTHONIOENCODING=utf-8` é necessário no Windows para os acentos aparecerem
> certo no console. Não afeta os arquivos JSON (esses já saem em UTF-8 sempre).

Isso executa, em ordem, e grava tudo em `...\<AAAAMMDD>\_json_dump\`:

1. **Dump de todas as tabelas** → um `.json` por tabela + `_summary.json`.
2. **`vendas_itens.json`** → linhas de venda já com produto resolvido (item→produto).
3. **`catalogo_produtos.json`** → catálogo de produtos (fonte secundária).
4. **`dados.sqlite`** → consolidação dos JSONs em um banco SQLite único,
   com schema tipado para as tabelas-chave (Produto, Cliente, Tran, MovEst,
   Caixa, Categoria, vendas_itens, catalogo_produtos) e schema dinâmico
   (colunas TEXT + `_raw` com JSON original) para as demais.

Tempo: ~1 minuto para uma base típica. Tabelas vazias geram `[]` (normal).

Para pular o passo 4 (gerar só JSON):

```powershell
python C:\Nex\nx2json\rodar_dump.py "C:\Nex\backups\<CLIENTE>\<AAAAMMDD>" --no-sqlite
```

---

## 3. Conferir o resultado (validação rápida)

Modo JSON (default):

```powershell
$env:PYTHONIOENCODING="utf-8"
python C:\Nex\nx2json\validar_dump.py "C:\Nex\backups\<CLIENTE>\<AAAAMMDD>\_json_dump"
```

Modo SQLite (equivalente, rodando os mesmos checks via SQL — mais rápido em
bases grandes):

```powershell
python C:\Nex\nx2json\validar_dump.py "C:\Nex\backups\<CLIENTE>\<AAAAMMDD>\_json_dump" --sqlite
```

Também aceita o caminho direto do `.sqlite`:

```powershell
python C:\Nex\nx2json\validar_dump.py "C:\...\_json_dump\dados.sqlite" --sqlite
```

Confere as contagens das tabelas-chave e mostra a taxa de item→produto resolvido.
Também aponta tabelas que falharam (ver seção 5).

Confira na mão se os números batem com o esperado do cliente (nº de produtos, clientes,
vendas).

---

## 4. O que cada arquivo entrega (para a migração)

Tabelas/arquivos que importam para a migração:

| Arquivo gerado          | Entidade            | Campos-chave |
|-------------------------|---------------------|--------------|
| `Produto.json`          | Produtos            | `ID`, `Descricao` (nome), `Codigo`, `Preco`, `Categoria`, `uid_categoria`, `NCM`, `EstoqueAtual`, `UID`   |
| `Cliente.json`          | Clientes            | dados cadastrais + `Obs` |
| `Caixa.json`            | Caixa               | - |
| `Tran.json`             | Vendas (cabeçalho)  | `ID`, `Descricao` (resumo textual dos itens), totais |
| `vendas_itens.json`     | **Itens das vendas**| `venda_id`, `produto_id`, `produto_nome`, `produto_codigo`, `categoria`, `quantidade`, `unitario`, `total`, `tipo_tran` |
| `dados.sqlite`          | **Tudo acima**      | banco único com schema tipado e índices; `_meta`, `_extract_summary` |

Ordem de importação recomendada (dependências): **categorias → produtos → clientes →
vendas → itens**.

> Item→produto: vem do `vendas_itens.json` (reconstruído de `MovEst` via
> `MovEst.Produto → Produto.ID`, ~99,8%). Não depende de blobs nem de `stock`.

### 4.1 SQLite: estrutura

O `dados.sqlite` é o mesmo conteúdo dos JSONs, mas pronto para consulta. Tabelas:

- **Tipadas com índices**: `Produto`, `Cliente`, `Tran`, `MovEst`, `Caixa`,
  `Categoria`, `vendas_itens`, `catalogo_produtos`. Campos não listados no
  schema tipado ficam na coluna `_raw` como JSON (nada é perdido).
- **Dinâmicas**: toda `.nx1` sem schema tipado vira uma tabela com todas as
  colunas em `TEXT` + `_raw` (JSON original do registro). Útil para auditoria.
- **Metadados**: `_meta` (versão do schema, data da extração, origem) e
  `_extract_summary` (status por `.nx1`: ok/erro, campos, registros).

Consultas típicas que a migração precisa:

```sql
-- Top 20 produtos mais vendidos
SELECT produto_nome, SUM(quantidade) qtd, SUM(total) rec
FROM vendas_itens
GROUP BY produto_id
ORDER BY qtd DESC
LIMIT 20;

-- Clientes com dado de contato
SELECT ID, Nome, Telefone, Email FROM Cliente
WHERE Telefone IS NOT NULL OR Email IS NOT NULL;

-- Faturamento por mês
SELECT substr(DataHora,1,7) AS mes, SUM(Total) AS total
FROM Tran WHERE Cancelado=0
GROUP BY mes ORDER BY mes;
```

Para regenerar só o SQLite a partir de JSONs existentes (sem reler os `.nx1`):

```powershell
python C:\Nex\nx2json\json_to_sqlite.py "<pasta _json_dump>" "<saida.sqlite>"
```

---

## 5. Limitações conhecidas (esperado, não é erro de execução)

- **6 tabelas falham no schema** (`max() iterable argument is empty`): `MoedasCustom`,
  `ProdutoValidade`, `RegistrosRemovidos`, `TEF_Config`, `TEF_Tran`, `Usuario`.
  Não são necessárias para produtos/clientes/vendas/itens. `Usuario` fica pendente de
  correção do parser de schema.
- **Blobs grandes / imagens** (foto de produto, foto de cliente, documentos grandes):
  ainda não são extraídos (ficam como `<blob#...>` ou base64 parcial). Os blobs de
  **texto** (observações, JSON, XML de NF-e) saem corretos (~99,9%).
- **`RecDel.json`** sai vazio — é log de registros deletados, irrelevante.

---

## 6. Scripts (referência)

Todos aceitam caminhos como argumento. Normalmente você só usa o `rodar_dump.py`.

| Script | O que faz | Uso |
|--------|-----------|-----|
| `rodar_dump.py`        | **Pipeline completo** (recomendado) | `python rodar_dump.py <pasta_nx1> [saida] [--no-sqlite]` |
| `dump_all.py`          | Só o dump de todas as tabelas | `python dump_all.py <pasta_nx1> <saida>` |
| `build_vendas_itens.py`| Só reconstrói `vendas_itens.json` | `python build_vendas_itens.py <pasta_nx1> [saida]` |
| `extract_catalog.py`   | Só extrai o catálogo JSON | `python extract_catalog.py <catalogo_json.nx1> [saida.json]` |
| `json_to_sqlite.py`    | Só consolida JSONs em SQLite | `python json_to_sqlite.py <pasta _json_dump> [saida.sqlite]` |
| `validar_dump.py`      | Validação (JSON ou SQLite) | `python validar_dump.py <pasta> [--sqlite]` |
| `nxread.py`            | Biblioteca + dump de **uma** tabela | `python nxread.py <tabela.nx1>` |
| `nxschema.py`          | Mostra o layout (schema) de uma tabela | `python nxschema.py <tabela.nx1>` |

---

## 7. Checklist de campo (resumo)

1. [ ] Fechar o sistema do cliente.
2. [ ] Copiar todos os `.nx1` para `C:\Nex\backups\<CLIENTE>\<AAAAMMDD>\`.
3. [ ] Copiar o backup para um segundo local (HD/nuvem).
4. [ ] `python C:\Nex\nx2json\rodar_dump.py "<pasta do backup>"`.
5. [ ] `python C:\Nex\nx2json\validar_dump.py "<pasta>\_json_dump"`.
6. [ ] Conferir contagens com o cliente (produtos, clientes, vendas).
7. [ ] Levar a pasta inteira (`.nx1` + `_json_dump`) para a migração.
