"""VOC Radar — 真实 Pipeline 端到端一键运行脚本（供本机运行）.

前提（在本机 backend/ 目录下）:
    1) 已建虚拟环境并安装依赖:
         python -m venv .venv && .venv\\Scripts\\python.exe -m pip install -r requirements.txt
    2) .env 已填入真实 MODEL_ROUTER_API_KEY（当前仓库已配个人版 dashscope Key）
    3) 已用 download_dataset.py 把数据集放到 data/raw/（见 download_dataset.py --help）

本脚本会:
    - 初始化数据库（若表已存在则幂等跳过）
    - 自动读取 data/raw/ 下的数据集，取出现有竞品 ASIN 建一个项目
    - 用真实百炼 Key 顺序跑完 s1→s7 七阶段（embedding/qwen-max/deepseek-r1 均为真实 API 调用）
    - 打印每阶段摘要，并给出最终报告文件路径

用法:
    python run_real_pipeline.py
    python run_real_pipeline.py --name "无线耳机真实评论分析" --category "Cell Phones & Accessories"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402  (自动加载 backend/.env)
from app.models.database import get_session, init_db  # noqa: E402
from app.models.schemas import Project  # noqa: E402
from app.services.data_loader import DataLoader  # noqa: E402
from app.pipeline.orchestrator import run_pipeline, EventType  # noqa: E402


def _on_progress(evt: dict) -> None:
    """简单的进度回调（同步），把 SSE 事件打印到终端。"""
    etype = evt.get("event")
    data = evt.get("data", {})
    if etype in (EventType.PROGRESS, EventType.STAGE_DONE, EventType.STAGE_WARNING):
        stage = data.get("stage", "?")
        msg = data.get("message", "")
        out = data.get("output_summary", "")
        line = f"[{etype}] {stage}"
        if msg:
            line += f" - {msg}"
        if out:
            line += f" => {out}"
        print(line)
    elif etype == EventType.ERROR:
        print(f"[ERROR] {data.get('stage')}: {data.get('message')} (code={data.get('error_code')})")
    elif etype == EventType.COMPLETE:
        print(f"[COMPLETE] status={data.get('status')} report={data.get('report_url')}")


def _create_project(name: str, category: str) -> str:
    """读取 data/raw 数据集，建项目并返回 project_id。"""
    loader = DataLoader()
    try:
        reviews = loader.load_dir()
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 读取数据集失败: {e}")
        reviews = []
    asins: list[str] = []
    seen: set[str] = set()
    for r in reviews:
        if r.asin and r.asin not in seen:
            seen.add(r.asin)
            asins.append(r.asin)
        if len(asins) >= 10:  # 取前 10 个竞品 ASIN 即可
            break

    project = Project(
        name=name,
        category=category,
        status="pending",
        progress=0.0,
    )
    project.competitor_asin_list = asins  # 便捷 setter -> JSON
    with get_session() as session:
        session.add(project)
        session.commit()
        pid = project.id
    print(f"[project] 已建项目 id={pid} name={name!r} 竞品ASIN数={len(asins)}")
    return pid


def main() -> int:
    ap = argparse.ArgumentParser(description="VOC Radar 真实 Pipeline 端到端运行")
    ap.add_argument("--name", default="VOC Radar 真实评论分析", help="项目名称")
    ap.add_argument("--category", default="Cell Phones & Accessories", help="品类")
    args = ap.parse_args()

    init_db()  # 幂等建表
    project_id = _create_project(args.name, args.category)

    print(f"[run] 开始真实 Pipeline（调用百炼 API），project_id={project_id}")
    try:
        result = asyncio.run(run_pipeline(project_id, on_progress=_on_progress))
    except Exception as e:  # noqa: BLE001
        print(f"[FATAL] Pipeline 异常: {e}")
        return 1

    print("\n==== Pipeline 结果 ====")
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str))

    report_path = settings.report_dir / f"{project_id}.md"
    print(f"\n[report] 报告文件: {report_path}")
    if report_path.exists():
        print(f"[report] 字符数: {report_path.stat().st_size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
