# Contrato 1.0.0 - Materiais em Lote

Python >=3.11. Código original MIT. Dependência de exportação openpyxl==3.1.5 (MIT), et-xmlfile==2.0.0 (MIT). Sem rede, relógio, banco ou serviço na biblioteca/CLI. LibreOffice é consumidor externo de QA, nunca dependência de execução. Erros são PlanError(code,path,message), sem repetir valores da entrada, caminhos absolutos ou tracebacks na CLI.

## Entrada fechada

JSON UTF-8 estrito, sem BOM, chaves repetidas, NaN/Infinity, floats ou inteiros substituindo quantidades. Até 1 MiB, profundidade estrutural <=12. Objetos e arrays JSON comuns; API recusa subclasses/objetos arbitrários. Campos exatos, nenhum extra ou ausente. version é int exato 1, não bool.

Projeto: {version:1,title:string,items:[Item],demands:[Demand],stock:[Stock]}.

Item comprado: {id,name,unit,kind:'buy',pack:quantity}.
Item fabricado: {id,name,unit,kind:'make',batch:quantity,components:[{item,quantity}]}.
Component.quantity é a quantidade NA UNIDADE DO FILHO consumida por UM LOTE do pai. Item.batch é o rendimento de um lote na unidade do pai. pack é a quantidade por embalagem na unidade do comprado. batch e pack são positivos. Fabricados têm pelo menos um componente; comprados não têm componentes. Referências existem; componentes distintos por pai; todo o catálogo é acíclico, inclusive itens sem demanda.

Demand: {id,item,quantity}, quantity positiva; IDs distintos. Stock: {item,quantity}, quantity >=0, no máximo um por item, omitido significa zero. Não converter unidades. A unidade de um item aplica-se a todo estoque/demanda do mesmo ID e a componentes que o referenciam.

IDs item/demand: [a-z][a-z0-9_-]{0,39}. unit: [a-z][a-z0-9_-]{0,15}. title 1..120 pontos Unicode; name 1..100. Textos sem espaços externos, C0/DEL, surrogates, U+2028/U+2029/U+FFFE/U+FFFF; sem interpretação HTML, fórmulas ou links. Até 250 itens, 2000 arestas e 250 demandas. items não vazio, demands/stock podem ser vazios. Quantidade de ENTRADA é string decimal ASCII: 0 ou inteiro sem zero à esquerda, fração opcional de 1..6 casas; sem sinal/expoente; valor <=10^12. Saídas usam texto decimal exato sem zeros dispensáveis quando finito, ou n/d irredutível. A função quantity_text(Fraction) é pública. Valor absoluto de qualquer resultado <=10^12; numerador e denominador reduzidos até 80 dígitos. Se exceder, falhar integralmente E_LIMIT, sem plano parcial.

## API de core (core.py, agente de núcleo)

PlanError(ValueError): .code,.path,.message. Mensagens em português.
parse_project(data: bytes|str) -> Project. validate_project(mapping:dict) -> Project. dataclasses frozen com tuplas, sem aliases mutáveis.
Component(item:str,quantity:Fraction); Item(id,name,unit,kind,lot:Fraction,components:tuple[Component,...]); Demand(id,item,quantity); Stock(item,quantity); Project(title,items:tuple[Item,...],demands:tuple[Demand,...],stock:tuple[Stock,...]). validate_project aceita apenas formato JSON, não Project. plan_project(Project) -> Plan, revalida fronteira de dataclasses para instâncias forjadas; não confiar em objetos construídos pelo chamador.

Plan(title,rows:tuple[PlanRow,...],origins:tuple[Origin,...],demands:tuple[Demand,...],edges:tuple[Edge,...]). PlanRow(item,name,unit,kind,level:int,lot:Fraction,gross:Fraction,stock:Fraction,used:Fraction,net:Fraction,lots:int,planned:Fraction,leftover:Fraction). Origin(item,kind:'direct'|'parent',source:str,quantity:Fraction). Edge(parent,child,per_batch:Fraction). Direct.source é ID da demanda; parent.source é ID do pai. Origens somente positivas; uma por demanda direta e por aresta com pai produzindo. Nenhuma atribuição inventada do estoque ou do arredondamento a raízes específicas.

Topologia Kahn com desempate lexicográfico de ID, todo pai antes de filho. level = maior caminho a partir de uma raiz do catálogo, raiz0. Acumular gross de TODAS as origens. used=min(gross,stock); net=max(gross-stock,0); lots=ceil(net/lot), inteiro exato (0 se net0); planned=lots*lot; leftover=stock+planned-gross. Se make, cada aresta contribui lots*per_batch ao filho. Estoque de submontagem reduz produção e consumo de filhos. Se buy, sem propagação. Todos os itens aparecem, até sem demanda; estoque sem demanda fica inteiro em leftover. Ordem de rows é Kahn, origins por ordem de rows/item, kind direct antes parent e source lexical; demands por ID; edges por parent/child. Resultado independente da ordem dos arrays de entrada, sem mutar entrada.

## Demonstração original (demo.py, núcleo)

