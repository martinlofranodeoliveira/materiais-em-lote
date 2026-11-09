# Interoperabilidade verificada

Em 09/11/2026, os relatórios XLSX realmente produzidos pela CLI foram importados por **LibreOffice 26.2.6.3 620(Build:3)**, no Linux. A importação inicial para ODS preservou as mesmas quatro abas, endereços, valores e tipos de **171 células da demonstração** e **243 células do caso de texto**. Um leitor ODF independente, sem escapes ST_Xstring, comparou todas essas células ao XLSX original e ao JSON de origem. Quantidades permaneceram texto exato; somente nível e número de lotes eram inteiros. Não houve teste com Microsoft Excel.

O arquivo da demonstração também foi salvo novamente em XLSX sem alterar suas 171 células. No caso de texto ampliado, o reexportador do LibreOffice perdeu dois padrões literais; a reabertura desse XLSX confirmou as perdas. Por isso, o registro tem status **`completed-with-consumer-limitation`**, `textRoundtripExact: false` e `equal: false` para essa reexportação. Não há alegação de preservação geral após salvar em um aplicativo de terceiros.

A prova versionada está em [evidence.json](../fixtures/interop/evidence.json). O registro contém a versão observada, argumentos exatos de cada processo, códigos de saída, stdout/stderr, SHA256 e tamanho dos onze artefatos. Os únicos caminhos dos comandos são o executável do sistema e um diretório temporário aleatório; nenhum perfil, nome de usuário ou caminho do projeto foi incorporado. Os nomes e diretórios temporários reais foram mantidos para permitir auditoria dos comandos.

| Artefato original | SHA256 |
| --- | --- |
| `demo.zip` | `18535ed0b4d7ecccb0541aae9a51874dd2fec387dc4ae2e4c68b52a586107c8c` |
| `text.zip` | `c35cc973b08f8d677d44e11572a8b3417fa78fb505df727ab17b4d8d9548081d` |
| `text-original.xlsx` | `80db53bb57c08a9f81ca8f5bc36098dfb3fc47ff1a7bf2b72d2ee309fc69bb80` |

## Verificação independente do bundle

[check_bundle.py](../tools/check_bundle.py) usa apenas a biblioteca padrão: ZIP, XML, JSON, CSV, SHA256 e `fractions.Fraction`. Não importa `materiais_em_lote`, seu núcleo ou seu exportador. Não extrai membros no sistema de arquivos.

O verificador confere o inventário fechado de sete arquivos, nomes seguros, ausência de duplicatas, limites de tamanho, metadados fixos, hashes e tamanhos do manifesto. Rejeita JSON ambíguo, quantidades não textuais, referências inválidas, ciclos e limites racionais excedidos. Reconstrói a topologia, cada origem direta ou dependente, o desconto único de estoque, os lotes e os saldos usando frações exatas. Compara todos os registros do JSON, a tabela CSV e os tipos/valores das células OOXML. O modo `--demo` acrescenta respostas e dez rastros manuais literais.

| Item | Bruta | Estoque usado | Líquida | Lotes | Planejada | Saldo |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| expositor | 2 | 0 | 2 | 2 | 2 | 0 |
| kit | 3 | 1 | 2 | 1 | 2 | 0 |
| painel | 7 | 2 | 5 | 2 | 6 | 1 |
| suporte | 8 | 1 | 7 | 2 | 8 | 1 |
| chapa | 2 | 1 | 1 | 1 | 2 | 1 |
| tinta | 1.5 | 0.3 | 1.2 | 2 | 2 | 0.8 |

A tinta reúne `0.5` do kit, `0.4` dos expositores e `0.6` dos painéis antes de usar seu estoque `0.3`. Unidades diferentes não são reunidas em um total geral.

O leitor OOXML recusa fórmulas no relatório estático, hyperlinks, relações externas, macros, conexões, objetos incorporados e partes ativas conhecidas. Também verifica cabeçalho congelado, filtro/tabela e impressão ajustada em largura no arquivo original. Isso verifica o formato contratado; não é um sanitizador geral de todo arquivo Office possível.

## Texto autoral

[text-project.json](../fixtures/interop/text-project.json) inclui nomes começando por `=`, `+`, `-` e `@`, além de acentos, aspas, apóstrofo e `<&>`. O título começa por `=`. Os nomes permaneceram texto literal na importação e na reexportação desses líderes de fórmula: `=1+1` não se tornou uma fórmula nem o número 2. No CSV, o verificador exige o apóstrofo documentado antes desses líderes. O projeto também inclui quantidade `0.1` e rendimento de lote `3`.

A regressão inclui o ID `item_x0041_` e os nomes literais `_x0041_`, `_x000D_`, `_x005F_x0041_`, `_x0041__x000D_`, `_x0041_x000D_` e `_xD83D__xDE00_`. O produtor protege os underscores que poderiam iniciar escapes OOXML. O leitor independente decodifica ST_Xstring uma vez por trecho `t`, combina pares UTF16 válidos e preserva underscores protegidos. Ele não interpreta novamente o texto resultante nem decodifica através de limites entre trechos. O título nas propriedades XML não usa ST_Xstring. A necessidade de proteger o underscore em padrões `_xHHHH_` está documentada pela [Microsoft para ST_Xstring](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/d34ae755-c53f-4a44-a363-c6dd3ee018a4).

O XLSX original entrega todos os literais corretos: [text-import.ods](../fixtures/interop/text-import.ods) registra a importação inicial bem-sucedida das 243 células. O problema aparece quando LibreOffice 26.2.6.3 salva novamente os padrões protegido e sobreposto em XLSX:

