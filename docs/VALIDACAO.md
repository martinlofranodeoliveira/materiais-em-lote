# Validação e alcance

Registro de 9 de novembro de 2026. Testes unitários, conferência de arquivos e consumidor externo têm provas separadas.

## Núcleo e publicação

Passaram **59 testes locais** em Python 3.14.4/Linux, sem falhas ou omissões: 18 do núcleo, 15 de relatórios/CLI, 18 de interoperabilidade e oito de distribuição. No Windows, o caso de FIFO POSIX é explicitamente omitido; os demais resultados ficam nos logs da matriz de CI.

O cenário manual de seis itens fixa estoque de submontagem, material compartilhado em profundidades diferentes, arredondamento por lote e embalagem e dez origens positivas. Um oráculo independente de pequenos DAGs enumera vetores de lotes, sem usar a rotina topológica do aplicativo. Os testes incluem catálogo inteiro, referências, ciclos, limites, quantidades decimais, imutabilidade e dataclasses forjadas.

Os testes de relatórios verificam o pacote completo, hashes, fonte original, números do cenário, ausência de fórmulas no XLSX, texto literal com líderes de fórmula, escape Markdown e proteção CSV. A publicação é exercitada com destino novo, arquivo/diretório/link já existente e falhas simuladas de hardlink e fsync. A CLI é invocada em subprocessos, incluindo erros sanitizados e entrada FIFO sem espera por escritor no POSIX.

```sh
python -m unittest discover -s tests -v
python tools/check_bundle.py exemplo.zip --demo
```

O leitor de ZIP/XML/JSON/CSV usa somente a biblioteca padrão, sem importar o núcleo ou relatórios. Ele reconstrói os dados e a memória de cálculo e compara o cenário a valores conhecidos. Hashes associam os resultados aos bytes conferidos.

## Consumidor externo

O [ensaio LibreOffice](INTEROPERABILIDADE.md) registra separadamente abertura e nova gravação dos relatórios estáticos e recálculo de uma planilha de auditoria independente. A auditoria contém cenários autorais e resultados literais, não fórmulas inseridas no relatório do aplicativo.

O LibreOffice 26.2.6.3 efetivamente importou **171 células da demonstração e 243 do caso de texto**, em quatro abas de cada cenário, conservando os valores e tipos originais. Essa conferência usa as saídas ODS, lidas pela biblioteca padrão. O cenário comum conservou também o XLSX regravado. Na regressão ampliada de texto, o reexportador perdeu a proteção de dois padrões ST_Xstring; a comparação e a reabertura registram a diferença, com `equal:false` e `textRoundtripExact:false`. O produtor foi corrigido conforme a camada de escapes, e o arquivo original importa corretamente. A execução registra `completed-with-consumer-limitation`, sem afirmar preservação total da reexportação.

Em uma auditoria separada, os **72 caches de fórmulas** de três cenários autorais corresponderam aos esperados literais, com tolerância absoluta de `1e-12`. A execução usou perfil, HOME e diretórios XDG temporários e namespace de rede Linux sem conexão externa. Não usou um perfil pessoal e não modificou o consumidor.

Uma revisão funcional independente encontrou o problema inicial de escapes; os outros testes e 150 pequenos DAGs racionais confrontados com um oráculo de ponto fixo passaram. A confirmação dirigida pontuou o problema do produtor como **resolvido**, conferindo código, reconstrução byte a byte dos bundles, 15 testes de relatórios/CLI, 18 de interoperabilidade e as evidências armazenadas. Esse passe não executou novamente o LibreOffice nem reviu o produto inteiro. A regressão conserva os valores esperados e distingue a correção do arquivo original da limitação externa de salvamento.

Abrir as fixtures e conferir seus hashes não executa outra vez o consumidor. A CLI normal não depende de LibreOffice. Não foi exercitado Microsoft Excel e não é alegada equivalência geral de aritmética racional em planilhas.

## Distribuição e release

Os verificadores de distribuição conferem inventário exato, metadados e RECORD. Wheel e sdist precisam ser instalados em ambientes descartáveis fora da fonte; a CLI instalada deve gerar o exemplo, passar pelo leitor independente e preservar uma saída já existente.

O build local produziu um wheel de 13 membros (seis módulos e sete metadados/licenças) e um sdist de 52 membros (44 fontes revisadas e oito arquivos gerados do empacotamento). Ambos foram instalados em ambientes descartáveis fora da árvore fonte; a CLI gerou o exemplo, passou pelo leitor independente, teve RECORD conferido e preservou um destino existente. Os executáveis do LibreOffice e seus perfis não integram esses pacotes; os documentos sintéticos da prova acompanham a fonte.

A CI está configurada para repetir os testes em Python 3.11 a 3.14 no Linux e 3.14 no Windows, com um trabalho Linux separado para executar o LibreOffice real. Esse trabalho usa explicitamente a opção de registrar o contraexemplo conhecido; ele exige igualdade na importação original e informa as diferenças da reexportação. Os [resultados por commit](https://github.com/martinlofranodeoliveira/materiais-em-lote/actions) e a [release v1.0.0](https://github.com/martinlofranodeoliveira/materiais-em-lote/releases/tag/v1.0.0) identificam a versão e permitem conferir seus resultados públicos. Os checksums da release identificam os assets publicados separadamente dos hashes das fixtures de interoperabilidade.
