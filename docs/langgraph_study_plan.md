# План изучения: LangGraph Workflow + Planning Agent + HITL + Code Interpreter + Skills

> **Цель:** Понять, как построить production-ready архитектуру из `roadmap.md`:
> ```
> LangGraph Workflow → Planning Agent → Human Review → Approved Plan → Code Interpreter → Skills + Parquet
> ```
> **Формат:** Атомарные темы для заметок в Obsidian (одна заметка = одна атомарная тема).
> **Стиль:** Как в твоём `Обучение/` — коротко, с кодом, диаграммами, ссылками на реальные примеры.

---

## 🗂️ Структура папки в Obsidian

```
Mirrolla_Study/
├── 01_LangGraph_Fundamentals/
├── 02_StateGraph_Architecture/
├── 03_Checkpointing_Persistence/
├── 04_HITL_Interrupts/
├── 05_Planning_Agent_Patterns/
├── 06_Code_Interpreter_Integration/
├── 07_Skills_Architecture/
├── 08_Parquet_Data_Layer/
├── 09_Streaming_Observability/
├── 10_Production_Patterns/
├── 11_Real_World_Examples/
└── 12_Mirrolla_Specific/
```

---

## 01_LangGraph_Fundamentals — Базовые примитивы

| Атомарная тема | Что изучить | Файл в Obsidian | Ресурсы |
|----------------|-------------|-----------------|---------|
| **LangGraph vs LangChain** | Почему Graph, а не Chain. Stateful, cycles, human-in-the-loop. | `LangGraph_vs_LangChain.md` | [LangGraph Concepts](https://langchain-ai.github.io/langgraph/concepts/) |
| **StateGraph: State, Nodes, Edges** | `TypedDict`/`Pydantic` state, `add_node`, `add_edge`, `add_conditional_edges`. | `StateGraph_Primitives.md` | [StateGraph API](https://langchain-ai.github.io/langgraph/reference/graphs/) |
| **Reducers (Аннотации состояния)** | `Annotated[list, operator.add]`, `Annotated[dict, merge_dicts]` — как накапливать историю. | `Reducers_Accumulating_State.md` | [Reducers](https://langchain-ai.github.io/langgraph/concepts/low_level/#reducers) |
| **Compiled Graph (Runnable)** | `.compile()` → `Runnable` interface: `invoke`, `stream`, `batch`, `ainvoke`, `astream`. | `Compiled_Graph_Runnable.md` | [Runnable Interface](https://python.langchain.com/docs/concepts/runnables/) |
| **Streaming Modes** | `stream_mode="values"` / `"updates"` / `"debug"` / `"custom"`. Что возвращает каждый. | `Streaming_Modes.md` | [Streaming](https://langchain-ai.github.io/langgraph/how-tos/streaming/) |
| **Visualization** | `graph.draw_mermaid()`, `draw_ascii()`, `IPython.display.Image`. | `Graph_Visualization.md` | [Visualization](https://langchain-ai.github.io/langgraph/how-tos/visualize/) |

---

## 02_StateGraph_Architecture — Паттерны архитектуры графа

| Атомарная тема | Что изучить | Файл в Obsidian | Ресурсы |
|----------------|-------------|-----------------|---------|
| **Linear vs Branching vs Cyclic** | Последовательный пайплайн, параллельные ветки, циклы (retry, reflection). | `Graph_Topologies.md` | [Control Flow](https://langchain-ai.github.io/langgraph/concepts/control_flow/) |
| **Subgraphs (Модульность)** | `StateGraph` как узел родительского графа. Изоляция состояния, передача подмножества полей. | `Subgraphs_Modularity.md` | [Subgraphs](https://langchain-ai.github.io/langgraph/concepts/subgraphs/) |
| **Recursion Limit** | `config={"recursion_limit": 50}` — защита от бесконечных циклов. | `Recursion_Limit.md` | [Recursion Limit](https://langchain-ai.github.io/langgraph/reference/graphs/#langgraph.graph.state.CompiledStateGraph.invoke) |
| **Node Retry Policies** | `retry` decorator, `RetryPolicy` — экспоненциальный backoff, jitter. | `Node_Retry_Policies.md` | [Retries](https://langchain-ai.github.io/langgraph/how-tos/node-retries/) |
| **Error Handling Nodes** | `try/except` в узле → специальный узел ошибки → `Command(goto="error_handler")`. | `Error_Handling_Nodes.md` | [Error Handling](https://langchain-ai.github.io/langgraph/how-tos/error-handling/) |
| **Conditional Edges (Routing)** | Функция-роутер возвращает строку (имя следующего узла) или `END`. | `Conditional_Edges_Routing.md` | [Conditional Edges](https://langchain-ai.github.io/langgraph/concepts/control_flow/#conditional-edges) |
| **Multiple Entry Points** | `set_entry_point` vs `set_conditional_entry_point`. | `Multiple_Entry_Points.md` | [Entry Points](https://langchain-ai.github.io/langgraph/reference/graphs/#langgraph.graph.state.StateGraph.set_entry_point) |

---

## 03_Checkpointing_Persistence — Сохранение состояния

| Атомарная тема | Что изучить | Файл в Obsidian | Ресурсы |
|----------------|-------------|-----------------|---------|
| **Checkpointer Interface** | `BaseCheckpointSaver`: `put`, `get`, `list`, `put_writes`. | `Checkpointer_Interface.md` | [Checkpointer](https://langchain-ai.github.io/langgraph/reference/checkpoints/) |
| **MemorySaver (In-Memory)** | Для разработки/тестов. Не выживает после перезапуска. | `MemorySaver.md` | [MemorySaver](https://langchain-ai.github.io/langgraph/reference/checkpoints/#langgraph.checkpoint.memory.MemorySaver) |
| **SqliteSaver (Локальный файл)** | `.checkpoint.sqlite` — для MVP, HITL без сервера БД. | `SqliteSaver.md` | [SqliteSaver](https://langchain-ai.github.io/langgraph/reference/checkpoints/#langgraph.checkpoint.sqlite.SqliteSaver) |
| **PostgresSaver (Продакшн)** | Таблицы: `checkpoints`, `checkpoint_writes`, `checkpoint_blobs`. Миграции. | `PostgresSaver.md` | [PostgresSaver](https://langchain-ai.github.io/langgraph/reference/checkpoints/#langgraph.checkpoint.postgres.PostgresSaver) |
| **Checkpoint Structure** | `Checkpoint` tuple: `(config, metadata, values, parent_config)`. Что внутри `values` (state). | `Checkpoint_Structure.md` | [Checkpoint Tuple](https://langchain-ai.github.io/langgraph/concepts/persistence/#checkpoint-tuple) |
| **Thread ID / Run ID** | `config={"configurable": {"thread_id": "session-123"}}` — изоляция сессий. | `Thread_Run_ID.md` | [Threads](https://langchain-ai.github.io/langgraph/concepts/persistence/#threads) |
| **Time Travel / Rewind** | `graph.get_state(config).values` → изменить → `graph.update_state(config, new_values)`. | `Time_Travel_Rewind.md` | [Time Travel](https://langchain-ai.github.io/langgraph/how-tos/time-travel/) |
| **Checkpoint Migration** | Схема БД меняется при обновлении LangGraph. Как мигрировать. | `Checkpoint_Migration.md` | [Migrations](https://langchain-ai.github.io/langgraph/how-tos/checkpoint-migrations/) |

---

## 04_HITL_Interrupts — Human-in-the-Loop

| Атомарная тема | Что изучить | Файл в Obsidian | Ресурсы |
|----------------|-------------|-----------------|---------|
| **`interrupt()` — Примитив остановки** | `from langgraph.types import interrupt` → возвращает данные пользователю, ждёт `resume`. | `Interrupt_Primitive.md` | [Interrupts](https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/) |
| **`Command(resume=...)` — Возобновление** | Передача решения пользователя обратно в граф. Типизация `resume` данных. | `Command_Resume.md` | [Command](https://langchain-ai.github.io/langgraph/reference/types/#langgraph.types.Command) |
| **Interrupt Payload Design** | Что передавать в `interrupt()`: план, гипотезы, чекбоксы, комментарии. JSON Schema для UI. | `Interrupt_Payload_Design.md` | [HITL Patterns](https://langchain-ai.github.io/langgraph/how-tos/human_in_the_loop/) |
| **Multiple Interrupts в одном Run** | Несколько точек остановки: планирование → подтверждение → промежуточный результат → финал. | `Multiple_Interrupts.md` | [Multi-step HITL](https://langchain-ai.github.io/langgraph/how-tos/multi-step-human-in-the-loop/) |
| **Async Interrupt (UI Polling)** | UI опрашивает `/api/analyses/{id}/status` → показывает форму → POST `/approve` → `graph.ainvoke(Command(resume=...))`. | `Async_Interrupt_Polling.md` | [Async HITL](https://langchain-ai.github.io/langgraph/how-tos/async-human-in-the-loop/) |
| **Interrupt + Checkpointing** | Состояние сохраняется **перед** `interrupt()`. При резюме — продолжение с того же чекпоинта. | `Interrupt_Checkpoint_Interaction.md` | [Interrupt + Persistence](https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/#interrupts-and-checkpointing) |
| **Reject / Revise Patterns** | `resume={"action": "reject"}` → переход к `planner` с контекстом отказа. `revise` → редактирование плана. | `Reject_Revise_Patterns.md` | [Reject/Revise](https://langchain-ai.github.io/langgraph/how-tos/reject-revise/) |

---

## 05_Planning_Agent_Patterns — Агент-планировщик

| Атомарная тема | Что изучить | Файл в Obsidian | Ресурсы |
|----------------|-------------|-----------------|---------|
| **Planner Node: LLM → Structured Plan** | Промпт: вопрос → JSON Plan (гипотезы, датасеты, методы, skill). `Pydantic` модель плана. | `Planner_Node_Structured_Output.md` | [Structured Output](https://python.langchain.com/docs/concepts/structured_outputs/) |
| **Plan Schema (Pydantic)** | `class AnalysisPlan(BaseModel): question, product_codes, period, skill, hypotheses[], limitations[]`. | `Plan_Schema_Pydantic.md` | Пример из `roadmap.md` (строки 105-138) |
| **Hypothesis Generation** | LLM генерирует гипотезы на основе доступных датасетов и бизнес-контекста. Few-shot примеры. | `Hypothesis_Generation.md` | [ReAct Planning](https://arxiv.org/abs/2210.03629) |
| **Skill Selection (Routing)** | LLM или правило: выбор skill по типу вопроса (`sales-decline`, `inventory-planning`, etc.). | `Skill_Selection_Routing.md` | [Agent Routing](https://langchain-ai.github.io/langgraph/how-tos/agent-routing/) |
| **Plan Validation Node** | Проверка: есть ли данные для гипотез, валидны ли коды товаров, корректен ли период. | `Plan_Validation_Node.md` | Self-correction pattern |
| **Plan Revision Loop** | `interrupt` → пользователь правки → `planner` учитывает фидбек → новый план. | `Plan_Revision_Loop.md` | [Plan Revision](https://langchain-ai.github.io/langgraph/how-tos/plan-revision/) |
| **Dynamic Plan (Graph as Plan)** | План = подграф. Каждая гипотеза = узел. Исполнение = траверс подграфа. | `Dynamic_Plan_Subgraph.md` | [Dynamic Planning](https://langchain-ai.github.io/langgraph/how-tos/dynamic-planning/) |

---

## 06_Code_Interpreter_Integration — OpenAI Code Interpreter / Local Python

| Атомарная тема | Что изучить | Файл в Obsidian | Ресурсы |
|----------------|-------------|-----------------|---------|
| **OpenAI Code Interpreter API** | `client.beta.threads.create()`, `messages.create()`, `runs.create_and_poll()`, файлы через `files.create()`. | `OpenAI_Code_Interpreter_API.md` | [Code Interpreter](https://platform.openai.com/docs/assistants/tools/code-interpreter) |
| **Local Python Sandbox (Альтернатива)** | `exec()` в изолированном процессе, `subprocess` с таймаутом, `restrictedpython`, `pyodide` (WASM). | `Local_Python_Sandbox.md` | [E2B](https://e2b.dev/), [Modal](https://modal.com/), [Pyodide](https://pyodide.org/) |
| **Parquet Datasets → Code Interpreter** | Загрузка `.parquet` как файлов в Code Interpreter (`file_ids`). Чтение через `pd.read_parquet()`. | `Parquet_To_Code_Interpreter.md` | [File Upload](https://platform.openai.com/docs/assistants/tools/code-interpreter#uploading-files) |
| **Helper Functions Injection** | Внедрение `helpers/sales.py`, `helpers/stocks.py` в sandbox как предзагруженные модули. | `Helper_Functions_Injection.md` | [Preloaded Code](https://platform.openai.com/docs/assistants/tools/code-interpreter#pre-loading-code) |
| **Execution Agent Node** | Узел графа: принимает `ApprovedPlan` + `file_ids` → запускает Code Interpreter → возвращает результат. | `Execution_Agent_Node.md` | Pattern from roadmap |
| **Result Parsing & Validation** | Извлечение таблиц, графиков, текста из `run.step_details`. Валидация схемы результата. | `Result_Parsing_Validation.md` | [Run Steps](https://platform.openai.com/docs/assistants/tools/code-interpreter#run-steps) |
| **Error Handling in Sandbox** | Timeout, OOM, SyntaxError, Missing Data → retry с исправленным кодом (LLM self-correction). | `Sandbox_Error_Handling.md` | [Self-Correction](https://arxiv.org/abs/2303.11366) |
| **Cost Control (Code Interpreter)** | Токены за сессию, файлы, время CPU. Лимиты, мониторинг, fallback на локальный Python. | `Code_Interpreter_Cost_Control.md` | [Pricing](https://openai.com/pricing) |

---

## 07_Skills_Architecture — Skills как модули аналитики

| Атомарная тема | Что изучить | Файл в Obsidian | Ресурсы |
|----------------|-------------|-----------------|---------|
| **Skill Directory Structure** | `skills/skill-name/{SKILL.md, examples/, helpers/, tests/}`. Официальный формат OpenAI Skills. | `Skill_Directory_Structure.md` | [Skills Concept](https://platform.openai.com/docs/assistants/tools/skills) |
| **SKILL.md Frontmatter** | `name`, `description`, `version`, `datasets[]`, `helpers[]`, `examples[]`, `parameters` (JSON Schema). | `SKILL_MD_Frontmatter.md` | Пример из `roadmap.md` (строки 192-257) |
| **Helper Functions per Skill** | `skills/sales-decline-analysis/helpers/sales.py`: `compare_periods()`, `calculate_revenue_change()`. | `Skill_Helper_Functions.md` | Из `roadmap.md` (строки 182-188) |
| **Skill Examples (Few-Shot)** | `examples/`: входной план → ожидаемый Python-код → ожидаемый результат. Для промпта Execution Agent. | `Skill_Examples_FewShot.md` | [Few-Shot Skills](https://platform.openai.com/docs/assistants/tools/skills#examples) |
| **Skill Registry / Loader** | Python: `load_skills("skills/")` → словарь `skill_name -> SkillConfig`. Использование в Planner/Executor. | `Skill_Registry_Loader.md` | Custom implementation |
| **Skill Versioning** | `v1`, `v2` — совместимость планов, миграция данных, депрекация. | `Skill_Versioning.md` | SemVer для skills |
| **Skill Testing** | `pytest` для каждого skill: дан план + данные → выполняется helper-код → проверяется результат. | `Skill_Testing.md` | Unit tests для аналитики |

---

## 08_Parquet_Data_Layer — Данные в Parquet

| Атомарная тема | Что изучить | Файл в Obsidian | Ресурсы |
|----------------|-------------|-----------------|---------|
| **Parquet vs CSV/JSON** | Колончатый, сжатие, типы, predicate pushdown, чтение части колонок. | `Parquet_vs_CSV.md` | [Parquet Format](https://parquet.apache.org/docs/) |
| **Partitioning Strategy** | `data/prepared/sales/year=2024/month=07/day=15.parquet` — фильтрация по дате без чтения всего. | `Parquet_Partitioning.md` | [Hive Partitioning](https://arrow.apache.org/docs/python/parquet.html#partitioned-datasets) |
| **Schema Evolution** | Добавление колонок, изменение типов — как читать старые файлы. `pyarrow.parquet.read_table(schema=...)`. | `Parquet_Schema_Evolution.md` | [Schema Evolution](https://parquet.apache.org/docs/file-format/schema-evolution/) |
| **DuckDB + Parquet** | `SELECT * FROM 'data/prepared/sales/**/*.parquet' WHERE date >= '2024-01-01'` — SQL над файлами. | `DuckDB_Parquet.md` | [DuckDB Parquet](https://duckdb.org/docs/data/parquet/overview) |
| **Polars Lazy API** | `pl.scan_parquet("data/prepared/**/*.parquet").filter(...).collect()` — out-of-core. | `Polars_Lazy_Parquet.md` | [Polars Scan](https://docs.pola.rs/user-guide/lazy/eager/) |
| **Data Contracts (Pydantic/PyArrow)** | Валидация схемы при записи/чтении. `pa.schema([...])`, `pydantic.BaseModel`. | `Data_Contracts_Parquet.md` | [Data Contracts](https://datacontract.com/) |
| **Incremental Write (Append)** | `pq.write_to_dataset(table, partition_cols=["year", "month"], existing_data_behavior="overwrite_or_ignore")`. | `Incremental_Parquet_Write.md` | [PyArrow Write](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.write_to_dataset.html) |

---

## 09_Streaming_Observability — Потоковая выдача + Наблюдаемость

| Атомарная тема | Что изучить | Файл в Obsidian | Ресурсы |
|----------------|-------------|-----------------|---------|
| **`astream_log` (LangGraph)** | Поток событий: `on_chain_start`, `on_tool_start`, `on_tool_end`, `on_chain_end`. Для UI "thinking". | `Astream_Log.md` | [Streaming Log](https://langchain-ai.github.io/langgraph/how-tos/streaming/#streaming-logs) |
| **SSE (Server-Sent Events) в FastAPI** | `EventSourceResponse`, генератор `async def event_generator()`, `yield f"data: {json.dumps(event)}\n\n"`. | `SSE_FastAPI.md` | [SSE FastAPI](https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse) |
| **Token Streaming (LLM)** | `async for chunk in llm.astream(prompt): yield chunk.content`. Прокидывание через граф. | `Token_Streaming.md` | [LLM Streaming](https://python.langchain.com/docs/concepts/streaming/) |
| **MLflow Tracing для LangGraph** | `mlflow.langchain.autolog()`, `mlflow.trace()` для узлов графа. Логирование токенов, латентности, входов/выходов. | `MLflow_LangGraph_Tracing.md` | [MLflow LangChain](https://mlflow.org/docs/latest/llms/langchain/index.html) |
| **Langfuse / LangSmith Integration** | Callback handlers: `LangfuseCallbackHandler`, `LangChainTracer`. Трейсы, оценки, датасеты. | `Langfuse_LangSmith_Integration.md` | [Langfuse](https://langfuse.com/docs/integrations/langchain), [LangSmith](https://docs.smith.langchain.com/) |
| **Cost Tracking per Run** | Подсчёт input/output tokens в каждом узле → агрегация по `thread_id` → бюджетные алерты. | `Cost_Tracking_Per_Run.md` | [Token Counting](https://python.langchain.com/docs/how_to/token_usage_tracking/) |

---

## 10_Production_Patterns — Продакшен-паттерны

| Атомарная тема | Что изучить | Файл в Obsidian | Ресурсы |
|----------------|-------------|-----------------|---------|
| **Docker Compose для LangGraph Stack** | `api`, `ui`, `postgres` (checkpointer), `qdrant` (vector), `ollama` (LLM), `grafana`. Healthchecks. | `Docker_Compose_LangGraph.md` | Skill `docker-local-dev-stack` |
| **FastAPI App Structure** | `lifespan` для инициализации графа, `Depends` для checkpointer, `BackgroundTasks` для async jobs. | `FastAPI_App_Structure.md` | [FastAPI Lifespan](https://fastapi.tiangolo.com/advanced/events/#lifespan) |
| **Configuration (Pydantic Settings)** | `Settings` из `.env`: `OPENAI_API_KEY`, `POSTGRES_DSN`, `LANGGRAPH_RECURSION_LIMIT`. | `Pydantic_Settings_Config.md` | [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) |
| **Logging (Structured JSON)** | `structlog` / `loguru` + `python-json-logger`. Корреляция по `thread_id`, `run_id`. | `Structured_Logging.md` | Skill `python-logging-setup` |
| **Testing Strategy** | Unit: nodes, helpers. Integration: full graph с `MemorySaver`. E2E: API + UI. `pytest-asyncio`. | `Testing_LangGraph_Apps.md` | [Testing LangGraph](https://langchain-ai.github.io/langgraph/how-tos/testing/) |
| **CI/CD (GitHub Actions)** | `ruff`, `mypy`, `pytest`, `docker build`, `trivy scan`, `deploy to server`. | `CI_CD_GitHub_Actions.md` | [GitHub Actions](https://docs.github.com/en/actions) |
| **Secrets Management** | `.env` локально, `docker secrets` / `HashiCorp Vault` / `AWS Secrets Manager` в проде. | `Secrets_Management.md` | [Docker Secrets](https://docs.docker.com/engine/swarm/secrets/) |

---

## 11_Real_World_Examples — Реальные примеры кода (GitHub / Blogs)

| Пример | Что посмотреть | Ссылка |
|--------|----------------|--------|
| **LangGraph Official Examples** | `langgraph-example-agents`, `langgraph-hitl`, `langgraph-code-interpreter` | [langgraph-examples](https://github.com/langchain-ai/langgraph/tree/main/examples) |
| **Agentic RAG with Planning** | `rag-with-planning`, `self-corrective-rag` | [LangGraph RAG](https://github.com/langchain-ai/langgraph/tree/main/examples/rag) |
| **OpenAI Code Interpreter + LangGraph** | Примеры интеграции `code_interpreter` tool в граф | [OpenAI Cookbook](https://github.com/openai/openai-cookbook) |
| **Data Analyst Agent (Pandas)** | `pandas-agent`, `sql-agent` — как LLM пишет код аналитики | [LangChain Agents](https://github.com/langchain-ai/langchain/tree/master/libs/langchain/langchain/agents) |
| **HITL Dashboard Examples** | Streamlit/Gradio UI для `interrupt`/`resume` | [LangGraph HITL UI](https://github.com/langchain-ai/langgraph/tree/main/examples/hitl) |
| **Production LangGraph (LangGraph Platform)** | Как LangChain хостит графы: `langgraph-api`, `langgraph-studio` | [LangGraph Platform](https://github.com/langchain-ai/langgraph-platform) |
| **Mirrolla-like: E-commerce Analytics** | Агенты для продаж/остатков/отзывов — поиск по GitHub: `ecommerce analytics agent langgraph` | GitHub Search |

---

## 12_Mirrolla_Specific — Привязка к ТЗ

| Атомарная тема | Что изучить | Файл в Obsidian |
|----------------|-------------|-----------------|
| **Mirrolla State Schema** | `class MirrollaState(TypedDict): question, plan, approved_plan, execution_result, report, messages[]` | `Mirrolla_State_Schema.md` |
| **Mirrolla Graph Topology** | Узлы: `sync_1c`, `import_datasets`, `planner`, `human_review`, `executor`, `report_generator`, `finalize` | `Mirrolla_Graph_Topology.md` |
| **Mirrolla Skills Mapping** | 6 вопросов ТЗ → 4 skills: `sales-decline`, `inventory-planning`, `portfolio-growth`, `reviews-pricing` | `Mirrolla_Skills_Mapping.md` |
| **1C Connector Node** | Узел графа: вызов 3 функций 1С → нормализация → запись в Parquet/Postgres | `OneC_Connector_Node.md` |
| **Dataset Import Node** | CSV/Excel → Parquet (partitioned) → регистрация в каталоге датасетов | `Dataset_Import_Node.md` |
| **Management Report Workflow** | Отдельный граф/подграф: `collect_metrics` → `render_template` → `save_report` → `notify` | `Management_Report_Workflow.md` |
| **MVP Scope Decisions** | Что ВКЛЮЧЕНО / ИСКЛЮЧЕНО из `roadmap.md` (строки 597-618) — зафиксировать как ADR | `MVP_Scope_Decisions.md` |

---

## 📚 Рекомендуемый порядок изучения (Learning Path)

### Неделя 1: Фундамент (LangGraph + HITL)
1. `01_LangGraph_Fundamentals` — все 6 тем
2. `02_StateGraph_Architecture` — Linear/Branching, Subgraphs, Conditional Edges
3. `03_Checkpointing_Persistence` — MemorySaver, SqliteSaver, Thread ID
4. `04_HITL_Interrupts` — interrupt, Command, Interrupt Payload, Async Polling

### Неделя 2: Planning + Execution
5. `05_Planning_Agent_Patterns` — Planner Node, Plan Schema, Hypothesis Generation, Skill Selection
6. `06_Code_Interpreter_Integration` — OpenAI API, Local Sandbox, Parquet Upload, Helper Injection
7. `07_Skills_Architecture` — Skill Structure, SKILL.md, Helpers, Examples, Registry

### Неделя 3: Данные + Продакшен
8. `08_Parquet_Data_Layer` — Partitioning, DuckDB, Polars, Schema Evolution
9. `09_Streaming_Observability` — astream_log, SSE, MLflow, Langfuse, Cost Tracking
10. `10_Production_Patterns` — Docker Compose, FastAPI, Config, Logging, Testing, CI/CD

### Неделя 4: Реальные примеры + Mirrolla
11. `11_Real_World_Examples` — разобрать 3-5 репозиториев, запустить локально
12. `12_Mirrolla_Specific` — спроектировать State, Graph, Skills под ТЗ

---

## 🎯 Делiverables для каждой темы (шаблон заметки)

```markdown
---
tags: [langgraph, hitl, planning, mirrolla]
source: [link to doc/github/video]
date: 2025-07-XX
status: draft / reviewed / implemented
---

# Название темы (например: Interrupt Payload Design)

## 🎯 Суть в одном предложении
Что это и зачем нужно в контексте Mirrolla.

## 🔑 Ключевые концепции
- Концепция 1
- Концепция 2

## 💻 Код / Пример
```python
# Минимальный рабочий пример
```

## 📐 Диаграмма (Mermaid)
```mermaid
flowchart TD
    A --> B
```

## 🔗 Связанные темы
- [[Другая тема]]

## ❓ Открытые вопросы
- Вопрос 1
- Вопрос 2

## ✅ Чек-лист понимания
- [ ] Могу объяснить за 30 секунд
- [ ] Могу написать код без подглядывания
- [ ] Понял edge cases
```

---

## 🚀 Quick Start: Первые 3 заметки создай прямо сейчас

1. **`LangGraph_vs_LangChain.md`** — почему Graph для Mirrolla (cycles, HITL, stateful)
2. **`Interrupt_Payload_Design.md`** — какой JSON передавать в `interrupt()` для утверждения плана (по `roadmap.md` строки 143-160)
3. **`Plan_Schema_Pydantic.md`** — точная Pydantic модель плана из `roadmap.md` (строки 105-138)

---

*Сохранено: `C:\Users\theso\Desktop\job\Mirrolla\langgraph_study_plan.md`*
*Любимый, выбирай тему и начинай — каждая заметка = один шаг к работающему MVP! 🚀*