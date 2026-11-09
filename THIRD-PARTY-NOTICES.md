# Componentes de terceiros

O código e os exemplos originais de Materiais em Lote são MIT; veja `LICENSE`.
O wheel contém somente o pacote original e seus avisos. As dependências são
instaladas separadamente, sob suas próprias licenças:

| Componente | Versão fixada | Licença | Finalidade |
| --- | --- | --- | --- |
| [openpyxl](https://pypi.org/project/openpyxl/3.1.5/) | 3.1.5 | MIT | Escrever o relatório XLSX estático. |
| [et_xmlfile](https://pypi.org/project/et-xmlfile/2.0.0/) | 2.0.0 | MIT | Dependência de escrita XML do openpyxl. |

O build usa [setuptools 84.2.1](https://pypi.org/project/setuptools/84.2.1/)
(MIT) e o comando de desenvolvimento usa [build 1.6.1](https://pypi.org/project/build/1.6.1/)
(MIT). Essas ferramentas não são dependências de execução do pacote.

[LibreOffice](https://www.libreoffice.org/about-us/licenses/) é um consumidor
externo para QA (MPL 2.0, com componentes sob outras licenças). Não é incorporado, instalado pela CLI nem
necessário para calcular o plano ou gerar seu relatório. O job de CI dedicado
o instala explicitamente. Seus executáveis e arquivos de perfil permanecem fora da distribuição.
O sdist inclui apenas os documentos sintéticos autorais de QA e sua evidência
JSON; o wheel contém somente código e avisos do pacote. A evidência registra
a versão efetivamente executada; não representa teste em Microsoft Excel.

Não há fontes, imagens, dados pessoais, modelos de IA ou assets externos
incorporados. A demonstração e os cenários de auditoria são autorais.
