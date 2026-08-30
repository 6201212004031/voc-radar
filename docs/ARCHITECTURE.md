# VOC Radar 评论雷达 — 系统架构设计

> 版本：v1.0 | 架构师：高见远（Gao） | 日期：2026-07-29
> 适用范围：AI+跨境黑客松巅峰赛初赛原型
> 关联文档：`PRD.md`、`初赛方案_VOC_Radar_v4_最终版.md`

> ⚠️ **模型调度口径说明（2026-08-30 补注）**：本文件为 v1.0 初赛架构记录，正文中的
> 「R1 根因归因」「DeepSeek-R1（Top 5 归因）」等表述是**当时的原始设计**；实际实现已按
> 2026-08-29 的 Top5 全样本对比实验调整——根因归因主力为 `qwen3.7-max`（配置项
> `ATTRIBUTION_MODEL`），`deepseek-r1` 降为可选补充通道。当前口径以
> 《复赛提交_VOC_Radar说明文档》第 2.1 节与 `docs/PRD.md`（v1.1）为准，本文件保留历史
> 表述作为设计演进痕迹。

---

## 一、实现方案与框架选型

### 1.1 整体架构概览

VOC Radar 采用**前后端分离的单体应用**架构，原型阶段不引入微服务/消息队列等复杂度，确保可演示且开发周期可控。核心是后端一条**多阶段 Prompt 链 Pipeline**，前端为单页交互式决策看板。

