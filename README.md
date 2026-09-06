# Nexo
### Inteligência para suas planilhas

Nexo transforma arquivos Excel e CSV em um painel interativo com indicadores, gráficos, filtros e regras de limpeza. A interface está em português e toda a leitura de planilhas acontece no navegador, em um Web Worker.

## O que funciona

- Importação de XLSX, XLS, CSV e TSV; seleção de múltiplas abas de um mesmo arquivo.
- Detecção de cabeçalho, colunas numéricas, textos, datas e identificadores.
- Ajuste manual do cabeçalho (primeiras 30 linhas), indicador, categoria, data e tipo de análise.
- Indicadores financeiros de receitas, despesas e saldo; análise geral de soma, média e contagem.
- Gráficos mensais, comparação por categoria e distribuição de despesas.
- Busca sem distinção de acentos, filtros por categoria e intervalo de datas.
- Tabela com ordenação, paginação e exportação CSV da seleção.
- Relatório JSON contendo filtros, configuração, indicadores e qualidade.
- Limpeza de espaços, remoção opcional de duplicados e exclusão de linhas vazias.
- Perfil de qualidade com células vazias, duplicados e valores numéricos inválidos.
- Exemplos fictícios de finanças, vendas e estoque.
- Layout responsivo, controles acessíveis e navegação por teclado.

## Executar localmente

Requisitos: Node.js 22.13 ou superior e pnpm 11.

~~~sh
pnpm install
pnpm dev
~~~

Abra o endereço exibido no terminal, normalmente http://localhost:3000.

~~~sh
pnpm typecheck
pnpm test
pnpm build
~~~

O projeto usa o scaffold oficial de Sites com React 19, TypeScript, Vinext/Vite, Shadcn/Base UI, Recharts e SheetJS CE 0.20.3. A versão de SheetJS vem da distribuição oficial: https://docs.sheetjs.com/docs/getting-started/installation/nodejs/

O build gera um Worker compatível com Cloudflare e arquivos do cliente em dist/. Para testar esse resultado localmente:

~~~sh
pnpm start
~~~

Publicar o código em um repositório GitHub não hospeda automaticamente o dashboard. O build atual usa Cloudflare Workers, e não é um pacote estático pronto para GitHub Pages.

## Experimente com um Excel real

Importe **examples/nexo-dados-ficticios.xlsx**.

| Aba | Conteúdo |
| --- | --- |
| Finanças | 74 lançamentos de janeiro a junho de 2026, incluindo duas duplicatas, campos vazios e uma categoria com espaços |
| Vendas | 36 vendas com total calculado por quantidade × preço unitário |
| Estoque | 20 produtos com SKU textual e valor em estoque calculado |

Na aba Finanças, com a remoção de duplicados **desativada**, o resultado esperado é:

| Indicador | Resultado |
| --- | --- |
| Registros | 74 |
| Receitas | R$ 89.100,00 |
| Despesas | R$ 60.774,00 |
| Saldo | R$ 28.326,00 |

Com a remoção **ativada**, são 72 registros, receitas de R$ 89.100,00, despesas de R$ 55.689,00 e saldo de R$ 33.411,00. Estes valores incluem todos os status.

## Regras de interpretação

**Estrutura:** cada aba deve conter uma tabela com uma linha de cabeçalhos. Títulos ou cabeçalhos mesclados podem exigir ajuste manual. Tabelas independentes na mesma aba devem ser separadas antes da importação.

**Finanças:** com uma coluna de tipo, Receita/Entrada/Crédito e equivalentes em inglês são entradas; Despesa/Saída/Débito são saídas. O tipo prevalece sobre o sinal. Tipos desconhecidos são sinalizados e excluídos do saldo. Sem coluna de tipo, positivos são entradas e negativos são saídas. Para receitas e despesas em colunas separadas, normalize para Tipo + Valor ou analise as colunas individualmente.

**Números:** células numéricas de Excel mantêm seus valores. Texto aceita R$ 1.234,56 e 1,234.56. Sem contexto adicional, 1.234 é tratado como mil duzentos e trinta e quatro; 1,234 como 1,234 decimal. Percentuais textuais são convertidos para frações. Códigos como SKU e CPF não são escolhidos como medidas automaticamente.

**Datas:** dia/mês/ano, ano-mês-dia e datas nativas de Excel. Datas inválidas são excluídas da evolução e de filtros temporais e são sinalizadas. Os cartões continuam incluindo registros sem data quando nenhum filtro temporal está ativo.

**Fórmulas:** usa o último resultado salvo no Excel. Não recalcula fórmulas nem executa macros. Salve o arquivo após o recálculo no Excel ou LibreOffice.

**Automação:** limpeza e análise acontecem a cada importação, alteração de regra ou filtro. Reimportar cabeçalhos idênticos reutiliza o mapeamento da sessão. Não há monitoramento automático de arquivos em disco, tarefas agendadas ou conexão com Google Sheets.

## Privacidade e limites

Os dados permanecem em memória durante a sessão da página; não são enviados a um servidor nem gravados em localStorage. Recarregar a página descarta a planilha. Apenas as preferências de limpeza e a abertura do menu podem ficar salvas no navegador.

- Um arquivo de até 15 MB por importação.
- Até 50.000 registros, 200 colunas e 300.000 células por aba.
- Até 500.000 células no arquivo.
- Timeout de leitura: 30 segundos.
- Arquivos protegidos por senha não são suportados.
- Limites de desempenho variam conforme o dispositivo.
- Valores são calculados com números JavaScript; não substitui contabilidade com precisão decimal arbitrária.
- Exportações CSV neutralizam textos que possam ser interpretados como fórmulas.
- A análise é determinística; não depende de uma API de IA.

## Estrutura

~~~text
app/page.tsx          Interface e estado da sessão
app/globals.css       Identidade visual e responsividade
lib/engine.ts         Detecção, limpeza, filtros e cálculos
lib/import.worker.ts  Leitura isolada de Excel e CSV
tests/engine.test.ts  Testes de regras e cálculos
examples/            Planilha fictícia de teste
.openai/hosting.json  Configuração do scaffold de Sites
~~~

O navegador pode expor read_dashboard_summary via WebMCP quando houver suporte. É uma ferramenta somente de leitura dos indicadores já visíveis, sem transmissão externa.

## Validação

Os testes automatizados cobrem formatos numéricos, datas inválidas, CSV multilinha, cabeçalhos duplicados, preservação de identificadores, classificação financeira, filtros e exportação. A importação da planilha de exemplo, a alternância de telas e a remoção reversível dos duplicados também foram verificadas na prévia local.

## Licença

MIT. Os dados de exemplo são fictícios.


