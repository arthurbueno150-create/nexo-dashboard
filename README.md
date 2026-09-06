# Nexo

**Clareza em cada célula.** Um dashboard em Python que transforma planilhas de finanças, vendas, estoque e outros dados tabulares em indicadores, gráficos e tabelas exploráveis.

## Executar

Requer **Python 3.11 ou superior**. Não precisa de Node.js, TypeScript ou etapa de build.

```bash
git clone https://github.com/arthurbueno150-create/nexo-dashboard.git
cd nexo-dashboard
python -m venv .venv
```

No Windows (PowerShell):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

No macOS ou Linux:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

Abra **http://127.0.0.1:3000**. O servidor Waitress inicia sem modo de depuração. Para encerrar, pressione `Ctrl+C` no terminal. Para testar, use o Python desse mesmo ambiente:

```bash
python -m unittest discover -s tests -v
```

## O que funciona

- Importação de **XLSX, XLS, CSV e TSV**, com seleção de abas e detecção de cabeçalhos e tipos.
- Indicadores financeiros, análise de colunas numéricas e contagem para tabelas de texto.
- Gráficos calculados em Python e renderizados em SVG, sem serviços externos.
- Busca sem distinção de acentos, filtro por categoria e datas, ordenação e paginação.
- Ajuste manual da métrica, categoria, data, tipo de movimentação e modo de análise.
- Qualidade dos dados: células vazias, duplicatas e valores inválidos.
- Regras reutilizadas durante a sessão: ignorar linhas vazias, aparar espaços e remover duplicatas exatas.
- Exportação de **todos os registros filtrados** em CSV e relatório em JSON. Decimais do JSON são strings para preservar precisão.
- Interface responsiva em português e exemplos fictícios de finanças, vendas e estoque.

Os cálculos, a importação, as regras, os filtros e as exportações rodam em **Python**. Flask e Jinja entregam HTML/CSS; um pequeno arquivo JavaScript melhora o envio de formulários e o arraste de arquivos. Os formulários também funcionam sem JavaScript.

## Experimentar com uma planilha

Use [`examples/nexo-dados-ficticios.xlsx`](examples/nexo-dados-ficticios.xlsx). O arquivo possui três abas com dados inteiramente fictícios:

| Aba | Registros | O que conferir |
| --- | ---: | --- |
| Finanças | 74 | Receitas de R$ 89.100,00, despesas de R$ 60.774,00 e saldo de R$ 28.326,00 |
| Vendas | 36 | Quantidades e valores de vendas, com resultados de fórmulas salvos |
| Estoque | 20 | Quantidades, valores e códigos SKU com zeros à esquerda |

Na aba Finanças, ative **Remover linhas duplicadas** em Automações e clique em **Aplicar regras**. A contagem passa para 72, as despesas para R$ 55.689,00 e o saldo para R$ 33.411,00. Desative a regra para recuperar os registros na análise; o arquivo original não é modificado.

## Como interpretar os resultados

A detecção automática é uma sugestão: confira **Configurar análise**, especialmente em arquivos com títulos, células mescladas ou várias tabelas na mesma aba. É possível selecionar uma das primeiras 30 linhas como cabeçalho.

No modo financeiro, Receita/Despesa, Entrada/Saída e Crédito/Débito (também equivalentes em inglês) classificam movimentações pelo valor absoluto. Tipos não reconhecidos são destacados e ficam fora do saldo. Sem coluna de tipo, o modo financeiro manual usa o sinal do valor. Todos os status são incluídos; aplique filtros para restringir a seleção.

CSV aceita UTF-8 e Windows-1252. Valores como `1.234,56`, `1,234.56`, `R$ 50,00` e `12%` são reconhecidos. Na ambiguidade, `1.234` é mil duzentos e trinta e quatro e `1,234` é um decimal. Códigos detectados como identificadores não viram métricas automaticamente. Fórmulas não são calculadas: o Excel é lido usando o último resultado salvo. Salve o arquivo em um editor de planilhas que atualize esses resultados antes de importar.

As automações recalculam o painel quando você importa, filtra ou aplica regras. Não existe monitoramento de arquivos em disco: reimporte a planilha quando ela mudar. Uma nova importação com cabeçalhos iguais mantém o mapeamento escolhido na sessão.

## Dados e limites

Os arquivos são enviados ao **servidor Python**. Ao executar localmente, esse servidor está no seu computador. Em uma hospedagem, os dados chegam ao servidor de quem hospeda o aplicativo. Nenhuma planilha é enviada a APIs de terceiros, e não há armazenamento permanente dos uploads.

Dados e preferências ficam em memória, separados por sessão de navegador. São descartados ao encerrar a sessão ou o servidor. Sessões com mais de duas horas sem atividade são removidas na próxima requisição; a expiração não é uma garantia de eliminação física da memória. O cookie contém apenas um identificador assinado. Reiniciar o servidor também redefine as sessões.

Limites: **15 MB por arquivo**, 50.000 registros, 200 colunas e 300.000 células por aba; 500.000 células por arquivo; até 16 sessões e 2 milhões de células importadas entre sessões. A leitura roda em processo separado e é interrompida após 30 segundos. Arquivos protegidos por senha, macros e formatos diferentes dos listados não são suportados. CSV exportado neutraliza textos que poderiam ser interpretados como fórmulas.

## Configuração e hospedagem

Configure variáveis no ambiente antes de iniciar (não há carregamento automático de `.env`):

| Variável | Padrão | Uso |
| --- | --- | --- |
| `PORT` | `3000` | Porta HTTP |
| `NEXO_HOST` | `127.0.0.1` | Endereço de escuta; `0.0.0.0` para um servidor acessível pela rede |
| `NEXO_ALLOWED_HOSTS` | `localhost,127.0.0.1,[::1]` | Nomes permitidos, separados por vírgula, sem protocolo nem porta |
| `NEXO_SECRET_KEY` | Aleatória a cada início | Segredo de assinatura do cookie; mantenha fora do Git |
| `NEXO_SECURE_COOKIE` | Desativado | `1` quando a aplicação for servida exclusivamente por HTTPS |

A aplicação usa **um processo servidor**, com threads e sessões em memória. Não configure múltiplos processos ou réplicas sem antes implementar armazenamento compartilhado para as sessões. Para acesso público, configure HTTPS e controle de acesso no ambiente de hospedagem: o projeto não oferece cadastro ou autenticação de usuários. GitHub Pages hospeda conteúdo estático e não executa este servidor Python.

## Estrutura

```text
app.py                 Inicialização Flask + Waitress
nexo/engine.py         Detecção, limpeza e cálculo com Decimal
nexo/imports.py        Leitura dos quatro formatos com limites
nexo/charts.py         Geometria dos gráficos SVG
nexo/web.py            Rotas, sessões, filtros e downloads
templates/            Páginas Jinja
static/               CSS, ícones e melhoria dos formulários
tests/                Testes unitários e de integração
examples/             Planilha fictícia para experimentar
```

Versão 2: migração da aplicação TypeScript para Python, preservando o histórico do repositório. Licença [MIT](LICENSE).