```
┌──────────────────────────────────────────────────────────────────┐
│                     用户（跨境卖家）                              │
└─────────────────────────┬────────────────────────────────────────┘
                          │ 浏览器
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│  前端：单页 HTML + Chart.js（深色主题交互式决策看板）              │
│  - 痛点热力图 / 优先级矩阵 / 痛点下钻面板 / 报告导出按钮          │
└─────────────────────────┬────────────────────────────────────────┘
                          │ HTTP / JSON / SSE（进度流）
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│  后端：Python + FastAPI                                          │
│  ┌─────────────┐  ┌─────────────────────────────────────────┐    │
│  │  API 路由层  │  │  Pipeline 编排层（多阶段 Prompt 链）     │    │
│  │  /analyze    │  │  Step1 采集 → Step2 预处理 →            │    │
│  │  /reports    │  │  Step3 聚类 → Step4 标签+分级 →         │    │
│  │  /reviews    │  │  Step5 R1 归因 → Step6 建议生成 →       │    │
│  │  /export     │  │  Step7 报告整合                          │    │
│  └─────────────┘  └─────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │  服务层：Model Router 客户端 / 聚类服务 / 数据采集服务   │     │
│  └─────────────────────────────────────────────────────────┘     │
│  ┌──────────────────────┐  ┌──────────────────────────────┐     │
│  │  SQLite 持久化层      │  │  .env 配置（API Key/Base URL）│     │
│  └──────────────────────┘  └──────────────────────────────┘     │
└─────────────────────────┬────────────────────────────────────────┘
                          │ HTTPS
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│  阿里云百炼 Model Router API（OpenAI 兼容格式）                   │
│  - text-embedding-v4（向量化）                                    │
│  - qwen3.7-max（标签/建议/分级判断）                              │
│  - DeepSeek-R1（Top 5 痛点根因归因）                              │
│  - qwen3-vl-plus（P1：图片缺陷识别）                              │
│  - qwen3.5-flash（P1：刷评初判，原型可选）                        │
└──────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│  数据源：Kaggle Amazon Review 数据集（主） / Rainforest API（备） │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 技术栈确认

| 层 | 技术 | 版本/说明 | 选型理由 |
|----|------|----------|---------|
| 后端语言 | Python | 3.11+ | AI 生态成熟，开发效率高 |
| Web 框架 | FastAPI | 0.110+ | 原生异步、SSE 支持进度流、自动 OpenAPI 文档 |
| ASGI 服务器 | Uvicorn | 0.27+ | FastAPI 标配 |
| 数据库 | SQLite | 内置 | 原型零配置，单文件便于演示和迁移 |
| ORM | SQLAlchemy | 2.0+ | 表达力强，支持同步/异步 |
| 聚类 | scikit-learn | 1.4+ | K-Means 内置，稳定可靠 |
| 向量化 | text-embedding-v4 | 百炼 API | 中文/英文混合评论向量化效果好 |
| HTTP 客户端 | httpx | 0.27+ | 异步、流式支持、API 调用首选 |
| LLM 客户端 | OpenAI Python SDK | 1.30+ | OpenAI 兼容格式直连 Model Router |
| 数据处理 | pandas | 2.2+ | Kaggle CSV 加载与清洗 |
| 报告导出 | markdown + jinja2 | - | Markdown 模板渲染 |
| PDF 导出（P1） | weasyprint | 60+ | Markdown → HTML → PDF |
| 前端 | 原生 HTML + CSS + JS | ES6+ | 单页应用，无需构建工具 |
| 图表 | Chart.js | 4.4+ | 热力图/散点图/趋势图全支持 |
| Markdown 渲染 | marked.js | CDN | 前端渲染 MD 报告 |
| 进度推送 | SSE (Server-Sent Events) | 原生 | 单向流式推送 pipeline 进度 |

### 1.3 模块划分

后端按"路由 → 编排 → 服务 → 持久化"四层划分，每层职责单一：

```
backend/
├── app/
│   ├── api/              # 路由层：HTTP 端点定义
│   ├── pipeline/         # 编排层：多阶段 Prompt 链
│   ├── services/         # 服务层：模型调用、聚类、采集
│   ├── models/           # 数据模型：SQLAlchemy ORM
│   ├── core/             # 核心配置：settings、日志、异常
│   └── utils/            # 工具函数
└── data/                 # SQLite 数据库文件、Kaggle 数据集
```

---

## 二、文件列表及相对路径

### 2.1 后端文件清单

| 相对路径 | 职责 | 优先级 |
|---------|------|-------|
| `backend/requirements.txt` | Python 依赖清单 | P0 |
| `backend/.env.example` | 环境变量模板（API Key、Base URL） | P0 |
| `backend/.env` | 实际环境变量（不入 Git） | P0 |
| `backend/.gitignore` | 忽略 .env / data/*.db / __pycache__ | P0 |
| `backend/app/__init__.py` | 应用包标识 | P0 |
| `backend/app/main.py` | FastAPI 应用入口，挂载路由、CORS、启动脚本 | P0 |
| `backend/app/core/__init__.py` | 包标识 | P0 |
| `backend/app/core/config.py` | Pydantic Settings 配置类，读取 .env | P0 |
| `backend/app/core/logging.py` | 日志配置（统一格式 + 文件输出） | P0 |
| `backend/app/core/exceptions.py` | 自定义异常 + 全局异常处理器 | P0 |
| `backend/app/models/__init__.py` | 包标识 | P0 |
| `backend/app/models/database.py` | SQLAlchemy 引擎、Session、Base | P0 |
| `backend/app/models/schemas.py` | ORM 模型：projects, reviews, pain_points, attributions, suggestions, listing_suggestions | P0 |
| `backend/app/api/__init__.py` | 路由聚合 | P0 |
| `backend/app/api/projects.py` | 项目管理接口：创建/列表/详情 | P0 |
| `backend/app/api/analyze.py` | 触发 pipeline 接口（含 SSE 进度流） | P0 |
| `backend/app/api/reports.py` | 报告查询/导出接口（MD/PDF） | P0 |
| `backend/app/api/reviews.py` | 评论查询接口（按痛点/竞品筛选） | P0 |
| `backend/app/pipeline/__init__.py` | 包标识 | P0 |
| `backend/app/pipeline/orchestrator.py` | Pipeline 编排器：串联各阶段、推送 SSE 进度 | P0 |
| `backend/app/pipeline/stages/__init__.py` | 包标识 | P0 |
| `backend/app/pipeline/stages/s1_ingest.py` | 阶段1：数据加载（Kaggle CSV / 手动 JSON） | P0 |
| `backend/app/pipeline/stages/s2_preprocess.py` | 阶段2：预处理（去重、过滤、元数据提取） | P0 |
| `backend/app/pipeline/stages/s3_cluster.py` | 阶段3：向量化 + K-Means 聚类 | P0 |
| `backend/app/pipeline/stages/s4_label.py` | 阶段4：qwen-max 生成痛点标签 + 分级判断 | P0 |
| `backend/app/pipeline/stages/s5_attribute.py` | 阶段5：R1 根因归因（仅 Top 5） | P0 |
| `backend/app/pipeline/stages/s6_suggest.py` | 阶段6：qwen-max 生成改进建议 + Listing 卖点 | P0 |
| `backend/app/pipeline/stages/s7_report.py` | 阶段7：报告整合（Markdown 渲染） | P0 |
| `backend/app/services/__init__.py` | 包标识 | P0 |
| `backend/app/services/model_router.py` | Model Router 客户端封装（OpenAI 兼容） | P0 |
| `backend/app/services/embedding_service.py` | text-embedding-v4 调用 + 批处理 + 缓存 | P0 |
| `backend/app/services/llm_service.py` | qwen-max / R1 统一调用封装（含重试） | P0 |
| `backend/app/services/cluster_service.py` | K-Means 聚类 + 簇数选择（k=8-15 试区间） | P0 |
| `backend/app/services/data_loader.py` | Kaggle 数据集加载 + 手动采集 JSON 解析 | P0 |
| `backend/app/services/vision_service.py` | P1：qwen3-vl-plus 图片缺陷识别 | P1 |
| `backend/app/services/export_service.py` | Markdown / PDF 报告渲染 | P0（MD）/ P1（PDF） |
| `backend/app/utils/__init__.py` | 包标识 | P0 |
| `backend/app/utils/text.py` | 文本清洗、截断、Token 估算 | P0 |
| `backend/app/utils/json_helpers.py` | LLM JSON 输出解析（容错） | P0 |
| `backend/app/utils/time.py` | 时间格式化、趋势计算 | P0 |
| `backend/run.sh` / `backend/run.bat` | 启动脚本（uvicorn + 初始化数据库） | P0 |

### 2.2 前端文件清单

| 相对路径 | 职责 | 优先级 |
|---------|------|------|-------|
| `frontend/index.html` | 单页应用主页面 + 顶部导航 + 主内容区骨架 | P0 |
| `frontend/css/style.css` | 深色主题样式、KPI 卡片、热力图、矩阵、下钻面板 | P0 |
| `frontend/js/app.js` | 应用主逻辑：状态管理、路由、API 调用 | P0 |
| `frontend/js/api.js` | 后端 API 客户端封装（fetch + SSE） | P0 |
| `frontend/js/components/kpi.js` | KPI 卡片组件（竞品数/评论数/痛点数/R1 归因数） | P0 |
| `frontend/js/components/heatmap.js` | 痛点热力图（Chart.js 横向条形图） | P0 |
| `frontend/js/components/matrix.js` | 改进优先级矩阵（Chart.js 散点图四象限） | P0 |
| `frontend/js/components/detail-panel.js` | 痛点下钻面板（R1 归因 + 评论原文 + 竞品对比） | P0 |
| `frontend/js/components/suggestions.js` | 差异化卖点建议清单 | P0 |
| `frontend/js/components/progress.js` | Pipeline 进度条（SSE 接收） | P0 |
| `frontend/js/components/report-view.js` | 报告预览（marked.js 渲染 MD） | P0 |
| `frontend/js/components/compare-view.js` | P1：R1 vs qwen-max 对比视图 tab | P1 |

### 2.3 文档与配置文件

| 相对路径 | 职责 |
|---------|------|
| `docs/PRD.md` | 产品需求文档（已有） |
| `docs/ARCHITECTURE.md` | 本架构文档 |
| `docs/API.md` | API 接口示例与 curl 调用（由开发同学补充） |
| `docs/RUNBOOK.md` | 本地运行手册（环境变量、数据集放置、启动命令） |
| `data/raw/` | Kaggle 原始数据集（CSV/JSON） |
| `data/processed/` | 预处理后的中间数据 |
| `data/voc_radar.db` | SQLite 数据库文件 |
| `data/reports/` | 生成的报告输出目录 |
| `README.md` | 项目总览、快速启动、技术栈说明 |
| `.gitignore` | 根级忽略规则 |

---

## 三、数据结构与接口

### 3.1 SQLite 表结构

共 6 张表，关系如下：

```
projects 1───* reviews
projects 1───* pain_points
pain_points 1───1 attributions      （仅 Top 5 痛点有归因）
pain_points 1───* suggestions
projects 1───* listing_suggestions
```

#### 3.1.1 `projects` — 分析项目

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | TEXT | PK | UUID |
| name | TEXT | NOT NULL | 项目名（如"蓝牙耳机竞品分析"） |
| category | TEXT | NOT NULL | 品类关键词（如"bluetooth earbuds"） |
| competitor_asins | TEXT | - | JSON 数组，竞品 ASIN 列表 |
| status | TEXT | NOT NULL | enum: `pending`/`running`/`completed`/`failed` |
| current_stage | TEXT | - | 当前 pipeline 阶段（s1~s7） |
| progress | REAL | - | 0.0~1.0 进度 |
| config_json | TEXT | - | JSON：k 值、Top N、是否启用 R1 等 |
| created_at | TIMESTAMP | NOT NULL | 创建时间 |
| updated_at | TIMESTAMP | NOT NULL | 更新时间 |
| completed_at | TIMESTAMP | - | 完成时间 |

#### 3.1.2 `reviews` — 评论

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | TEXT | PK | UUID |
| project_id | TEXT | FK → projects.id | 所属项目 |
| asin | TEXT | NOT NULL | 竞品 ASIN |
| product_name | TEXT | - | 竞品名称 |
| rating | INTEGER | NOT NULL | 星级 1-5 |
| title | TEXT | - | 评论标题 |
| body | TEXT | NOT NULL | 评论正文 |
| date | TIMESTAMP | - | 评论日期 |
| variant | TEXT | - | 变体（颜色/尺寸等） |
| helpful_votes | INTEGER | DEFAULT 0 | 点赞数 |
| is_vp | BOOLEAN | DEFAULT TRUE | 是否 Verified Purchase |
| has_image | BOOLEAN | DEFAULT FALSE | 是否带图 |
| image_urls | TEXT | - | JSON 数组，图片 URL |
| is_negative | BOOLEAN | - | 是否差评（rating ≤ 3） |
| cluster_id | INTEGER | - | 所属痛点簇 ID（聚类后填充） |
| is_representative | BOOLEAN | DEFAULT FALSE | 是否簇代表性评论 |
| is_suspicious | BOOLEAN | DEFAULT FALSE | P1：是否疑似刷评 |
| raw_json | TEXT | - | 原始数据备份（JSON） |
| created_at | TIMESTAMP | NOT NULL | 入库时间 |

索引：`(project_id, asin)`、`(project_id, is_negative)`、`(cluster_id)`、`(project_id, helpful_votes DESC)`

#### 3.1.3 `pain_points` — 痛点簇

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | TEXT | PK | UUID |
| project_id | TEXT | FK → projects.id | 所属项目 |
| cluster_id | INTEGER | NOT NULL | 簇编号（0~k-1） |
| label | TEXT | NOT NULL | qwen-max 生成的痛点标签（如"续航差"） |
| description | TEXT | - | 痛点简述（1-2 句） |
| review_count | INTEGER | NOT NULL | 簇内评论数 |
| impact_ratio | REAL | NOT NULL | 占比（簇评论数 / 项目差评总数） |
| avg_rating | REAL | - | 簇内平均星级 |
| trend | TEXT | - | enum: `rising`/`stable`/`falling`/`unknown` |
| is_common_weakness | BOOLEAN | DEFAULT FALSE | 是否品类共性弱点（多竞品共有） |
| suitable_for_reasoning | BOOLEAN | DEFAULT TRUE | 是否适合 R1 深度推理 |
| reasoning_reason | TEXT | - | 不适合推理时的理由 |
| rank_by_impact | INTEGER | - | 按影响面排名 |
| is_top5 | BOOLEAN | DEFAULT FALSE | 是否进入 R1 归因 Top 5 |
| competitor_breakdown | TEXT | - | JSON：各竞品该痛点占比/星级 |
| created_at | TIMESTAMP | NOT NULL | - |

索引：`(project_id, rank_by_impact)`、`(project_id, is_top5)`

#### 3.1.4 `attributions` — R1 根因归因

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | TEXT | PK | UUID |
| pain_point_id | TEXT | FK → pain_points.id, UNIQUE | 一对一 |
| project_id | TEXT | FK → projects.id | 冗余便于查询 |
| root_cause | TEXT | NOT NULL | R1 输出的根因结论 |
| evidence | TEXT | NOT NULL | JSON 数组：[{review_id, quote, rating, helpful_votes}] |
| improvement_measures | TEXT | - | JSON 数组：[{measure, cost, priority}] |
| model_used | TEXT | NOT NULL | `deepseek-r1` 或 `qwen3.7-max`（对比实验用） |
| prompt_tokens | INTEGER | - | Token 用量（成本追踪） |
| completion_tokens | INTEGER | - | - |
| latency_ms | INTEGER | - | 调用耗时 |
| created_at | TIMESTAMP | NOT NULL | - |

#### 3.1.5 `suggestions` — 改进建议

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | TEXT | PK | UUID |
| pain_point_id | TEXT | FK → pain_points.id | 关联痛点 |
| project_id | TEXT | FK → projects.id | - |
| type | TEXT | NOT NULL | enum: `product_improvement`/`listing_optimization` |
| content | TEXT | NOT NULL | 建议内容 |
| cost | TEXT | - | enum: `low`/`medium`/`high` |
| priority | TEXT | - | enum: `high`/`medium`/`low` |
| quadrant | TEXT | - | enum: `quick_win`/`strategic`/`filler`/`thankless`（四象限） |
| created_at | TIMESTAMP | NOT NULL | - |

#### 3.1.6 `listing_suggestions` — Listing 卖点建议

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | TEXT | PK | UUID |
| project_id | TEXT | FK → projects.id | - |
| competitor_weakness | TEXT | NOT NULL | 竞品共性弱点 |
| suggested_selling_point | TEXT | NOT NULL | 建议卖点 |
| listing_field | TEXT | - | enum: `title`/`bullet_point`/`a_plus_content`/`image` |
| priority | TEXT | NOT NULL | enum: `high`/`medium`/`low` |
| rationale | TEXT | - | 建议理由 |
| created_at | TIMESTAMP | NOT NULL | - |

### 3.2 FastAPI 接口定义

所有接口统一前缀 `/api/v1`，响应体统一格式：

```json
{
  "code": 0,
  "message": "ok",
  "data": { ... },
  "request_id": "uuid"
}
```

错误时 `code != 0`，`data` 为 null，`message` 描述错误。

#### 3.2.1 项目管理

| 方法 | 路径 | 说明 | 请求体 | 响应体 |
|------|------|------|--------|--------|
| POST | `/projects` | 创建分析项目 | `{name, category, competitor_asins[], config?}` | `ProjectVO` |
| GET | `/projects` | 项目列表 | query: `page, size` | `PageVO<ProjectVO>` |
| GET | `/projects/{id}` | 项目详情 | - | `ProjectDetailVO`（含统计） |
| DELETE | `/projects/{id}` | 删除项目 | - | `{code, message}` |

#### 3.2.2 触发分析（核心）

| 方法 | 路径 | 说明 | 请求体 | 响应体 |
|------|------|------|--------|--------|
| POST | `/projects/{id}/analyze` | 触发 pipeline | `{config?: {k_range:[8,15], top_n:5, enable_r1:true, enable_vision:false}}` | `{task_id, status:"running"}` |
| GET | `/projects/{id}/progress` | SSE 进度流 | - | `text/event-stream`，每阶段推送 `{stage, progress, message, timestamp}` |
| GET | `/projects/{id}/status` | 查询状态（非流式） | - | `{status, current_stage, progress, error?}` |

#### 3.2.3 分析结果查询

| 方法 | 路径 | 说明 | query | 响应体 |
|------|------|------|-------|--------|
| GET | `/projects/{id}/overview` | 看板概览（KPI + 热力图 + 矩阵 + 卖点） | - | `OverviewVO` |
| GET | `/projects/{id}/pain-points` | 痛点列表 | `top5_only?, sort_by?` | `PainPointVO[]` |
| GET | `/pain-points/{id}` | 痛点详情（含归因 + 代表性评论 + 竞品对比） | - | `PainPointDetailVO` |
| GET | `/projects/{id}/reviews` | 评论列表（支持筛选） | `cluster_id?, asin?, is_negative?, page, size` | `PageVO<ReviewVO>` |
| GET | `/reviews/{id}` | 评论详情 | - | `ReviewVO` |

#### 3.2.4 报告导出

| 方法 | 路径 | 说明 | query | 响应 |
|------|------|------|-------|------|
| GET | `/projects/{id}/report` | 获取 Markdown 报告内容 | `format=md` | `{content: "..."}` |
| GET | `/projects/{id}/report/download` | 下载报告文件 | `format=md\|pdf` | 文件流（Content-Disposition） |

#### 3.2.5 对比实验（P1）

| 方法 | 路径 | 说明 | 响应体 |
|------|------|------|--------|
| GET | `/pain-points/{id}/compare` | R1 vs qwen-max 归因对比 | `{r1_attribution, qwen_attribution, diff_summary}` |

### 3.3 核心 JSON Schema

#### 3.3.1 `OverviewVO` — 看板概览

```json
{
  "project": {
    "id": "uuid",
    "name": "蓝牙耳机竞品分析",
    "category": "bluetooth earbuds",
    "status": "completed",
    "created_at": "2026-07-29T10:00:00Z",
    "completed_at": "2026-07-29T10:12:34Z"
  },
  "kpis": {
    "competitor_count": 3,
    "review_count": 1245,
    "negative_review_count": 612,
    "pain_point_count": 12,
    "r1_attribution_count": 5
  },
  "heatmap": [
    {
      "pain_point_id": "uuid",
      "label": "续航差",
      "impact_ratio": 0.28,
      "review_count": 345,
      "avg_rating": 1.8,
      "trend": "rising",
      "is_top5": true
    }
  ],
  "matrix": [
    {
      "pain_point_id": "uuid",
      "label": "续航差",
      "impact_ratio": 0.28,
      "difficulty_score": 0.7,
      "quadrant": "strategic",
      "priority": "high"
    }
  ],
  "listing_suggestions": [
    {
      "id": "uuid",
      "competitor_weakness": "续航差（3/3 竞品共性）",
      "suggested_selling_point": "标题突出续航参数（如 50H Playtime）",
      "listing_field": "title",
      "priority": "high",
      "rationale": "竞品普遍被吐槽续航，强化此卖点可形成差异化"
    }
  ]
}
```

#### 3.3.2 `PainPointDetailVO` — 痛点详情

```json
{
  "pain_point": {
    "id": "uuid",
    "label": "续航差",
    "description": "用户普遍反映电池续航远低于标称值，低温环境尤为明显",
    "impact_ratio": 0.28,
    "review_count": 345,
    "avg_rating": 1.8,
    "trend": "rising",
    "is_common_weakness": true,
    "suitable_for_reasoning": true,
    "rank_by_impact": 1,
    "is_top5": true
  },
  "attribution": {
    "root_cause": "低温环境下电池化学活性下降，导致续航缩水；部分批次存在电池老化问题",
    "evidence": [
      {
        "review_id": "uuid",
        "quote": "skating in -10°C, battery died in 20 min",
        "rating": 1,
        "helpful_votes": 23,
        "asin": "B0xxx"
      }
    ],
    "improvement_measures": [
      {"measure": "采用低温电池芯", "cost": "medium", "priority": "high"},
      {"measure": "Listing 标注工作温度范围", "cost": "low", "priority": "high"}
    ],
    "model_used": "deepseek-r1"
  },
  "representative_reviews": [
    {
      "id": "uuid",
      "rating": 1,
      "title": "Useless in winter",
      "body": "Battery dies after 20 min in cold weather...",
      "date": "2025-11-03",
      "variant": "黑色",
      "helpful_votes": 23,
      "asin": "B0xxx",
      "has_image": true,
      "image_urls": ["https://..."]
    }
  ],
  "competitor_comparison": [
    {"asin": "B0xxx", "product_name": "Product A", "pain_ratio": 0.32, "avg_rating": 1.7, "is_common": true},
    {"asin": "B0yyy", "product_name": "Product B", "pain_ratio": 0.28, "avg_rating": 1.9, "is_common": true}
  ]
}
```

#### 3.3.3 SSE 进度消息

```
event: progress
data: {"stage":"s3_cluster","progress":0.35,"message":"正在向量化 612 条差评...","timestamp":"2026-07-29T10:03:12Z"}

