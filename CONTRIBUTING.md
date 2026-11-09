# Contribuir

Descreva a situação, a entrada mínima fictícia, o resultado esperado e o observado. Listas técnicas e estoques podem conter informações da operação: use dados sintéticos em issues e testes.

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install . build==1.6.1
python -m unittest discover -s tests -v
python -m build
python scripts/check_distribution.py --dist dist
```

No Windows, ative com `.venv\Scripts\Activate.ps1`. Instale novamente o pacote depois de mudar a fonte, ou use `pip install -e .` durante o desenvolvimento.

O núcleo está em `src/materiais_em_lote/core.py`; demonstração, relatórios e CLI têm módulos separados. Leia [CONTRACT.md](CONTRACT.md) antes de alterar esquemas, ordem, limites ou regra de lote. Preserve aritmética exata, agregação antes do desconto de estoque e falha integral em dados inválidos. Mudanças de comportamento precisam de casos que detectem o problema, preferencialmente com valores manuais ou oráculo independente.

O LibreOffice é uma ferramenta externa de QA. A conferência de fixtures existentes não o executa novamente. Para um ensaio novo, siga [docs/INTEROPERABILIDADE.md](docs/INTEROPERABILIDADE.md), com perfil temporário exclusivo e entrada sintética. Não use um perfil pessoal ou documentos reais; não introduza rede ou macros no aplicativo.

Não publique o projeto no índice de pacotes ou GitHub como parte dos testes. `scripts/package_release.py` prepara arquivos locais e não envia nada. Preserve as licenças MIT e as atribuições das dependências.
