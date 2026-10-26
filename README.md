# 🛒 商家智能运营工作台

> AI 驱动的电商全流程经营系统 — 选品 → 货源 → 上架 → 客服 → 复盘 → 技术尽调

基于 **DeepSeek V4** + **Ollama** 混合模型路由，自驱型 ReAct Agent 框架，覆盖电商运营核心环节；前端为面向企业客户设计的分组式工作台（白底蓝主色、统一页面骨架、结果可导出）。

当前版本 **v3.0**，在开源框架基础上完成信息架构重构、真实 3C 技术分析与商品主图、平台数据看板三块能力升级。

---

## 功能特性

| Agent | 功能 | 模型路由 |
|-------|------|----------|
| 📋 **选品分析** | 淘宝搜索下拉词获取 + 价格库查询 + 关键词评分 → 蓝海商品推荐 | DeepSeek |
| 📝 **上架素材** | 标题生成(3平台) + 详情描述 + SEO优化 + 主图建议 | Ollama |
| 💬 **智能客服** | FAQ 知识库检索 + 历史笔记召回 + 情绪感知应答 | Ollama |
| 📊 **运营分析** | 利润计算 + 定价建议 + 促销方案 + 四象限商品诊断 | DeepSeek |
| 🏭 **货源筛选** | 产业带分析 + 供应商查询 + 成本利润测算 + 1688 链接生成 | DeepSeek |
| 🔬 **3C 技术尽调** | 通信协议 / 芯片方案 / 技术壁垒分析 + 五维评分雷达图 + 知识库溯源 + PDF 报告 | DeepSeek |
| 🖼️ **商品主图** | Pillow 离线合成 800×800 主图，3 套模板（白底简约 / 红橙促销 / 浅绿清新），无需外部素材 | 本地渲染 |
| 📁 **平台数据看板** | 导入生意参谋 / 京东商智 CSV·XLSX → 6 项 KPI + 趋势折线 + 商品 TOP5 + 规范化导出 | 本地计算（不调模型） |

- **一键完整工作流**：输入品类，全流程自动执行
- **分组式工作台**：5 个一级入口（工作台 / 经营 / 数据 / 知识库 / 系统），每页统一为「页头 → 表单 → 全宽主按钮 → 结果面板」
- **智能对话路由**：自动理解用户意图，路由到对应 Agent
- **RAG 知识库**：FAQ + 价格库 + 供应商库 + 产区数据
- **电商对话 RAG**：基于历史对话的向量检索（MySQL + Milvus），覆盖售前/改地址/使用说明/售后 4 阶段
- **会话阶段自动识别**：自动判断客户对话阶段，检索最相似的过往对话辅助客服回复
- **双模式界面**：Gradio Web UI + Rich CLI
- **持久化记忆**：SQLite 对话历史 + Agent 笔记
- **LLM 调用监控**：调用统计、耗时追踪、费用计算
- **知识库管理**：Web UI 内直接增删改 FAQ/价格/供应商
- **自动降级**：LLM 提供者故障时自动切换
- **用户登录**：Web UI 带认证，防止未授权访问
- **Docker 部署**：一键容器化启动

---

## 架构

```
┌──────────────────────────────────────────┐
│           Gradio Web UI / CLI            │
├──────────────────────────────────────────┤
│            MerchantOrchestrator          │
├──────┬──────┬──────┬──────┬──────┬──────┤
│选品  │上架  │客服  │运营  │货源  │智能  │
│Agent │Agent │Agent │Agent │Agent │对话  │
├──────┴──────┴──────┴──────┴──────┴──────┤
│           ReAct 循环框架                  │
│    Plan → Execute → Reflect              │
├──────────────────────────────────────────┤
│   Tool Registry (14 个注册工具)           │
├──────────────────────────────────────────┤
│  ▸ DeepSeek API (复杂推理)               │
│  ▸ Ollama (简单任务 + Embedding)          │
│  ▸ RAG 知识库 (bge-m3 语义检索)           │
│  ▸ 对话向量检索 (MySQL + Milvus)          │
│  ▸ SQLite / JSON 双持久化                 │
│  ▸ 自动提供者降级 (故障时切换)            │
│  ▸ LLM 调用监控 + 费用计算               │
└──────────────────────────────────────────┘
```