event: progress
data: {"stage":"s3_cluster","progress":0.45,"message":"向量化完成，开始 K-Means 聚类（k=10）","timestamp":"2026-07-29T10:03:45Z"}

event: stage_done
data: {"stage":"s3_cluster","duration_ms":33100,"output_summary":"生成 10 个痛点簇"}

event: error
data: {"stage":"s5_attribute","message":"R1 调用超时","error_code":"LLM_TIMEOUT"}

event: complete
data: {"project_id":"uuid","status":"completed","report_url":"/api/v1/projects/uuid/report"}
```

---

## 四、程序调用流程（时序图）

### 4.1 完整 Pipeline 时序

```
用户        前端          FastAPI      Orchestrator    各 Stage      Model Router    SQLite
 │           │              │              │              │              │              │
 │─输入品类─→│              │              │              │              │              │
 │           │─POST/projects/{id}/analyze→│              │              │              │
 │           │              │─创建任务────→│              │              │              │
 │           │              │←task_id──────│              │              │              │
 │           │←task_id──────│              │              │              │              │
 │           │              │              │              │              │              │
 │           │─GET /progress (SSE)────────→│              │              │              │
 │           │              │              │              │              │              │
 │           │              │              │─ S1: ingest ─→│              │              │
 │           │              │              │              │─加载 CSV/JSON──────────────→│
 │           │              │              │              │←reviews 数据─│              │
 │           │              │              │              │─写入 reviews─│──────────────→│
 │           │              │              │←stage_done───│              │              │
 │           │              │              │─ 推送 SSE: progress=0.15 ─────────────────→│（前端）
 │           │              │              │              │              │              │
 │           │              │              │─ S2: preprocess →│           │              │
 │           │              │              │              │─去重/过滤/提取元数据         │
 │           │              │              │              │─更新 reviews─│──────────────→│
 │           │              │              │←stage_done───│              │              │
 │           │              │              │─ 推送 SSE: progress=0.25 ─────────────────→│
 │           │              │              │              │              │              │
 │           │              │              │─ S3: cluster →│             │              │
 │           │              │              │              │─text-embedding-v4 批量调用─→│
 │           │              │              │              │←embeddings───│              │
 │           │              │              │              │─K-Means 聚类（k=8-15 试区间）│
 │           │              │              │              │─更新 reviews.cluster_id──────→│
 │           │              │              │←stage_done───│              │              │
 │           │              │              │─ 推送 SSE: progress=0.45 ─────────────────→│
 │           │              │              │              │              │              │
 │           │              │              │─ S4: label ──→│             │              │
 │           │              │              │              │─qwen-max 为每簇生成标签─────→│
 │           │              │              │              │←标签+分级判断─│              │
 │           │              │              │              │─写入 pain_points────────────→│
 │           │              │              │              │─计算影响面/共性弱点         │
 │           │              │              │←stage_done───│              │              │
 │           │              │              │─ 推送 SSE: progress=0.60 ─────────────────→│
 │           │              │              │              │              │              │
 │           │              │              │─ S5: attribute→│            │              │
 │           │              │              │              │─取 Top 8 按影响面           │
 │           │              │              │              │─qwen-max 判断是否适合推理──→│
 │           │              │              │              │←suitable_top5─│              │
 │           │              │              │              │─对 Top 5 调用 DeepSeek-R1──→│
 │           │              │              │              │  (Prompt: 引用评论原文)     │
 │           │              │              │              │←root_cause+evidence────────│
 │           │              │              │              │─写入 attributions───────────→│
 │           │              │              │←stage_done───│              │              │
 │           │              │              │─ 推送 SSE: progress=0.80 ─────────────────→│
 │           │              │              │              │              │              │
 │           │              │              │─ S6: suggest →│             │              │
 │           │              │              │              │─qwen-max 整合归因→改进建议──→│
 │           │              │              │              │─qwen-max 分析共性弱点→卖点──→│
 │           │              │              │              │←suggestions+listing_sugg───│
 │           │              │              │              │─写入 suggestions/listing────→│
 │           │              │              │←stage_done───│              │              │
 │           │              │              │─ 推送 SSE: progress=0.92 ─────────────────→│
 │           │              │              │              │              │              │
 │           │              │              │─ S7: report →│              │              │
 │           │              │              │              │─Jinja2 渲染 Markdown 模板   │
 │           │              │              │              │─写入 data/reports/{id}.md   │
 │           │              │              │←stage_done───│              │              │
 │           │              │              │─ 推送 SSE: complete ─────────────────────→│
 │           │              │              │              │              │              │
 │           │←SSE: complete│              │              │              │              │
 │←看板渲染──│              │              │              │              │              │
 │           │─GET /overview→│              │              │              │              │
 │           │←OverviewVO───│              │              │              │              │
 │←热力图/矩阵│              │              │              │              │              │
 │─点击痛点─→│              │              │              │              │              │
 │           │─GET /pain-points/{id}──────→│              │              │              │
 │           │←PainPointDetailVO──────────│              │              │              │
 │←下钻面板─│              │              │              │              │              │
 │─导出报告→│              │              │              │              │              │
 │           │─GET /report/download───────→│              │              │              │
 │←MD 文件──│              │              │              │              │              │
