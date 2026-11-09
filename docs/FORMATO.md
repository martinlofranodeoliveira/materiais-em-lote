# Formato do cenário e dos resultados

## Entrada JSON 1

O objeto raiz contém exatamente `version`, `title`, `items`, `demands` e `stock`. `version` é o inteiro 1. Consulte a [entrada original completa](../fixtures/projeto-oficina.json). Não são aceitos BOM, chaves JSON repetidas, NaN, Infinity ou campos desconhecidos.

IDs de itens e demandas têm de 1 a 40 caracteres, começam com letra minúscula ASCII e continuam com letras minúsculas, dígitos, `_` ou `-`. Uma unidade segue a mesma gramática, com no máximo 16 caracteres. Título e nomes conservam Unicode, sem controles ou espaços externos; seus máximos são 120 e 100 pontos Unicode.

Quantidades são **strings** decimais ASCII: `"0"`, `"2"` e `"0.3"`, por exemplo. Não use números JSON, sinal, expoente, vírgula decimal ou zero inicial dispensável. São admitidas até seis casas decimais e valor máximo de `10^12`. Demanda, lote, embalagem e consumo por lote são positivos. Estoque pode ser zero.

### Comprado

```json
{"id":"suporte","name":"Suporte","unit":"un","kind":"buy","pack":"4"}
```

`pack` é a quantidade por embalagem, na unidade do próprio item. Não existe lista de componentes em um comprado.

### Fabricado

```json
{"id":"kit","name":"Kit de oficina","unit":"un","kind":"make","batch":"2","components":[{"item":"suporte","quantity":"4"}]}
```

`batch` é o rendimento de um lote. Cada `components.quantity` declara o consumo de **um lote inteiro do pai**, na unidade do filho. O exemplo produz dois kits e consome quatro suportes por lote, não quatro suportes por kit. As referências precisam existir no catálogo completo. Não repita o mesmo componente no mesmo pai; não são permitidos ciclos.

### Pedidos e estoque

```json
{"id":"pedido-kit","item":"kit","quantity":"3"}
```

Cada demanda tem ID único. Várias demandas do mesmo item são reunidas. Um registro de estoque tem somente `item` e `quantity`, por exemplo `{"item":"kit","quantity":"1"}`. No máximo um por item; ausência significa estoque zero. As unidades são as do catálogo; não há inferência ou conversão.

## Cálculo

Processar todos os pais antes de um filho, com desempate lexicográfico de ID. O nível é o maior caminho desde uma raiz do catálogo. Para cada item:

```text
bruta = soma de todas as demandas diretas e dependentes
usado = mínimo(bruta, estoque)
líquida = máximo(bruta - estoque, 0)
lotes = teto(líquida / lote_ou_embalagem)
planejado = lotes * lote_ou_embalagem
saldo = estoque + planejado - bruta
```

Se fabricado, cada componente recebe `lotes * consumo_por_lote`. O estoque de um submontado é usado antes de produzir mais dele; sua parte já pronta não consome componentes. Um material comprado encerra a propagação. O arredondamento ocorre por item, depois de reunir todas as suas origens. Não é atribuído ficticiamente a um pedido específico.

Não há caminho válido em um ciclo; o catálogo inteiro é recusado, inclusive se o ciclo não for usado pelos pedidos atuais. Itens sem demanda aparecem com produção/compra zero e estoque preservado. Toda quantidade calculada permanece até `10^12`, com numerador e denominador reduzidos de até 80 dígitos; ultrapassar um limite recusa o plano completo.

## JSON do plano

Campos raiz: `version`, `title`, `items`, `origins`, `demands`, `edges`. As linhas de itens contêm, nessa ordem:

`item`, `name`, `unit`, `kind`, `level`, `lot`, `gross`, `stock`, `used`, `net`, `lots`, `planned`, `leftover`.