demo_project() -> Project e demo_mapping() -> dict novo, sem I/O. Título 'Uma oficina, dois pedidos'. Seis itens:
kit, 'Kit de oficina', un, make batch2: painel3, suporte4, tinta0.5 por lote.
expositor, 'Expositor de bancada', un, make batch1: painel2, suporte2, tinta0.2.
painel, 'Painel preparado', un, make batch3: chapa1, tinta0.3.
suporte, 'Suporte', un, buy pack4. chapa, 'Chapa', un, buy pack2. tinta, 'Tinta', l, buy pack1.
Demandas pedido-kit:kit3, pedido-expositor:expositor2. Estoque kit1, painel2, suporte1, chapa1, tinta0.3. Sem estoque expositor.
Esperado manual: kit gross3/used1/net2/lots1/planned2/leftover0; expositor2/0/2/2/2/0; painel7/2/5/2/6/1; suporte8/1/7/2/8/1; chapa2/1/1/1/2/1; tinta1.5/0.3/1.2/2/2/0.8. tinta acumula0.5+0.4+0.6 antes do estoque. Quantidades de unidades diferentes nunca são somadas em total geral.

## Relatórios e CLI (root)

__version__='1.0.0'. CLI `materiais-em-lote planejar projeto.json --saida novo.zip`, `materiais-em-lote exemplo --saida novo.zip`, `materiais-em-lote --version`. Exemplo inclui sua entrada original autoral. Saída ZIP contém exatamente projeto.json (bytes lidos), plano.json, plano.csv, plano.md, plano.xlsx, LEIA-ME.md, manifesto.json. Manifesto exclui a si próprio, registra SHA256/tamanho dos seis membros, inputSHA256 e versão. Não incluir nomes de host, paths, hora, usuário ou estado do ambiente.

Relatório JSON: {version:1,title,items:[row],origins:[origin],demands:[demand],edges:[edge]}; nomes de campos das dataclasses preservados, todas as quantidades Fraction viram quantity_text; lots e level são int. CSV uma tabela das rows com cabeçalhos estáveis do JSON, UTF-8 e LF; protege texto autoral com líder de fórmula e documenta o apóstrofo acrescentado. Markdown identifica quantidades/unidades por item e memória de origens, escapa texto autoral. XLSX é relatório estático, todas as células explicitamente texto salvo lots/level inteiros; sem fórmulas, hyperlinks, macros ou conexões externas. Abas Plano, Origens, Pedidos, Estrutura. Preservar texto exato, inclusive líderes de fórmula, acentos e caracteres XML escapados; quantidades como texto exato, não binary float. Estilos de tabela/filtro, cabeçalho congelado e impressão em largura legível; não alegar Excel real testado. ZIPs gerados com nomes/timestamps/metadados fixos; reprodutibilidade no mesmo ambiente e versões, sem promessa entre compressores diferentes.

Construir todos os bytes antes de publicar. Saída precisa ser nova, parent existente; nenhum overwrite. Preparar temp regular no mesmo diretório e publicar arquivo completo via hardlink atômico sem substituição; apagar temp sempre. Se filesystem não suporta hardlink, erro explícito, não fallback inseguro. Preservar destino existente/entrada até em falhas. Não escrever bundle parcial em erro de validação. CLI códigos0sucesso,2entrada/uso,3I/O; stderr sanitizado, stdout só mensagem de sucesso/caminho que o chamador forneceu. Sem stdin/env implícitos, sem subprocess/network na execução normal.

## Prova externa (agente interop)

Independente do core: verificador stdlib de ZIP/XML/JSON/CSV reconstrói relações e conta rastros, compara demonstração a valores manuais. Abrir o XLSX realmente produzido pela CLI no LibreOffice headless com perfil temporário exclusivo, salvar novamente em diretório novo e comparar as quatro abas/células (incluindo payloads de texto com líderes de fórmula em caso específico). Sem ler perfil existente, macros, rede ou imprimir. Criar separado um XLSX de auditoria com fórmulas autorais independentes e esperados literais para demo, estoque de submontagem e item compartilhado com profundidades diferentes; LibreOffice recalcula e stdlib lê caches. Essa auditoria prova aqueles cenários, não converte o relatório estático em planilha dinâmica ou garantia geral de aritmética racional em Excel.

Regressão de interoperabilidade: proteger literais que parecem escapes ST_Xstring na escrita; o leitor independente os interpreta uma vez por trecho de texto. Exigir importação inicial de TODOS os textos/tipos, verificada por exportação ODS sem essa camada de escapes. A comparação após reexportação XLSX deve registrar igualdade ou divergência, nunca trocar os esperados para produzir sucesso. Foram observadas duas perdas do reexportador LibreOffice26.2.6.3 em padrões protegidos/sobrepostos, embora o original importe corretamente. O modo estrito falha nessas diferenças; somente uma opção explícita pode registrar o contraexemplo conhecido com status completed-with-consumer-limitation e equal:false. O cenário comum e as fórmulas continuam exigindo seus resultados originais. Não modificar upstream, inserir diferenças tipográficas artificiais ou excluir textos válidos do projeto para contornar a falha externa.

## Empacotamento (agente de release)

Pacote src layout materiais_em_lote. pyproject setuptools, script CLI .cli:main, pacote original MIT, dependências exatas. Wheel/sdist sem local/.venv/QA privado. CI Linux Python3.11..3.14 e Windows3.14; build/instalação e execução fora da fonte, fixture demo/bundle/reader independente, destino existente preservado. Job LibreOffice Linux separado com execução externa explícita. Pinar Actions por SHA. Checks verificam inventário de distribuição e metadados/RECORD. Release v1.0.0 com wheel,sdist,exemplo.zip,SHA256SUMS. Root publica após checks/CI, redownload e verificação pública, preserva README do perfil.