```

### 4.2 关键阶段细节

#### S3 聚类阶段（K-Means k 值选择）

```
1. 取所有差评（is_negative=true）的文本
2. 调用 text-embedding-v4 批量向量化（每批 100 条）
3. 对 k=8,9,10,...,15 分别跑 K-Means，计算 silhouette score
4. 选择 silhouette 最高的 k（兜底：若都低于 0.2，降级到 k=10 并记录 warning）
5. 每簇按 (helpful_votes * 0.6 + body_length * 0.4) 排序，取 Top 5-10 作为代表性评论
6. 更新 reviews.cluster_id 与 reviews.is_representative
```

#### S4 标签 + 分级阶段

```
对每个簇：
  1. 取簇内代表性评论 Top 10
  2. Prompt qwen3.7-max：
     - 输入：代表性评论列表
     - 输出 JSON：{label, description, suitable_for_reasoning, reasoning_reason?}
       - suitable_for_reasoning=false 的情况：纯事实型（"太贵了""太重了"）
  3. 计算影响面指标：review_count / impact_ratio / avg_rating / trend
  4. 计算是否共性弱点：若 ≥2 个竞品都有该痛点且占比 > 15%，标记 is_common_weakness=true
  5. 按 impact_ratio 排序得到 rank_by_impact
