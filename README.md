# VOC Radar 评论雷达

> AI+跨境黑客松巅峰赛 — 自动化评论分析流水线（复赛冲刺中）

## 项目简介

VOC Radar 将跨境卖家面对的"上千条竞品评论"转化为可执行的产品改进方向和差异化卖点建议。核心是一条自动化 Prompt 链 Pipeline：采集 → 预处理 → 聚类 → 分级 → 归因 → 建议 → 报告。

## 一键启动（推荐）

在项目根目录**双击 `start.bat`** 即可：脚本会自动做环境自检（虚拟环境 / `backend\.env` / API Key / 前端目录 / uvicorn 依赖），
然后启动服务并在约 5 秒后自动打开浏览器。

浏览器访问：**http://127.0.0.1:8000**

> **单端口架构**：后端 uvicorn 一个进程、一个端口（8000）就同时提供
> API（`/api/v1`）与前端页面（`/`，由 `backend/app/main.py` 挂载 `StaticFiles`）。
> **不需要再单独启动前端静态服务器**（早期"后端 + `python -m http.server`"的写法是错的，会端口冲突）。

## 技术栈

- **后端**：Python 3.13 / FastAPI / SQLAlchemy / scikit-learn / sse-starlette
- **前端**：原生 HTML + Chart.js（深色主题单页应用）
- **数据库**：SQLite（原型零配置）
- **AI 模型**：Model Router（OpenAI 兼容格式）
  - 官方 Base URL：`https://model-router.edu-aliyun.com/v1`（赛方通道，走赛方 25000 Credits 额度）
  - 备选 Base URL：`https://dashscope.aliyuncs.com/compatible-mode/v1`（百炼直连，走个人 Key 自费）
  - 模型（对齐官方《参赛指南》6.2 节清单，`backend/.env` 中的变量名）：
    - `MODEL_EMBEDDING` = `qwen/text-embedding-v4`（向量化）
    - `MODEL_FLASH` = `qwen/qwen3.5-flash`（粗筛分类 / 刷评初判）
    - `MODEL_LLM` = `qwen/qwen3.7-max`（标签 / 建议 / 分级判断）
    - `MODEL_VISION` = `qwen/qwen3-vl-plus`（带图评论视觉理解）
    - `MODEL_R1` = `deepseek-r1`（Top 5 痛点根因归因）

> ⚠️ **模型名前缀待实测**：官方清单带 `qwen/` 前缀，而 `.env` 当前为无前缀写法。
> 是否必需前缀请以实测为准——运行 `.\.venv\Scripts\python.exe backend\check_models.py`，
> 脚本会同时测试两种命名并输出建议写入 `.env` 的模型名。

## 目录结构

```
voc-radar/
├── start.bat               # Windows 一键启动（环境自检 + 启动 + 自动开浏览器）
├── .venv/                  # 虚拟环境（项目根目录，Python 3.13）
├── backend/                # 后端
│   ├── app/
│   │   ├── api/            # FastAPI 路由（前缀 /api/v1）
│   │   ├── core/           # 配置、日志、异常
│   │   ├── models/         # SQLAlchemy ORM
│   │   ├── pipeline/       # Pipeline 编排 + 各阶段
│   │   ├── services/       # 模型调用 / 聚类 / 采集服务
│   │   └── utils/          # 工具函数
│   ├── check_models.py     # 模型连通性自检（含模型名前缀实测）
│   ├── data/               # SQLite + 数据集 + 报告
│   ├── logs/               # 日志
│   ├── requirements.txt
│   └── .env.example
├── frontend/               # 前端单页应用（由后端单端口托管）
└── docs/                   # PRD / 架构 / API / RUNBOOK
```

## 快速启动

### 方式一：一键启动（推荐）

双击项目根目录的 **`start.bat`**，浏览器访问 **http://127.0.0.1:8000**。

不自动打开浏览器：`start.bat --no-browser`；换端口：用记事本改 `start.bat` 里的 `set "PORT=8000"`。

### 方式二：手工命令

```bash
# 0. 首次使用：创建虚拟环境 + 安装依赖（若 .venv 已存在可跳过）
C:\Users\32615\.workbuddy\binaries\python\versions\3.13.12\python.exe -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend/requirements.txt

# 1. 配置环境变量（复制模板并填入 API Key）
copy backend\.env.example backend\.env

# 2. 启动（注意：venv 在项目根目录；必须在 backend/ 目录下启动，app.main:app 才能被导入）
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3. 浏览器打开 http://127.0.0.1:8000
```

数据库会在应用启动时自动初始化（建表 + 建目录），无需手工执行。

### 自检工具

```bash
# 模型连通性自检：验证哪些模型名 / Base URL 组合可用，判定模型名前缀是否必需
.\.venv\Scripts\python.exe backend\check_models.py

# 只测赛方 Model Router 通道
.\.venv\Scripts\python.exe backend\check_models.py --base-url https://model-router.edu-aliyun.com/v1 --api-key <赛方Key>
```

## 文档

- `docs/PRD.md` — 产品需求文档
- `docs/ARCHITECTURE.md` — 系统架构设计
- `docs/RUNBOOK.md` — 本地运行手册（待补充）

## Pipeline 阶段

| 阶段 | 文件 | 说明 |
|------|------|------|
| S1 | `s1_ingest.py` | 评论入库（含去重） |
| S2 | `s2_preprocess.py` | 过滤非 VP、元数据提取、is_negative 标记 |
| S3 | `s3_cluster.py` | 向量化差评 + K-Means 聚类 + 代表性评论标记 |
| S4 | `s4_label.py` | qwen3.7-max 生成痛点标签 + 分级判断 |
| S5 | `s5_attribute.py` | R1 根因归因（仅 Top 5） |
| S6 | `s6_suggest.py` | qwen3.7-max 生成改进建议 + Listing 卖点 |
| S7 | `s7_report.py` | 报告整合（Markdown 渲染） |

## 当前状态（诚实标注，截至 2026-08-29）

- ✅ 一键启动脚本 `start.bat`、模型自检脚本 `backend/check_models.py` 已就绪
- ✅ 前后端代码与 7 阶段 Pipeline 已完整实现；内置 Seed Demo 数据可完整演示
- ⏳ **真实数据集尚未接入**（`backend/data/raw/` 目前只有 README.md）
- ⏳ **端到端实跑尚未完成**（真实数据 → 真模型调用 → 真报告）
- ⏳ **模型名前缀（是否需 `qwen/`）尚未实测** — 请在有网环境运行 `check_models.py` 后确认

## 诚实边界

- VOC Radar 提供**产品改进和差异化方向的参考信号**，不做"选品决策"
- R1 归因是**辅助参考**，最终决策仍需卖家判断
- 原型阶段数据来源为公开数据集，生产级数据采集为复赛/后续规划
