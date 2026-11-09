# Materiais em Lote

Biblioteca e CLI Python para transformar pedidos e listas técnicas multinível em necessidades de fabricação e compra. Projeto aberto MIT da LOFRANO TECNOLOGIA, documentação em português. Não há serviço, conta, compra real ou integração com estoque existente.

O uso proposto é uma oficina ou pequeno fabricante que já conhece seus produtos, quantidades e unidades. É uma hipótese de utilidade, sem alegar clientes ou pesquisa externa. A fila de pedidos e o estoque são declarações do arquivo de entrada, sem vínculo com uma data, calendário ou reserva real.

O mecanismo reúne TODAS as demandas de um item antes de descontar seu estoque uma vez. Somente a produção necessária, arredondada por lote declarado, demanda componentes. Comprados são arredondados por embalagem. O plano conserva cada origem direta e dependente e explica a sobra do lote. Quantidades são racionais exatas; não há conversão implícita de unidades, preços, previsão ou otimização.

Em 09/11/2026, o inventário público tinha 251 repositórios. Não foi identificado nesse inventário um planejamento BOM/MRP com esse desconto de estoque e propagação multinível. Os READMEs dos três vizinhos mais próximos foram consultados: Receitas em Escala agrega ingredientes por porções, Cabinet Assembly exporta painéis e Taskgraph Plan organiza dependências; seus mecanismos documentados não substituem este cálculo. Legendas, áudio e imposição PDF foram descartados por já existirem equivalentes.

Entrega: pacote Python instalável, CLI, API documentada, JSON/CSV/Markdown/XLSX em ZIP de saída, exemplo original completo e evidência de LibreOffice real. Preservar o README principal do perfil; divulgar somente em PROJETOS-ABERTOS.md e EVIDENCIAS.md. Nenhum dado ou segredo de outros projetos será copiado.