```

#### S5 R1 归因阶段（Top 5 筛选）

```
1. 取 rank_by_impact 前 8 的痛点
2. 过滤 suitable_for_reasoning=true 的，取前 5 个 → Top 5
3. 对每个 Top 5 痛点调用 DeepSeek-R1：
   Prompt 结构：
     System: 你是产品根因分析专家。基于用户评论做根因归因。
             规则：1) 所有结论必须引用评论原文作为证据；
                   2) 不编造评论中未出现的数据；
                   3) 信息不足时明确说明"无法确认"。
     User: 
       痛点标签：{label}
       代表性评论（Top 10）：{reviews}
       [可选] 图片缺陷识别结果：{vision_tags}
       
       请输出 JSON：
       {
         "root_cause": "...",
         "evidence": [{"review_id":"...","quote":"...","explanation":"..."}],
         "improvement_measures": [{"measure":"...","cost":"low|medium|high","priority":"high|medium|low"}]
       }
4. 解析 R1 输出（容错：若 JSON 解析失败，降级为文本存储并标记）
5. 记录 model_used、token 用量、latency
```

### 4.3 异常与降级策略

| 异常场景 | 降级策略 |
|---------|---------|
| Model Router 调用超时 | 重试 3 次（指数退避 1s/2s/4s），仍失败则该阶段标记 failed，pipeline 不中断（除 S3 外） |
| R1 调用失败 | 该痛点降级用 qwen3.7-max 归因，attribution.model_used 标记为 `qwen3.7-max` |
| text-embedding-v4 失败 | 整个 pipeline 失败（无降级路径） |
| JSON 解析失败 | 尝试正则提取 JSON 片段；仍失败则原始输出存入 raw 字段，结构化字段为 null |
| Kaggle 数据集缺失 | 报错并提示用户放置数据集到 `data/raw/` |
| SQLite 写入失败 | 重试 3 次，仍失败则记录日志并跳过该条记录 |

---

## 五、任务列表（按实现顺序）

> 编号规则：T-{序号}；依赖标注；难度：简单(S)/中等(M)/复杂(C)；对应需求 ID。

### 阶段一：基础设施（Week 1 前段）

| 编号 | 任务 | 依赖 | 难度 | 需求 | 预计 |
|------|------|------|------|------|------|
| T-1 | 初始化项目骨架：目录结构、.gitignore、README、requirements.txt | - | S | - | 0.5d |
| T-2 | 编写 .env.example 与 core/config.py（Pydantic Settings） | T-1 | S | - | 0.5d |
| T-3 | 实现 SQLAlchemy ORM 模型与数据库初始化脚本 | T-2 | M | P0-1 | 1d |
| T-4 | 实现 Model Router 客户端封装（model_router.py + llm_service.py） | T-2 | M | P0-3/4/5 | 1d |
| T-5 | 实现 embedding_service.py（批量 + 缓存） | T-4 | M | P0-3 | 0.5d |

### 阶段二：数据与聚类（Week 1 后段）

| 编号 | 任务 | 依赖 | 难度 | 需求 | 预计 |
|------|------|------|------|------|------|
| T-6 | 准备 Kaggle 数据集，放置到 data/raw/ 并验证字段 | T-1 | S | P0-1 | 0.5d |
| T-7 | 实现 data_loader.py：Kaggle CSV/JSON 加载 + 字段映射 | T-3, T-6 | M | P0-1 | 1d |
| T-8 | 实现 s1_ingest.py：评论入库（含去重） | T-7 | M | P0-1 | 0.5d |
| T-9 | 实现 s2_preprocess.py：过滤非 VP、元数据提取、is_negative 标记 | T-8 | M | P0-2 | 1d |
| T-10 | 实现 cluster_service.py：K-Means + k 值选择（silhouette） | T-5 | C | P0-3 | 1.5d |
| T-11 | 实现 s3_cluster.py：向量化差评 + 聚类 + 代表性评论标记 | T-9, T-10 | M | P0-3 | 1d |

### 阶段三：LLM 阶段（Week 2 前段）

| 编号 | 任务 | 依赖 | 难度 | 需求 | 预计 |
|------|------|------|------|------|------|
| T-12 | 编写 Prompt 模板库（labels/suggestions/r1_attribution/listing） | T-4 | M | P0-4/5/6 | 1d |
| T-13 | 实现 s4_label.py：qwen-max 生成标签 + 分级判断 + 影响面统计 | T-11, T-12 | M | P0-4 | 1d |
| T-14 | 实现 s5_attribute.py：Top 8→Top 5 筛选 + R1 归因 + 证据解析 | T-13 | C | P0-5, P1-1 | 1.5d |
| T-15 | 实现 s6_suggest.py：qwen-max 整合归因→改进建议 + 共性弱点→Listing 卖点 | T-14 | M | P0-6, P1-3 | 1d |
| T-16 | 实现 s7_report.py：Jinja2 渲染 Markdown 报告模板 | T-15 | M | P0-8 | 0.5d |

### 阶段四：API 与编排（Week 2 中段）

| 编号 | 任务 | 依赖 | 难度 | 需求 | 预计 |
|------|------|------|------|------|------|
| T-17 | 实现 orchestrator.py：串联 7 阶段 + 异常降级 + 日志 | T-8~T-16 | C | - | 1d |
| T-18 | 实现 SSE 进度推送机制（/progress 端点） | T-17 | M | P0-7 | 0.5d |
| T-19 | 实现 API 路由层：projects / analyze / reviews / pain-points / reports | T-17 | M | P0-7 | 1d |
| T-20 | 实现 main.py：CORS、路由挂载、全局异常处理、启动初始化 | T-19 | S | - | 0.5d |

### 阶段五：前端看板（Week 2 后段，可与阶段四并行）

| 编号 | 任务 | 依赖 | 难度 | 需求 | 预计 |
|------|------|------|------|------|------|
| T-21 | 编写 index.html + style.css：深色主题骨架 + 顶部导航 + KPI 卡片 | - | M | P0-7 | 1d |
| T-22 | 实现 js/api.js：fetch 封装 + SSE 接收 | - | M | P0-7 | 0.5d |
| T-23 | 实现 heatmap.js：痛点热力图（Chart.js 横向条形图，按影响面排序） | T-21, T-22 | M | P0-7 | 1d |
| T-24 | 实现 matrix.js：改进优先级四象限散点图 | T-21, T-22 | M | P0-7 | 1d |
| T-25 | 实现 detail-panel.js：痛点下钻面板（归因 + 评论 + 竞品对比） | T-22 | C | P0-7 | 1.5d |
| T-26 | 实现 suggestions.js：差异化卖点建议清单 | T-22 | S | P0-7, P1-3 | 0.5d |
| T-27 | 实现 progress.js：pipeline 进度条 + 阶段提示 | T-22, T-18 | M | P0-7 | 0.5d |
| T-28 | 实现 report-view.js：报告预览（marked.js） + 导出按钮 | T-22 | S | P0-8 | 0.5d |

### 阶段六：联调与打磨（Week 3）

| 编号 | 任务 | 依赖 | 难度 | 需求 | 预计 |
|------|------|------|------|------|------|
| T-29 | 前后端联调：完整跑通一遍品类分析 | T-20, T-21~T-28 | C | - | 1d |
| T-30 | P1：实现 vision_service.py + 图片缺陷识别集成 | T-4 | M | P1-2 | 1d |
| T-31 | P1：实现 compare-view.js + 对比接口（R1 vs qwen-max） | T-14, T-22 | M | P1-6 | 1d |
| T-32 | P1：PDF 导出（weasyprint） | T-16 | M | P1-5 | 0.5d |
| T-33 | P1：时间趋势分析（trend 字段计算 + 趋势图组件） | T-13 | M | P1-4 | 0.5d |
| T-34 | 编写 RUNBOOK.md：本地运行手册 + 数据集放置说明 | T-29 | S | - | 0.5d |
| T-35 | 录制 3 分钟 Demo 视频 + 截图素材 | T-29 | S | - | 1d |

### 任务依赖关系图

```
T-1 ─┬─ T-2 ─┬─ T-3 ─┬─ T-7 ── T-8 ── T-9 ──┐
     │       │       │                        │
     │       │       └─ T-6 ──┘                │
     │       │                                 │
     │       └─ T-4 ─┬─ T-5 ── T-10 ── T-11 ──┤
     │               │                        │
     │               └─ T-12 ── T-13 ── T-14 ──┤
     │                              │          │
     │                              └─ T-15 ── T-16
     │                                         │
     └─ T-21 ── T-22 ──┬─ T-23                 │
                       ├─ T-24                 │
                       ├─ T-25                 │
                       ├─ T-26                 │
                       ├─ T-27 ←── T-18 ←── T-17 ←─┘
                       └─ T-28
                                  T-20 ←─ T-19 ←─ T-17
                                           
                       T-29 ←─ T-20 + T-21~T-28
                       T-30~T-33 (P1，按时间挑做)
                       T-34, T-35 (收尾)
