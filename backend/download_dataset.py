"""VOC Radar — 公开 Amazon 评论集下载 + 取样脚本（供本机运行）.

作用:
- 从 McAuley-Lab Amazon Reviews 2023 流式拉取某品类评论（.jsonl.gz），
  只下载前若干行（避免拉取整 GB 文件），随机取样 N 条，
  归一化为 data_loader 可识别的字段，写入 backend/data/raw/。
- 纯标准库实现（urllib + gzip），无需额外依赖；在「有外网」的机器上运行。

用法（在 backend/ 目录下执行）:
    # 默认：手机配件品类，取样 800 条
    python download_dataset.py

    # 指定品类 / 取样量 / 走代理
    python download_dataset.py --category Electronics --sample 1000
    python download_dataset.py --category Cell_Phones_and_Accessories --proxy http://127.0.0.1:26561

字段归一化后输出键（对齐 app/services/data_loader.FIELD_ALIASES）:
    asin, rating, title, text, verified_purchase, helpful_votes, timestamp, parent_asin
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import json
import random
import sys
import urllib.request
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
RAW_DIR = BACKEND_ROOT / "data" / "raw"

MCAULEY = (
    "https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/"
    "raw/review_categories/{category}.jsonl.gz"
)
HUGGINGFACE = (
    "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/"
    "resolve/main/review_categories/{category}.jsonl.gz"
)
# 国内可直连的 HuggingFace 镜像（校园网通常能访问，无需翻墙）
HF_MIRROR = (
    "https://hf-mirror.com/datasets/McAuley-Lab/Amazon-Reviews-2023/"
    "resolve/main/review_categories/{category}.jsonl.gz"
)


def _stream_jsonl(url: str, max_lines: int, proxy: str | None):
    """流式下载 gzip jsonl，逐行 yield 解析后的 dict，最多 max_lines 行后停止。"""
    if proxy:
        handler = urllib.request.ProxyHandler({"https": proxy, "http": proxy})
        urllib.request.install_opener(urllib.request.build_opener(handler))
    req = urllib.request.Request(url, headers={"User-Agent": "VOC-Radar/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        with gzip.GzipFile(fileobj=resp) as gz:
            for i, raw in enumerate(gz):
                if i >= max_lines:
                    break
                line = raw.decode("utf-8", "ignore").strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def _normalize(o: dict) -> dict | None:
    ts = o.get("sort_timestamp") or o.get("timestamp")
    date = None
    if ts:
        try:
            date = datetime.datetime.utcfromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d")
        except (ValueError, TypeError, OSError):
            date = None
    rec = {
        "asin": (o.get("asin") or o.get("parent_asin") or "").strip(),
        "rating": o.get("rating"),
        "title": (o.get("title") or "").strip(),
        "text": (o.get("text") or "").strip(),
        "verified_purchase": o.get("verified_purchase"),
        "helpful_votes": o.get("helpful_votes") or o.get("helpful_vote") or 0,
        "timestamp": date,
        "parent_asin": (o.get("parent_asin") or "").strip(),
    }
    try:
        rec["rating"] = int(float(rec["rating"]))
    except (TypeError, ValueError):
        rec["rating"] = 0
    if rec["asin"] and rec["text"]:
        return rec
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="下载并取样公开 Amazon 评论集")
    ap.add_argument("--category", default="Cell_Phones_and_Accessories",
                    help="Amazon Reviews 2023 品类名，如 Cell_Phones_and_Accessories / Electronics / Books")
    ap.add_argument("--sample", type=int, default=800, help="最终取样条数（仅 random 模式生效）")
    ap.add_argument("--max-lines", type=int, default=300000, help="最多下载的解压行数（控制流量）")
    ap.add_argument("--mode", choices=("competitor", "random"), default="competitor",
                    help="competitor=按竞品聚合（取评论最多的前 N 个 ASIN，VOC Radar 需要此结构）；random=随机取样")
    ap.add_argument("--competitors", type=int, default=10, help="competitor 模式：取评论数最多的前 N 个 ASIN")
    ap.add_argument("--per-asin", type=int, default=80, help="competitor 模式：每个 ASIN 最多取多少条")
    ap.add_argument("--seed", type=int, default=42, help="随机种子")
    ap.add_argument("--proxy", default=None, help="可选 HTTP/HTTPS 代理，如 http://127.0.0.1:26561")
    ap.add_argument("--out", default=None, help="输出 jsonl 路径（默认 data/raw/amazon_<品类>_reviews.jsonl）")
    args = ap.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else RAW_DIR / f"amazon_{args.category}_reviews.jsonl"

    rows: list[dict] = []
    last_err = None
    for tmpl in (MCAULEY, HUGGINGFACE, HF_MIRROR):
        url = tmpl.format(category=args.category)
        print(f"[download] 尝试: {url}")
        try:
            for o in _stream_jsonl(url, args.max_lines, args.proxy):
                rec = _normalize(o)
                if rec:
                    rows.append(rec)
            if rows:
                break
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"[download] 失败: {e}")
            continue

    if not rows:
        print(f"[error] 未获取到任何评论（最后错误: {last_err}）")
        return 1

    random.seed(args.seed)

    if args.mode == "competitor":
        # VOC Radar 需要「少数竞品 × 每品多条评论」的结构；随机取样会把评论打散到
        # 成百上千个 ASIN 上（每品仅 1 条），导致 s3 聚类无法进行。故按 ASIN 聚合取样。
        buckets: dict[str, list[dict]] = {}
        for r in rows:
            b = buckets.setdefault(r["asin"], [])
            if len(b) < args.per_asin * 2:  # 单品限流，控制内存
                b.append(r)
        ranked = sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True)
        top = ranked[: max(1, args.competitors)]
        sample = []
        for _asin, items in top:
            random.shuffle(items)
            sample.extend(items[: args.per_asin])
        random.shuffle(sample)
        print(f"[取样] competitor 模式：共 {len(buckets)} 个 ASIN，取评论最多的前 {len(top)} 个竞品")
        for asin, items in top:
            print(f"    {asin}: 命中 {len(items)} 条 -> 取用 {min(len(items), args.per_asin)} 条")
    else:
        random.shuffle(rows)
        sample = rows[: max(1, args.sample)]

    neg = [r for r in sample if (r["rating"] or 5) <= 3]

    with open(out_path, "w", encoding="utf-8") as f:
        for r in sample:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[ok] 解析 {len(rows)} 条 -> 取样 {len(sample)} 条"
          f"（差评 rating<=3: {len(neg)}，覆盖 {len({r['asin'] for r in sample})} 个竞品 ASIN）")
    print(f"[ok] 已写入: {out_path}")
    print(f"[next] 在本机 backend/ 下执行: python run_real_pipeline.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
