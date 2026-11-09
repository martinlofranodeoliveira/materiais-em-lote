# Materiais em Lote

Planeje materiais para pedidos usando listas técnicas com vários níveis. A ferramenta reúne as demandas de componentes compartilhados, desconta o estoque uma única vez e calcula os lotes de fabricação e as embalagens de compra. Cada resultado conserva sua memória de cálculo, com quantidades racionais exatas.

Biblioteca e CLI Python, licença MIT e documentação em português. Projeto da [LOFRANO TECNOLOGIA](https://lofranotecnologia.com.br/).

[Baixar a versão e o exemplo](https://github.com/martinlofranodeoliveira/materiais-em-lote/releases/tag/v1.0.0) · [Formato de entrada](docs/FORMATO.md) · [Validação](docs/VALIDACAO.md)

## Um pedido não é uma lista de compras direta

Na demonstração, um kit e um expositor usam painéis, suportes e tinta. Os próprios painéis também consomem tinta. Parte do kit e dos painéis já existe em estoque: essa parte não deve consumir componentes novamente.

O plano primeiro reúne todas as necessidades de cada item. Depois desconta seu estoque e calcula quantos lotes são necessários. Somente os lotes fabricados geram demanda para os componentes seguintes. A tinta recebe suas três origens antes de descontar o estoque e arredondar sua compra.

| Item do exemplo | Demanda bruta | Estoque | Necessidade líquida | Quantidade planejada | Saldo final |
| --- | --- | --- | --- | --- | --- |
| Kit de oficina | 3 un | 1 un | 2 un | Fabricar 2 un em 1 lote | 0 un |
| Expositor de bancada | 2 un | 0 un | 2 un | Fabricar 2 un em 2 lotes | 0 un |
| Painel preparado | 7 un | 2 un | 5 un | Fabricar 6 un em 2 lotes | 1 un |
| Suporte | 8 un | 1 un | 7 un | Comprar 8 un em 2 embalagens | 1 un |
| Chapa | 2 un | 1 un | 1 un | Comprar 2 un em 1 embalagem | 1 un |
| Tinta | 1.5 l | 0.3 l | 1.2 l | Comprar 2 l em 2 embalagens | 0.8 l |

O [cenário completo](fixtures/projeto-oficina.json) é original e fictício. A tinta soma `0.5 + 0.4 + 0.6 = 1.5 l`. Não existe total geral de quantidades: cada material mantém sua identidade e unidade.

## Experimente localmente

Requer Python 3.11 ou superior. Em um checkout deste repositório:

```sh
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# No PowerShell, use .venv\Scripts\Activate.ps1
python -m pip install .
materiais-em-lote exemplo --saida exemplo.zip
python -m zipfile -l exemplo.zip
```

O comando cria um ZIP novo contendo a entrada e seis relatórios/controles descritos abaixo. Extraia-o em uma pasta nova para abrir o XLSX ou ler o Markdown. O [exemplo da release](https://github.com/martinlofranodeoliveira/materiais-em-lote/releases/download/v1.0.0/exemplo.zip) também está pronto para baixar, sem instalar o programa para consultá-lo.

Para usar seus próprios dados:

```sh
materiais-em-lote planejar projeto.json --saida meu-plano.zip
materiais-em-lote planejar --help
```

O caminho de saída precisa ser novo e seu diretório pai precisa existir. Um arquivo já existente, diretório ou link nesse destino é preservado. A publicação usa um hardlink atômico; em um sistema de arquivos sem esse suporte, a operação informa falha e não tenta substituir o destino. A entrada é somente lida.

As dependências fixadas são `openpyxl==3.1.5` e `et-xmlfile==2.0.0`, ambas MIT. A instalação pode acessar o índice de pacotes; depois dela, os comandos funcionam localmente, sem rede, contas ou serviços. O [tutorial oficial do openpyxl](https://openpyxl.readthedocs.io/en/stable/tutorial.html) descreve a biblioteca usada para produzir o XLSX; o cálculo do plano é original deste projeto.

## O que fica no ZIP

| Arquivo | Finalidade |
| --- | --- |
| `projeto.json` | Bytes da entrada efetivamente usada, para conservar o cenário |
| `plano.json` | Itens, quantidades, pedidos, estrutura e todas as origens positivas |
| `plano.csv` | Uma tabela dos itens, com cabeçalhos estáveis para outros programas |
| `plano.md` | Leitura do plano e da memória de cálculo em português |
| `plano.xlsx` | Quatro abas estáticas: Plano, Origens, Pedidos e Estrutura |
| `LEIA-ME.md` | Orientação sobre unidades, arquivos e alcance |
| `manifesto.json` | Tamanho e SHA-256 dos seis outros arquivos, versão e hash da entrada |

**O XLSX é um relatório estático.** As quantidades são texto exato e não fórmulas ou números aproximados. Para recalcular, altere o JSON e gere outro pacote. Nomes que começam com `=`, `+`, `-` ou `@` continuam texto no XLSX; o CSV acrescenta um apóstrofo nesses casos, como documentado no formato. Não há macros, hyperlinks ou conexões externas geradas.

Os hashes identificam os bytes, sem autenticar seu autor. Os relatórios incluem os nomes e quantidades declarados na entrada; confira o conteúdo antes de compartilhá-los.

## API Python

```python
from materiais_em_lote import demo_project, plan_project, quantity_text

plano = plan_project(demo_project())
for item in plano.rows:
    if item.kind == "buy":
        print(item.item, quantity_text(item.planned), item.unit)
# chapa 2 un
# suporte 8 un
# tinta 2 l
```

`parse_project(bytes_ou_texto)` e `validate_project(dict)` produzem um projeto imutável. `plan_project(projeto)` devolve o plano com frações exatas. `build_bundle(bytes_ou_texto)` gera os bytes do ZIP sem escrever arquivos; `publish_bundle(bytes_ou_texto, destino)` publica o pacote em caminho novo. Erros de entrada usam `PlanError` com código, posição lógica e mensagem, sem repetir valores do arquivo.

## Regras e limites

- Até 250 itens, 2.000 relações de componentes e 250 demandas em JSON UTF-8 de até 1 MiB.
- Item comprado tem embalagem; item fabricado tem rendimento por lote e componentes por lote. Todo o catálogo precisa ser acíclico, inclusive a parte sem demanda.
- Quantidades de entrada são strings decimais sem sinal ou expoente, com até seis casas e valor máximo de `10^12`. Cálculos usam `Fraction`, sem ponto flutuante.
- Demanda precisa ser positiva. Estoque pode ser zero; omitir um item do estoque equivale a zero.
- Uma unidade por item, sem conversão automática. Um componente é medido na unidade do item referenciado.
- Todos os itens aparecem no plano. Sem pedidos, não há fabricação nem compra, e todo estoque continua no saldo final.
- Limites numéricos ou dados inválidos interrompem o cálculo inteiro, sem publicar um plano parcial.

O plano é uma projeção de um cenário fornecido. Não há preços, fornecedores, datas, capacidade de máquinas, reservas, compras reais, previsão ou otimização. O saldo calculado não altera um estoque existente. Veja o [contrato completo](CONTRACT.md).

## Verificação e contribuição

O [registro de validação](docs/VALIDACAO.md) separa testes do núcleo, conferência de arquivos e uso do LibreOffice real. A [interoperabilidade](docs/INTEROPERABILIDADE.md) cobre relatórios estáticos e cenários independentes de fórmulas; não promete igualdade racional geral em planilhas ou operação no Microsoft Excel.

Foi observada uma limitação concreta no LibreOffice 26.2.6.3: o XLSX original abre com os nomes literais corretos, mas salvar novamente altera dois padrões de texto que parecem escapes OOXML. A prova registra essa diferença, sem apresentá-la como igualdade. O relatório do programa permanece estático e o JSON conserva os valores para gerar outra cópia; veja os casos exatos no registro de interoperabilidade.

```sh
python -m unittest discover -s tests -v
python tools/check_bundle.py exemplo.zip --demo
python tools/verify_libreoffice.py --check-fixtures
```

Para desenvolver, veja [CONTRIBUTING.md](CONTRIBUTING.md). Para comunicar uma vulnerabilidade, veja [SECURITY.md](SECURITY.md). Código original sob [MIT](LICENSE), com atribuições das dependências em [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