```

---

## 六、依赖包列表

### 6.1 Python 依赖（`backend/requirements.txt`）

```text
# Web 框架
fastapi==0.110.3
uvicorn[standard]==0.27.1
python-multipart==0.0.9
sse-starlette==2.0.0

# 配置与日志
pydantic==2.6.4
pydantic-settings==2.2.1
python-dotenv==1.0.1

# 数据库
sqlalchemy==2.0.29

# 数据处理
pandas==2.2.2
numpy==1.26.4

# 机器学习
scikit-learn==1.4.2

# HTTP 客户端
httpx==0.27.0

# LLM SDK（OpenAI 兼容，直连 Model Router）
openai==1.28.0

# 报告渲染
jinja2==3.1.4
markdown==3.6

# PDF 导出（P1）
weasyprint==61.0

# 工具
python-dateutil==2.9.0
tenacity==8.2.3  # 重试机制

# 开发依赖（可选）
pytest==8.1.1
pytest-asyncio==0.23.6
```

### 6.2 前端依赖（CDN 引用，无需构建）

在 `index.html` 中通过 CDN 引入：

```html
<!-- Chart.js：图表渲染 -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>

<!-- marked.js：Markdown 渲染 -->
<script src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script>

<!-- DOMPurify：Markdown 渲染后的 XSS 防护 -->
<script src="https://cdn.jsdelivr.net/npm/dompurify@3.0.11/dist/purify.min.js"></script>

