# Relatar uma vulnerabilidade

Use a área de [segurança do repositório](https://github.com/martinlofranodeoliveira/materiais-em-lote/security) para consultar os canais privados disponíveis. Se um canal privado não estiver habilitado, abra uma issue pedindo contato sem anexar dados sensíveis ou detalhes exploráveis.

Inclua versão, sistema, comando e uma entrada mínima sintética. Não envie estoques, pedidos, nomes comerciais privados ou credenciais.

O aplicativo lê um JSON explícito e gera relatórios locais. A entrada é validada antes de publicar a saída; o destino precisa ser novo. Os relatórios conservam os dados declarados e devem ser revisados antes de compartilhamento. Hashes de integridade não são assinatura ou prova de autenticidade.

A biblioteca usa openpyxl para gerar sua própria planilha; não abre XLSX de terceiros no fluxo normal. O consumidor LibreOffice usado em QA é separado. Não há serviço de rede, conta ou controle de acesso fornecido por este pacote.
