"""R1 vs qwen-max 归因对比实验.

作用
----
对同一批痛点、用**完全相同的 prompt**（复用 s5_attribute 的 build_messages 与
OUTPUT_SCHEMA），分别调用 deepseek-r1 与 qwen3.7-max 做根因归因，输出对比结果。

这是复赛/决赛「技术思路」维度的关键证据：文档承诺用对比实验回应
「R1 真比 max 好吗」这一质疑，本脚本即该实验的可复现载体。

用法（在 backend/ 目录下执行）
------------------------------
    python compare_r1_qwen.py                 # 默认对 Top2 痛点做对比
    python compare_r1_qwen.py --top 3         # 对 Top3 痛点做对比
    python compare_r1_qwen.py --project <id>  # 指定项目（默认取最新的 completed 项目）

输出
----
- 终端打印对比表格
- 结果落盘：data/reports/r1_vs_qwen_compare.json / .md
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.models.database import get_session  # noqa: E402
from app.models.schemas import PainPoint, Project, Review  # noqa: E402
from app.pipeline.prompts import r1_attribution as r1_prompts  # noqa: E402
from app.services.model_router import get_model_router  # noqa: E402
from app.pipeline.stages.s5_attribute import _review_to_dict  # noqa: E402

OUT_DIR = BACKEND_ROOT / "data" / "reports"


def _pick_project(project_id: str | None) -> Project:
    """取指定项目，或最新的 completed 项目."""
    with get_session() as session:
        if project_id:
            p = session.get(Project, project_id)
            if not p:
                raise SystemExit(f"找不到项目: {project_id}")
        else:
            rows = (
                session.execute(select(Project).where(Project.status == "completed"))
                .scalars()
                .all()
            )
            if not rows:
                raise SystemExit("没有 status=completed 的项目，请先跑通 Pipeline")
            p = rows[-1]  # SQLite 按插入顺序，取最后一个
        session.expunge(p)
        return p


def _select_pain_points(project_id: str, top: int) -> list[PainPoint]:
    with get_session() as session:
        pts = (
            session.execute(
                select(PainPoint)
                .where(PainPoint.project_id == project_id)
                .order_by(PainPoint.rank_by_impact.asc())
            )
            .scalars()
            .all()
        )
        picked = [p for p in pts if p.suitable_for_reasoning][:top]
        if not picked:
            picked = list(pts)[:top]
        session.expunge_all()
        return list(picked)


def _fetch_reviews(project_id: str, cluster_id: int, top_n: int = 10) -> list[Review]:
    with get_session() as session:
        rows = (
            session.execute(
                select(Review)
                .where(Review.project_id == project_id)
                .where(Review.cluster_id == cluster_id)
                .order_by(Review.is_representative.desc(), Review.helpful_votes.desc())
                .limit(top_n)
            )
            .scalars()
            .all()
        )
        session.expunge_all()
        return list(rows)


async def _call(model: str, messages: list[dict]) -> dict:
    """调用指定模型做 JSON 归因，返回 {ok, data|error, latency_ms}."""
    client = get_model_router()
    start = time.time()
    try:
        data = await client.chat_json(
            messages=messages,
            model=model,
            schema=r1_prompts.OUTPUT_SCHEMA,
            temperature=0.3,
        )
        return {"ok": True, "data": data, "latency_ms": int((time.time() - start) * 1000)}
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"{e.__class__.__name__}: {e}",
            "latency_ms": int((time.time() - start) * 1000),
        }


def _metrics(data: dict) -> dict:
    """从归因结果里提取可量化指标."""
    if not isinstance(data, dict):
        return {}
    cause = data.get("root_cause") or ""
    evidence = data.get("evidence") or []
    measures = data.get("improvement_measures") or []
    cited = 0
    for e in evidence:
        if isinstance(e, dict) and (e.get("review_id") or e.get("quote")):
            cited += 1
    return {
        "root_cause_len": len(str(cause)),
        "evidence_count": len(evidence),
        "evidence_cited": cited,
        "measures_count": len(measures),
        "root_cause": str(cause),
    }


def _fmt_pct(v) -> str:
    """影响面格式化：兼容 0.181 与 18.1 两种存储方式."""
    if v is None:
        return "-"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{f * 100:.1f}%" if f <= 1 else f"{f:.1f}%"


async def main_async(args) -> int:
    project = _pick_project(args.project)
    print(f"[项目] {project.name}  ({project.id})")
    pain_points = _select_pain_points(project.id, args.top)
    print(f"[对比] 将对 {len(pain_points)} 个痛点分别用 deepseek-r1 与 {settings.MODEL_LLM} 归因\n")

    results = []
    for idx, pp in enumerate(pain_points, 1):
        reviews = _fetch_reviews(project.id, pp.cluster_id, top_n=args.reviews)
        review_dicts = [_review_to_dict(r) for r in reviews]
        messages = r1_prompts.build_messages(
            label=pp.label,
            description=pp.description or "",
            reviews=review_dicts,
            vision_tags=None,
            top_n=len(review_dicts),
        )
        print(f"--- ({idx}/{len(pain_points)}) {pp.label} "
              f"（影响面 {_fmt_pct(pp.impact_ratio)}，{len(review_dicts)} 条证据评论）---")

        r1 = await _call(settings.MODEL_R1, messages)
        print(f"    deepseek-r1 : {'OK' if r1['ok'] else 'FAIL'}  {r1['latency_ms']}ms")
        qw = await _call(settings.MODEL_LLM, messages)
        print(f"    {settings.MODEL_LLM} : {'OK' if qw['ok'] else 'FAIL'}  {qw['latency_ms']}ms")

        results.append(
            {
                "pain_point_id": pp.id,
                "label": pp.label,
                "impact_ratio": pp.impact_ratio,
                "review_count": len(review_dicts),
                "r1": {**r1, **(_metrics(r1.get("data", {})) if r1["ok"] else {})},
                "qwen": {**qw, **(_metrics(qw.get("data", {})) if qw["ok"] else {})},
            }
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "r1_vs_qwen_compare.json"
    md_path = OUT_DIR / "r1_vs_qwen_compare.md"

    json_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ---- Markdown 报告 ----
    lines = [
        "# R1 vs qwen-max 归因对比实验",
        "",
        f"> 项目：{project.name}（`{project.id}`）  ",
        f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"> 对比模型：`deepseek-r1` vs `{settings.MODEL_LLM}`  ",
        "> 实验设计：同一痛点、**完全相同的 prompt** 与输出 schema，分别调用两个模型",
        "",
        "## 量化对比",
        "",
        "| 痛点 | 影响面 | 模型 | 结果 | 耗时 | 根因字数 | 证据条数 | 含引用 | 改进措施 |",
        "|------|--------|------|------|------|----------|----------|--------|----------|",
    ]
    for r in results:
        head = f"| {r['label']} | {_fmt_pct(r['impact_ratio'])} "
        for key, name in (("r1", "deepseek-r1"), ("qwen", settings.MODEL_LLM)):
            d = r[key]
            if d["ok"]:
                lines.append(
                    head + f"| {name} | OK | {d['latency_ms']}ms | "
                    f"{d.get('root_cause_len', '-')} | {d.get('evidence_count', '-')} | "
                    f"{d.get('evidence_cited', '-')} | {d.get('measures_count', '-')} |"
                )
            else:
                lines.append(head + f"| {name} | FAIL | {d['latency_ms']}ms | - | - | - | - |")

    lines += ["", "## 根因文本对比", ""]
    for r in results:
        lines += [f"### {r['label']}", ""]
        for key, name in (("r1", "deepseek-r1"), ("qwen", settings.MODEL_LLM)):
            d = r[key]
            lines.append(f"**{name}** ({d['latency_ms']}ms)")
            lines.append("")
            if d["ok"]:
                lines.append(f"> {d.get('root_cause', '(空)')}")
            else:
                lines.append(f"> 调用失败：{d.get('error', '未知')}")
            lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")

    print("\n=== 对比汇总 ===")
    print(f"{'痛点':<14}{'模型':<16}{'结果':<6}{'耗时':>9}{'根因字数':>9}{'证据':>6}{'措施':>6}")
    for r in results:
        for key, name in (("r1", "deepseek-r1"), ("qwen", settings.MODEL_LLM)):
            d = r[key]
            if d["ok"]:
                print(f"{r['label'][:12]:<14}{name:<16}{'OK':<6}"
                      f"{d['latency_ms']:>8}ms{d.get('root_cause_len', 0):>9}"
                      f"{d.get('evidence_count', 0):>6}{d.get('measures_count', 0):>6}")
            else:
                print(f"{r['label'][:12]:<14}{name:<16}{'FAIL':<6}{d['latency_ms']:>8}ms")
    print(f"\n[ok] 已写入: {json_path}")
    print(f"[ok] 已写入: {md_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="R1 vs qwen-max 归因对比实验")
    ap.add_argument("--project", default=None, help="项目 ID（默认取最新的 completed 项目）")
    ap.add_argument("--top", type=int, default=2, help="对前 N 个痛点做对比")
    ap.add_argument("--reviews", type=int, default=10, help="每个痛点取多少条代表性评论")
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