<!-- 可选：highlight.js 代码高亮 -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/styles/github-dark.min.css">
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/lib/common.min.js"></script>
```

> 备注：原型阶段用 CDN 即可，离线演示场景可下载到 `frontend/vendor/` 本地引用。

---

## 七、共享知识（跨文件约定）

### 7.1 Model Router API 调用封装

所有模型调用统一走 `services/model_router.py`，禁止在 stage 中直接 `import openai`：

```python
# services/model_router.py 核心封装
from openai import AsyncOpenAI
from app.core.config import settings

class ModelRouterClient:
    """Model Router 统一客户端（OpenAI 兼容格式）"""
    
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.MODEL_ROUTER_API_KEY,
            base_url=settings.MODEL_ROUTER_BASE_URL,  # 通过 .env 配置，方便切换
        )
    
    async def embed(self, texts: list[str], model="text-embedding-v4") -> list[list[float]]:
        """批量向量化"""
        ...
    
    async def chat(self, messages, model="qwen3.7-max", response_format=None, temperature=0.3):
        """通用对话调用（qwen-max / R1 共用）"""
        ...
    
    async def chat_json(self, messages, model="qwen3.7-max", schema: dict = None) -> dict:
        """要求 JSON 输出的对话调用（含解析容错）"""
        ...