| Célula | Texto original esperado | Texto do XLSX reexportado e reaberto |
| --- | --- | --- |
| `Plano!B5` | `_x005F_x0041_` | `_x0041_` |
| `Plano!B6` | `_x0041_x000D_` | `_x0041` seguido de retorno de carro U+000D |

O reader OOXML detecta essas diferenças em [text-libreoffice.xlsx](../fixtures/interop/text-libreoffice.xlsx). A segunda leitura real do aplicativo, salva em [text-reopened.ods](../fixtures/interop/text-reopened.ods), confirma precisamente as mesmas diferenças, sem depender do decoder OOXML do verificador. As demais 241 células permanecem iguais. Os esperados semânticos continuam sendo o texto literal da entrada; os dois resultados alterados são registrados como perdas do consumidor, sem substituírem os esperados.

Para preservar o texto autoral e as quantidades, mantenha o ZIP original e seus arquivos `projeto.json`/`plano.json`. O pacote entrega um relatório estático correto; não corrige o comportamento de salvamento de terceiros. Nenhum input válido foi proibido para evitar esse contraexemplo.

## Auditoria de fórmulas separada

[audit-source.xlsx](../fixtures/interop/audit-source.xlsx) é um segundo workbook, escrito para esta prova. Ele não é o relatório estático da CLI. Suas fórmulas foram autoradas em [verify_libreoffice.py](../tools/verify_libreoffice.py), com entradas e respostas esperadas literais, sem chamar o planejador. O LibreOffice salvou os resultados em [audit-libreoffice.xlsx](../fixtures/interop/audit-libreoffice.xlsx); o leitor stdlib verificou os **72 caches numéricos de fórmulas** em três cenários:

1. A demonstração de seis itens, incluindo componente compartilhado e estoque multinível.
2. Estoque de submontagem: quatro unidades da raiz geram demanda de oito submontagens; o estoque de três reduz a necessidade a cinco. Com lote de duas, fabricam-se três lotes, consumindo nove componentes. Com estoque de dois e embalagem de quatro, compram-se duas embalagens e sobra uma unidade.
3. Componente compartilhado em profundidades diferentes: a raiz pede o mesmo componente diretamente e através de um ramo. O estoque de um ramo reduz sua produção a um lote; as duas origens do componente somam quatro. Seu estoque de um e embalagem de três resultam em uma embalagem, sem saldo.

A conferência estática do relatório exige igualdade exata de texto e inteiros. A auditoria usa o mecanismo numérico do LibreOffice, com tolerância absoluta de `1e-12` nos caches; isso não demonstra aritmética racional exata geral em planilhas nem uma planilha dinâmica de planejamento. Os esperados literais também são conferidos para detectar sua alteração.

## Isolamento da execução real

Cada prova externa cria HOME, diretórios XDG e um perfil LibreOffice temporários exclusivos. Nenhum perfil existente é usado. A configuração temporária desabilita macros e atualização de links; o leitor rejeita previamente relações externas. Cada conversão para XLSX ou ODS recebe um diretório de saída novo. Não há impressão ou acesso solicitado a serviços.

Os processos LibreOffice foram executados com `unshare --user --map-root-user --net --`, em um namespace de rede Linux novo sem conexão externa. A criação desse namespace é obrigatória: o script falha se estiver indisponível e não executa um fallback com rede. Isso exige Linux com namespaces de usuário/rede habilitados e `unshare`. O LibreOffice continua sendo consumidor externo de QA; o pacote e a CLI não dependem dele nem o iniciam.

## Reproduzir

Com o pacote instalado e os arquivos deste repositório:

```sh
materiais-em-lote exemplo --saida demo-novo.zip
materiais-em-lote planejar fixtures/interop/text-project.json --saida texto-novo.zip
python3 tools/check_bundle.py demo-novo.zip --demo
python3 tools/check_bundle.py texto-novo.zip
python3 tools/verify_libreoffice.py --bundle demo-novo.zip --text-bundle texto-novo.zip --output-dir evidencia-nova --record-known-export-limitation
```

O último comando efetivamente inicia LibreOffice e permite registrar somente o contraexemplo conhecido. Sem `--record-known-export-limitation`, o modo estrito falha diante de qualquer divergência, inclusive essas duas. Com a flag, a importação inicial e a demonstração ainda precisam ser integralmente iguais; a reexportação de texto precisa ser igual ou apresentar exatamente as duas perdas descritas. Uma terceira diferença, mudança de tipo, perda de outra célula ou divergência na auditoria continua sendo erro. A flag não muda os textos esperados nem registra `equal: true` quando há perda. A CI usa esse modo explícito para auditar também a limitação externa. Precisa de `openpyxl==3.1.5` para escrever o workbook de auditoria separado, de `/usr/bin/libreoffice` e de `/usr/bin/unshare`; os dois executáveis podem ser indicados por `--libreoffice` e `--unshare`. A pasta de evidência precisa ser nova. Os XLSX salvos pelo LibreOffice não são prometidos como reproduzíveis byte a byte; seus hashes registram esta execução concreta.

Para conferir os artefatos armazenados sem iniciar LibreOffice:

```sh
python3 tools/verify_libreoffice.py --check-fixtures
python3 -m unittest discover -s tests -p test_interop.py -v
```

Esse modo verifica os hashes, lê novamente os bundles, XLSX e ODS, repete as comparações e confirma as duas perdas armazenadas. Sua saída mantém `status: completed-with-consumer-limitation` e `textRoundtripExact: false`. Sua saída declara `mode: stored-evidence-only` e `newExternalExecution: false`. Ele não afirma que ocorreu uma nova execução externa. A CI mantém uma etapa distinta para uma nova prova com LibreOffice.
