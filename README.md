# VOC Radar 评论雷达

> AI+跨境黑客松巅峰赛初赛原型 — 自动化评论分析流水线

## 项目简介

VOC Radar 将跨境卖家面对的"上千条竞品评论"转化为可执行的产品改进方向和差异化卖点建议。核心是一条自动化 Prompt 链 Pipeline：采集 → 预处理 → 聚类 → 分级 → 归因 → 建议 → 报告。

## 技术栈

- **后端**：Python 3.11+ / FastAPI / SQLAlchemy / scikit-learn
- **前端**：原生 HTML + Chart.js（深色主题单页应用）
- **数据库**：SQLite（原型零配置）
- **AI 模型**：阿里云百炼 Model Router（OpenAI 兼容格式）
  - `text-embedding-v4`（向量化）
  - `qwen3.7-max`（标签 / 建议 / 分级判断）
  - `deepseek-r1`（Top 5 痛点根因归因）

## 目录结构

```
voc-radar/
├── backend/                # 后端
│   ├── app/
│   │   ├── api/            # FastAPI 路由
│   │   ├── core/           # 配置、日志、异常
│   │   ├── models/         # SQLAlchemy ORM
│   │   ├── pipeline/       # Pipeline 编排 + 各阶段
│   │   ├── services/       # 模型调用 / 聚类 / 采集服务
│   │   └── utils/          # 工具函数
│   ├── data/               # SQLite + 数据集 + 报告
│   ├── logs/               # 日志
│   ├── requirements.txt
│   └── .env.example
├── frontend/               # 前端单页应用
└── docs/                   # PRD / 架构 / API / RUNBOOK
```

## 快速启动

```bash
# 1. 创建虚拟环境（使用项目指定 Python）
C:\Users\32615\.workbuddy\binaries\python\versions\3.13.12\python.exe -m venv .venv
.venv\Scripts\activate

# 2. 安装依赖
pip install -r backend/requirements.txt

# 3. 配置环境变量
copy backend\.env.example backend\.env
# 编辑 backend\.env，填入 MODEL_ROUTER_API_KEY

# 4. 放置 Kaggle 数据集到 backend/data/raw/

# 5. 初始化数据库
python -m app.models.database

# 6. 启动后端
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
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
| S4 | `s4_label.py` | qwen-max 生成痛点标签 + 分级判断 |
| S5 | `s5_attribute.py` | R1 根因归因（仅 Top 5） |
| S6 | `s6_suggest.py` | qwen-max 生成改进建议 + Listing 卖点 |
| S7 | `s7_report.py` | 报告整合（Markdown 渲染） |

## 诚实边界

- VOC Radar 提供**产品改进和差异化方向的参考信号**，不做"选品决策"
- R1 归因是**辅助参考**，最终决策仍需卖家判断
- 原型阶段数据来源为公开数据集，生产级数据采集为复赛/后续规划