# 全局单例
model_router = ModelRouterClient()
```

**模型名约定**（与百炼平台对应）：
- `text-embedding-v4`
- `qwen3.7-max`
- `deepseek-r1`
- `qwen3-vl-plus`（P1）
- `qwen3.5-flash`（P1，可选）

### 7.2 错误处理约定

| 层 | 异常类型 | 处理方式 |
|----|---------|---------|
| API 路由层 | `HTTPException` + 全局异常处理器 | 统一返回 `{code, message, request_id}`，code 为业务错误码 |
| Pipeline 编排层 | `StageError(stage, message, cause)` | 捕获后决定是否降级；不可降级则标记 project.status=failed |
| 服务层 | `LLMError` / `EmbeddingError` / `ClusterError` | 由调用方决定重试或降级 |
| 工具层 | `JSONParseError` | 尝试容错解析；失败则上抛 |

**业务错误码表**：
- `0` = 成功
- `1001` = 项目不存在
- `1002` = 项目状态非法（如已运行中又触发）
- `2001` = 数据集缺失
- `2002` = 数据预处理失败
- `3001` = 向量化失败
- `3002` = 聚类失败
- `4001` = LLM 调用失败（超时/限流/网络）
- `4002` = LLM JSON 输出解析失败
- `5001` = 报告渲染失败

### 7.3 数据流约定

1. **评论入库后不可变**：`reviews` 表写入后，除 `cluster_id` / `is_representative` / `is_suspicious` 三个分析字段外，其他字段不修改
2. **阶段间数据传递走数据库**：每个 stage 从 DB 读输入、写输出到 DB，避免内存传递导致重启丢失
3. **pipeline 可重入**：每个 stage 检查 `project.current_stage`，已完成则跳过；支持从中断点恢复（原型阶段简化为整阶段重跑）
4. **报告生成是幂等的**：同一项目多次触发 `s7_report` 覆盖旧报告文件
5. **环境变量隔离**：API Key、Base URL 仅在 `.env` 中，代码中通过 `settings` 访问，禁止硬编码

### 7.4 前后端数据交互约定

- 所有时间字段使用 ISO 8601 UTC 格式（如 `2026-07-29T10:00:00Z`）
- 所有 ID 使用 UUID v4 字符串
- 分页接口统一参数 `page`（从 1 开始）+ `size`（默认 20，最大 100）
- SSE 消息严格遵循 `event: <type>\ndata: <json>\n\n` 格式
- 前端所有 fetch 走 `js/api.js` 统一封装，自动处理错误码与重试

### 7.5 日志与可观测

- 日志格式：`[时间] [级别] [模块] [request_id] 消息`
- 日志文件：`backend/logs/app.log`（按天滚动）
- 关键打点：每个 stage 的开始/结束/耗时、每次 LLM 调用的 model/token/latency
- Demo 演示时可关闭详细日志，仅保留 stage 进度

---

## 八、待明确事项

### 8.1 需 team-lead / 产品确认

| # | 事项 | 影响 | 建议 |
|---|------|------|------|
| A-1 | Demo 品类最终选定 | 影响数据集准备与 Prompt 调优方向 | 建议蓝牙耳机（评论量大、痛点直观、评委有共鸣） |
| A-2 | Kaggle 数据集具体选哪个 | 影响字段映射与数据量 | 建议 `Amazon Reviews 2023`（McAuley Lab），含 rating/title/text/date，字段齐全 |
| A-3 | 是否需要在看板显示原始评论的英文原文 + 中文翻译 | 影响 LLM 调用次数与 UI 设计 | 原型建议保留英文原文，痛点标签/归因用中文输出，降低复杂度 |
| A-4 | 代码仓库公开还是私有 | 影响 README 与提交流程 | 建议 GitHub 公开仓库，方便评委查看 |

### 8.2 架构层面需开发同学验证

| # | 事项 | 验证方式 |
|---|------|---------|
| A-5 | Model Router 个人账号是否能稳定调用 R1（免费额度是否够 Top 5×3 次演示） | 注册账号后跑一次 s5_attribute 验证 |
| A-6 | text-embedding-v4 批量调用上限（单次最大条数） | 查百炼文档或实测，决定 batch size |
| A-7 | K-Means 在 500-2000 条评论上的 silhouette score 实际区间 | 跑通 s3 后看是否需要切 HDBSCAN |
| A-8 | R1 输出 JSON 的稳定性（是否经常需要容错解析） | 跑 10 次 s5 统计 JSON 解析成功率 |
| A-9 | weasyprint 在 Windows 上的安装是否顺利（依赖 GTK） | 若困难，P1 的 PDF 可改用 `pdfkit + wkhtmltopdf` 或 `playwright` 截图转 PDF |

### 8.3 已明确无需再确认

- ✅ 聚类算法：K-Means（k=8-15）
- ✅ Top 5 选择标准：Top 8 按影响面 + qwen-max 分级判断
- ✅ 痛点分级：简化实现，不强调三级分类
- ✅ 看板布局：单栏 + 下钻
- ✅ 报告导出：P0 Markdown，P1 PDF
- ✅ R1 vs qwen-max 对比：P1，详情面板加对比 tab
- ✅ 数据策略：Kaggle 优先 + Rainforest 备选
- ✅ 代码仓库：GitHub
- ✅ 存储位置：`E:\projects\voc-radar`
- ✅ API 配置：`.env` 文件，Base URL 可切换

---

## 附录 A：本地快速启动流程

```bash
# 1. 克隆仓库
git clone <repo-url> E:\projects\voc-radar
cd E:\projects\voc-radar

# 2. 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# 3. 安装依赖
pip install -r backend/requirements.txt

# 4. 配置环境变量
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入 MODEL_ROUTER_API_KEY

# 5. 放置 Kaggle 数据集到 data/raw/

# 6. 初始化数据库
python -m backend.app.models.database

# 7. 启动后端
cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 8. 打开前端
# 浏览器访问 http://localhost:8000/  （FastAPI 托管 frontend 静态文件）
# 或直接打开 frontend/index.html
```

## 附录 B：`.env.example` 模板

```env
# Model Router 配置
MODEL_ROUTER_API_KEY=sk-your-personal-bailian-key
MODEL_ROUTER_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
# 比赛阶段切换为：https://model-router.edu-aliyun.com/v1

# 模型名称（与百炼对应，按需调整）
MODEL_EMBEDDING=text-embedding-v4
MODEL_LLM=qwen3.7-max
MODEL_R1=deepseek-r1
MODEL_VISION=qwen3-vl-plus
MODEL_FLASH=qwen3.5-flash

# 数据库
DATABASE_URL=sqlite:///./data/voc_radar.db

# 聚类配置
CLUSTER_K_MIN=8
CLUSTER_K_MAX=15
CLUSTER_BATCH_SIZE=100

# Pipeline 配uration
TOP_N_FOR_R1=5
TOP_N_CANDIDATES=8
R1_MAX_RETRIES=3
LLM_TIMEOUT_SECONDS=60

# 报告输出目录
REPORT_OUTPUT_DIR=./data/reports

# 日志
LOG_LEVEL=INFO
LOG_DIR=./logs
```

---

> 本架构文档为 VOC Radar 原型的实现蓝图。开发过程中如有调整，请同步更新此文档并通知团队。