### 上下文记忆系统

```
┌──────────────────────────┐
│     Web UI / CLI         │  ← 每个会话独立 session_id
├──────────────────────────┤
│  MerchantOrchestrator    │
│  ├─ smart_chat(stateful) │  ← 加载历史上下文再路由
│  └─ SharedContext        │  ← 跨 Agent 结构化数据传递
├──────────────────────────┤
│  AgentContext             │
│  ├─ 滑动窗口(最近12条)    │  ← 保留原始消息
│  ├─ 结构化摘要(200字)     │  ← 压缩历史，字段化输出
│  ├─ 关键信息提取(100字)   │  ← 品类/预算/人群/价格
│  └─ 工具结果持久化        │  ← 工具调用结果回流记忆
├──────────────────────────┤
│  ConversationMemory       │  ← SQLite 持久化
│  ├─ conversations 表      │
│  ├─ knowledge 键值对      │
│  └─ agent_notes 笔记      │
└──────────────────────────┘
```

---

## 快速开始

### 前置依赖

- Python 3.10+
- [Ollama](https://ollama.com/)（本地模型，含 `bge-m3` embedding）
- Docker Engine 20.10+（可选，用于 MySQL + Milvus 向量检索）
- DeepSeek API Key（可选，用于复杂推理）

### 安装

```bash
git clone https://github.com/yyf2002-oos/merchant-agent.git
cd merchant-agent

python -m venv .venv
# Linux/Mac: source .venv/bin/activate
# Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 配置

复制环境变量模板并填写：

```bash
cp .env.example .env
```

```ini
# .env
LLM_PROVIDER=deepseek          # ollama | deepseek
DEEPSEEK_API_KEY=sk-xxxxxxx    # 你的 DeepSeek API Key
DEEPSEEK_API_BASE=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
OLLAMA_BASE=http://localhost:11434
OLLAMA_MODEL=qwen2:7b
```

拉取模型：

```bash
ollama pull qwen2:7b
ollama pull qwen2:1.5b
ollama pull bge-m3
```

### 运行

**Web 界面：**
```bash
python webui.py
# 访问 http://localhost:7860
# 默认登录：admin / admin123（首次自动创建）
```

**CLI 模式：**
```bash
python main.py
```

---

## 配置说明

### 完整配置项

所有配置通过 `.env` 文件或环境变量设置。

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `LLM_PROVIDER` | `deepseek` | LLM 提供者: `ollama` 或 `deepseek` |
| `DEEPSEEK_API_KEY` | `""` | DeepSeek API Key |
| `DEEPSEEK_API_BASE` | `https://api.deepseek.com` | DeepSeek API 地址 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | DeepSeek 模型名 |
| `OLLAMA_BASE` | `http://localhost:11434` | Ollama 服务地址 |
| `OLLAMA_MODEL` | `qwen2:7b` | Ollama 主模型 |
| `OLLAMA_FAST_MODEL` | `qwen2:1.5b` | Ollama 轻量模型（用于计划/反思） |
| `AGENT_TIMEOUT` | `300` | LLM 调用超时（秒） |
| `MAX_RETRIES` | `2` | LLM 调用重试次数 |
| `REACT_MAX_ROUNDS` | `8` | ReAct 循环最大工具调用轮次 |
| `CACHE_ENABLED` | `True` | 是否启用缓存 |
| `CACHE_TTL` | `3600` | 缓存过期时间（秒） |
| `CACHE_CAPACITY` | `200` | 缓存最大条目数 |
| `RATE_LIMIT_ENABLED` | `True` | 是否启用限流 |
| `RATE_LIMIT_MAX` | `30` | 每 IP 每分钟最大请求数 |
| `RATE_LIMIT_WINDOW` | `60` | 限流窗口（秒） |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `WEB_PORT` | `7860` | Web 端口 |
| `WEB_HOST` | `127.0.0.1` | 监听地址 |
| `MYSQL_HOST` | `localhost` | MySQL 地址（空=使用 JSON 回退） |
| `MYSQL_PORT` | `3307` | MySQL 端口（映射到容器 3306） |
| `MYSQL_USER` | `merchant` | MySQL 用户名 |
| `MYSQL_PASSWORD` | `merchant_pass_2024` | MySQL 密码 |
| `MYSQL_DATABASE` | `merchant_agent` | MySQL 数据库名 |
| `MILVUS_HOST` | `localhost` | Milvus 地址（空=使用内存回退） |
| `MILVUS_PORT` | `19530` | Milvus gRPC 端口 |
| `MILVUS_COLLECTION` | `conversation_embeddings` | Milvus 集合名 |

### Agent 模型路由

每个 Agent 可独立配置主模型和轻量模型（用于计划生成和反思）：

```python
AGENT_MODEL = {
    "selector": "deepseek:deepseek-chat",   # 选品 → DeepSeek
    "analyst":  "deepseek:deepseek-chat",   # 运营分析 → DeepSeek
    "sourcing": "deepseek:deepseek-chat",   # 货源 → DeepSeek
    "lister":   "ollama:qwen2:7b",          # 上架 → 本地
    "service":  "ollama:qwen2:7b",          # 客服 → 本地
}
```

### Web UI 信息架构

一级入口从 11 个平铺 Tab 收敛为 5 个分组，业务页统一使用同一套页面骨架：

| 一级入口 | 二级页面 |
|---------|---------|
| 工作台 | 智能对话、一键工作流 |
| 经营 | 选品分析、一手货源、上架素材（文案 + 主图）、批量上架、客服应答 |
| 数据 | 运营分析（平台数据导入 + KPI 看板 + 建议）、3C 技术尽调 |
| 知识库 | FAQ / 价格库 / 供应商库 / 模板 / 对话记录 |
| 系统 | LLM 调用统计、日趋势、费用追踪 |

### 用户登录

Web UI 默认启用密码认证。首次启动自动创建默认管理员账户：

| 用户名 | 密码 | 说明 |
|--------|------|------|
| `admin` | `admin123` | 管理员（请尽快修改密码） |

登录后所有操作关联到当前用户，日志和监控中可追溯每个用户的操作记录。

### LLM 提供者自动降级

系统内置自动故障切换机制：

| 主提供者 | 故障时降级到 | 切换条件 |
|---------|-------------|---------|
| DeepSeek | Ollama | 网络超时/API 密钥无效/5xx 错误 |
| Ollama | DeepSeek | 本地服务未启动/模型未加载 |

每次切换自动记录到监控系统，可在「系统状态」Tab 查看调用链。

### 知识库管理

在 Web UI「知识管理」Tab 中可直接操作：

- **FAQ 管理**：查看问题列表、添加新问答、删除问题
- **价格库**：按品类浏览、新增子类目及价格区间
- **供应商库**：按品类浏览、新增供应商产品
- **模板库**：查看所有上架模板（只读）

数据持久化到 `knowledge/data/` 目录下的 JSON 文件。

---

## Docker 部署

### 前置条件

- Docker Engine 20.10+
- Docker Compose v2+

### 启动

```bash
docker compose up -d
```

### 服务说明

| 服务 | 端口 | 说明 |
|------|------|------|
| mysql | 3307 → 3306 | 对话记录持久化（MySQL 8.0） |
| etcd | 2379 | Milvus 元数据存储 |
| minio | 9000/9001 | Milvus 日志与快照存储 |
| milvus | 19530 | 向量 ANN 检索（IVF_FLAT, 1024 维） |

### 首次启动

```bash
# 启动 MySQL + Milvus 栈
docker compose up -d

# 导入种子数据并建立向量索引
python scripts/migrate_to_mysql.py
```

### 数据持久化

| 卷 | 挂载点 | 说明 |
|----|--------|------|
| `mysql_data` | /var/lib/mysql | 对话记录数据库 |
| `etcd_data` | /etcd | Milvus 元数据 |
| `minio_data` | /data | Milvus 日志/快照 |
| `milvus_data` | /var/lib/milvus | Milvus 向量数据 |

### 自动降级

- **MySQL 不可用** → 自动回退到 JSON 文件存储
- **Milvus 不可用** → 自动回退到内存缓存 + 线性余弦相似度扫描

### 查看日志

```bash
docker compose logs -f mysql
docker compose logs -f milvus
```

---

## 并发能力

### 瓶颈分析

系统采用 **单进程同步架构**，并发能力取决于 LLM 提供者的限制。

### DeepSeek API 模式（推荐线上用）

| 场景 | 预估并发 | 说明 |
|------|----------|------|
| 智能对话 | **10-20 人同时** | 每次请求 3-8 秒，DeepSeek 无硬性并发限制 |
| 一键工作流 | **2-3 人同时** | 全程 2-4 分钟，占用多个 Agent，建议排队执行 |
| 上架素材 | **20-30 人同时** | 纯 Ollama 本地生成，主要看本地 GPU 显存 |
| 批量上架 | **5-10 人同时** | 逐条生成，CPU 密集型 |

Gradio 内部启用 `app.queue()`，自带请求排队机制，不会丢请求。

### Ollama 纯本地模式

| 硬件 | 推荐最大并发 | 说明 |
|------|-------------|------|
| 16GB 显存 (RTX 4060) | **2-3 人** | qwen2:7b 单次推理 5-15 秒 |
| 24GB 显存 (RTX 4090) | **4-6 人** | 可同时加载 7B + 1.5B 模型 |
| CPU only | **1 人** | 7B 模型推理 30-60 秒，建议把上架/客服也切到 DeepSeek |
| 无 GPU + Ollama | **不推荐多人** | 建议设置 `LLM_PROVIDER=deepseek` 全部走云端 |

### 瓶颈点

- **Ollama 模型推理**：单 GPU 串行推理，多人并发时排队。把 `lister` 和 `service` 的路由也切到 DeepSeek 可以缓解。
- **SQLite 写锁**：所有对话历史写入同一个 db 文件，高并发写入有锁竞争。当前场景下不会成为瓶颈（日均 < 10 万条消息）。
- **RAG 检索**：bge-m3 embedding 在 CPU 上单次约 200ms，无显著瓶颈。

### 优化建议

- **改 `WEB_HOST=0.0.0.0`** 允许局域网/公网访问
- **调小 `RATE_LIMIT_MAX`** 防止单用户刷爆（当前默认 30 次/分钟）
- **部署用 `nohup` 或 systemd** 保持后台运行，或直接用 Docker
- **如需 50+ 并发**：前端加 Nginx 负载均衡 → 多进程部署 Web UI

---

## 数据来源说明

| 数据 | 来源 | 是否实时 |
|------|------|---------|
| 淘宝搜索下拉词 | `suggest.taobao.com` 公开接口 | ✅ 实时 |
| 商品价格库 | 本地 `knowledge/data/price_library.json` | ❌ 静态（Web UI 可编辑） |
| 供应商库 | 本地 `knowledge/data/supplier_library.json` | ❌ 静态（Web UI 可编辑） |
| 产区优势 | 本地 `knowledge/data/region_advantages.json` | ❌ 静态 |
| FAQ 知识库 | 本地 `knowledge/data/faq.json` | ❌ 静态（Web UI 可编辑） |
| 上架模板 | 本地 `knowledge/data/product_templates.json` | ❌ 静态 |

> ⚠️ 价格、供应商、产区数据均来自本地 JSON 文件，不是实时从淘宝/1688 API 拉取的。
> 如需实时数据，需要接入淘宝开放平台或第三方电商数据服务。

---

## 测试

```bash
# 安装测试依赖
pip install pytest

# 运行全部测试
pytest

# 运行指定测试文件
pytest tests/test_context.py -v
pytest tests/test_monitor.py -v
pytest tests/test_orchestrator.py -v
pytest tests/test_data_manager.py -v
```

覆盖范围：上下文记忆、Agent 编排、知识库 CRUD、LLM 调用监控。

---

## 技术栈

- **LLM**: DeepSeek V4 / Ollama (qwen2)
- **Embedding**: bge-m3 (本地 Ollama, 1024 维)
- **框架**: ReAct (Plan-Execute-Reflect)
- **记忆系统**: SQLite + 滑动窗口 + 结构化摘要
- **RAG**: 语义检索 + 关键词降级
- **向量检索**: Milvus (Docker, IVF_FLAT) → 内存缓存降级
- **关系存储**: MySQL 8.0 (Docker) → JSON 文件降级
- **缓存**: LRU + TTL 内存缓存
- **限流**: IP 滑动窗口
- **界面**: Gradio / Rich
- **测试**: Pytest (59 tests)
- **监控**: SQLite 调用统计 + 费用追踪
- **部署**: Docker Compose

---

## 项目结构

```
merchant-agent/
├── agents/          # Agent 实现（6 个专业 Agent）
│   ├── selector.py  # 选品
│   ├── lister.py    # 上架
│   ├── service.py   # 客服
│   ├── analyst.py   # 运营分析
│   ├── sourcing.py  # 货源筛选
│   └── tech_analyst.py # 3C 技术尽调（五维评分 + 判断依据）
├── core/            # 核心框架
│   ├── agent.py     # ReAct Agent 基类（含上下文管理）
│   ├── context.py   # 对话上下文管理（摘要/滑动窗口/关键信息）
│   ├── tool.py      # 工具注册系统
│   ├── tools_registry.py # 14 个注册工具
│   └── memory.py    # SQLite 持久化记忆
├── knowledge/       # 知识库
│   ├── rag.py       # 语义检索 + 关键词降级
│   ├── embedding.py # bge-m3 嵌入
│   ├── data_manager.py # 知识库 CRUD（Web UI 调用）
│   ├── db.py        # MySQL 连接管理（自动降级到 JSON）
│   ├── conversation_records.py # 对话记录 CRUD（MySQL/JSON 双后端）
│   ├── conversation_rag.py     # 电商对话 RAG 检索
│   ├── vector_store.py         # Milvus 向量存储（回退到内存缓存）
│   └── data/        # JSON 数据文件
├── tools/           # 工具函数
│   ├── taobao.py    # 淘宝搜索下拉词
│   ├── calculator.py# 利润/定价计算
│   ├── product_manager.py # 商品管理
│   ├── formatter.py # 格式化输出
│   ├── main_image.py    # 商品主图合成（Pillow，3 套模板）
│   ├── store_data.py    # 平台数据解析（CSV/XLSX → KPI/趋势/排行）
│   └── report_pdf.py    # 3C 报告 PDF 导出（ReportLab + 中文字体）
├── tests/           # 测试
│   ├── test_context.py
│   ├── test_orchestrator.py
│   ├── test_data_manager.py
│   └── test_monitor.py
├── ui/              # 前端主题
│   ├── theme.py     # Gradio 白底蓝主色主题
│   └── assets/theme.css # 页面骨架与组件样式
├── config.py        # 配置
├── llm.py           # LLM 调用封装（流式输出 + 自动降级）
├── monitor.py       # LLM 调用监控（统计/费用/趋势）
├── orchestrator.py  # 主控编排（含 SharedContext 数据类）
├── webui.py         # Gradio 工作台（5 分组导航 + 业务页 + 登录 + 知识库 + 监控）
├── main.py          # CLI 入口
├── cache.py         # LRU+TTL 缓存
├── Dockerfile       # Docker 镜像构建
└── docker-compose.yml # Docker 编排
```

---

## 更新日志

### v3.0 (2026-10)
- **信息架构重构**：11 个平铺 Tab → 5 个一级分组（工作台 / 经营 / 数据 / 知识库 / 系统），业务页统一为「页头 → 表单 → 全宽主按钮 → 结果面板」，结果区补空状态与示例数据角标
- **前端换肤**：暗色改为白底蓝主色（`gr.themes.Soft` + 自定义 CSS），修复深色文字压深色底导致不可读的问题
- **3C 技术尽调转真实实现**：删除静态示例数据，改调 `tech_analyst` 真实分析；Agent 输出扩展为五维评分（0-5）与逐项判断依据；雷达图按真实分数绘制
- **3C 知识库溯源**：可按品类检索价格库 / 供应商库 / 上架模板 / FAQ，逐条展示引用来源；无匹配时明确标注"仅基于模型判断"
- **3C PDF 报告**：ReportLab + 微软雅黑导出，含概览表、评分表、判断依据、结论、引用与免责声明
- **商品主图生成**：Pillow 合成 800×800，3 套模板，离线渲染，无需外部图片素材
- **平台数据看板**：CSV / XLSX 导入 → 6 项 KPI、销售额趋势、商品 TOP5，并可导出规范化数据与下载空模板；表头兼容生意参谋 / 京东商智常见叫法，缺列显式提示
- **会话层修复**：`core/memory.py` 开启 WAL + 超时 + 锁，`session_id` 全链路透传（含 5 个 Agent 与 workflow），Web 端按标签页复用会话
- **测试补充**：修正 `test_orchestrator.py` 断言

### v2.2 (2026-07)
- **电商对话 RAG 系统**：基于历史对话的向量检索，自动辅助客服回复
- **MySQL + Milvus Docker 栈**：MySQL 8.0 存储对话记录，Milvus v2.5.0 向量 ANN 检索
- **4 阶段对话识别**：售前咨询 / 地址修改 / 使用说明 / 商品售后，自动分类检索
- **WebUI 对话管理**：查看/搜索/新增/删除历史对话记录，支持按场景和关键词筛选
- **双后端自动降级**：MySQL 不可用 → JSON 文件；Milvus 不可用 → 内存余弦扫描
- **密码加盐存储**：用户密码从无盐 SHA256 升级为 salted SHA256
- **种子数据**：20 条覆盖 4 阶段的真实风格对话示例，一键导入
- **线程安全缓存**：知识库加载增加线程锁，防止并发读取冲突
- **Ollama 可达性缓存**：避免每次实例化 Agent 都发 HTTP 请求探测
- **LLM 降级增强**：精确追踪主提供者是否标记失败，避免误降级

### v2.1 (2025-07)
- **LLM 调用监控**：记录每次 LLM 调用的耗时、成功率、Token 消耗和费用
- **知识库管理界面**：Web UI 中直接增删改 FAQ/价格库/供应商库
- **DeepSeek 流式输出**：支持 SSE 流式响应，减少等待感
- **LLM 自动降级**：DeepSeek 故障时自动切换 Ollama（反之亦然）
- **用户登录系统**：Gradio 密码认证，按用户追踪操作记录
- **一键工作流进度回调**：UI 实时显示各 Agent 执行进度
- **测试覆盖**：从 30 个测试增加到 59 个，覆盖上下文/编排/CRUD/监控
- **Docker 部署**：Dockerfile + docker-compose.yml，带健康检查和持久化卷