`kind` é `buy` ou `make`; `level` e `lots` são inteiros. Quantidades são texto exato: decimal sem zeros finais dispensáveis quando finito, ou fração irredutível `n/d`. O formato pode representar frações gerais; as entradas decimais e os lotes inteiros desta versão mantêm os valores do plano em decimais finitos. Não converta a float se precisar de igualdade exata.

Uma origem contém `item`, `kind`, `source`, `quantity`: `direct` aponta ao ID da demanda; `parent` aponta ao ID do pai fabricado. Só há origens positivas. Cada aresta em `edges` contém `parent`, `child`, `per_batch`. As demandas originais ficam em `demands` com `id`, `item`, `quantity`.

Os itens seguem a ordem topológica; as origens seguem a ordem dos itens, com diretas antes das dependentes e IDs de origem em ordem lexical. Demandas são ordenadas por ID e arestas por pai/filho. Reordenar os arrays de entrada não altera o plano; os bytes originais da entrada e seu hash continuam diferentes se você reformatar o arquivo.

## CSV, Markdown e XLSX

O CSV UTF-8 usa vírgula, aspas conforme necessidade e LF. Seus cabeçalhos são os nomes estáveis das linhas JSON. Para textos cujo primeiro caractere não branco seja `=`, `+`, `-` ou `@`, é acrescentado um apóstrofo. Esse é um campo de apresentação protegido; o JSON conserva o texto original. CSV não é arquivo de restauração do cenário.

O Markdown escapa os caracteres de HTML e de formatação para mostrar título e nomes literalmente. A memória de cálculo apresenta todas as origens positivas. Não há soma geral de itens diferentes.

O XLSX tem quatro abas: **Plano**, **Origens**, **Pedidos**, **Estrutura**, com cabeçalhos em português na linha 1. Os dados começam na linha 2. `level` e `lots` são células numéricas inteiras; IDs, nomes, unidades, tipos e quantidades são células de texto explícito. O título fica nos metadados do documento. Texto com líder de fórmula continua literal. Não são geradas fórmulas, hyperlinks, macros ou conexões externas. Filtros e cabeçalhos congelados ajudam a consulta, mas o arquivo é estático: ele não recalcula quando editado.

Textos literais que parecem escapes OOXML, como `_x0041_`, têm seu underscore inicial protegido no arquivo. Consumidores interpretam esses escapes uma única vez para recuperar o texto original. Esse tratamento segue a [regra ST_Xstring documentada pela Microsoft](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/d34ae755-c53f-4a44-a363-c6dd3ee018a4). Ler o XML bruto sem interpretar essa camada pode mostrar a proteção no lugar do texto final; para processamento direto dos dados, prefira `plano.json`.

## Pacote e publicação

O ZIP contém exatamente sete nomes fixos: `projeto.json`, `plano.json`, `plano.csv`, `plano.md`, `plano.xlsx`, `LEIA-ME.md`, `manifesto.json`. O manifesto registra `version:1`, `packageVersion`, `inputSHA256` e `files`, uma lista lexical de objetos `{name,size,sha256}` para os seis outros arquivos.

Todos os relatórios são construídos antes da escrita da saída. Um arquivo temporário regular no mesmo diretório recebe os bytes completos e é publicado por hardlink exclusivo. Um destino existente não é substituído; o temporário é removido. Falta de suporte a hardlink é erro explícito. A implementação não promete sobrevivência a falha elétrica nem proteção contra um adversário que controle o sistema de arquivos.

Timestamps e metadados gerados são fixos, inclusive dentro do XLSX. A repetição no mesmo ambiente e versões produz os mesmos bytes. Não é promessa de compressão idêntica entre versões diferentes de Python, zlib ou openpyxl.

## Códigos de saída

`0`: pacote completo criado. `2`: entrada ou uso inválido. `3`: I/O ou publicação recusada, incluindo destino existente. A CLI não imprime valores do arquivo, caminho absoluto interno ou traceback em erros esperados. A mensagem de sucesso mostra o caminho de saída fornecido pelo chamador.
