"""VOC Radar 演示视频录制（完整版，约 2 分钟）.

相比 capture_demo.py 的简版流程（仅 18 秒），本脚本编排了完整演示节奏：
空态 → 加载看板 → 滚动看板全貌 → 下钻 Top1/Top2 痛点 → 滚动详情
→ 打开报告 → 滚动报告全文 → 收尾停留。

前置：后端已启动（uvicorn app.main:app --port 8000）。
用法：python capture_video.py --project <项目ID>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:8000"
VIDEO_DIR = Path(r"E:\projects\voc-radar\_video_tmp")
VIEWPORT = {"width": 1600, "height": 1000}


async def scroll(page, times: int, dy: int = 380, wait: int = 1500) -> None:
    """缓慢滚动，模拟人工浏览."""
    for _ in range(times):
        await page.mouse.wheel(0, dy)
        await page.wait_for_timeout(wait)


async def ensure_closed(page) -> None:
    """关闭可能打开的详情面板/报告弹层."""
    await page.evaluate(
        """() => {
            const A = window.VOC_App;
            if (!A) return;
            const d = A.components && A.components.detailPanel;
            if (d && typeof d.close === 'function') d.close();
            const r = A.components && A.components.reportView;
            if (r && typeof r.close === 'function') r.close();
        }"""
    )
    await page.wait_for_timeout(700)
    for sel in ("#detailPanel .detail-close", "#reportModal .report-close"):
        loc = page.locator(sel).first
        if await page.locator(sel).count() and await loc.is_visible():
            await loc.click()
            await page.wait_for_timeout(700)


async def open_pain_point(page, idx: int) -> bool:
    """下钻第 idx 个（按影响面排序）痛点."""
    pp_id = await page.evaluate(
        """(i) => {
            const h = window.VOC_App.state.overview?.heatmap || [];
            return h.length > i ? h[i].pain_point_id : null;
        }""",
        idx,
    )
    if not pp_id:
        return False
    await page.evaluate(
        "(id) => window.VOC_App.components.detailPanel.open(id)", pp_id
    )
    await page.wait_for_selector("#detailPanel:not([hidden])", timeout=20000)
    await page.wait_for_timeout(3500)
    return True


async def main_async(project_id: str) -> int:
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=1,
            locale="zh-CN",
            record_video_dir=str(VIDEO_DIR),
            record_video_size=VIEWPORT,
        )
        page = await ctx.new_page()

        # 1) 空态开场
        await page.goto(BASE_URL, wait_until="networkidle")
        await page.wait_for_timeout(3500)

        # 2) 加载真实项目 → 看板
        await page.evaluate("(pid) => window.VOC_App.loadOverview(pid)", project_id)
        await page.wait_for_selector("#dashboard:not([hidden])", timeout=30000)
        await page.wait_for_timeout(5000)

        # 3) 滚动看板全貌（KPI → 热力图 → 矩阵 → 卖点清单）
        await scroll(page, 8, dy=380, wait=1600)
        await page.evaluate("() => window.scrollTo({top: 0, behavior: 'smooth'})")
        await page.wait_for_timeout(2500)

        # 4) 下钻 Top1 痛点
        if await open_pain_point(page, 0):
            await scroll(page, 5, dy=360, wait=1500)
            await ensure_closed(page)

        # 5) 下钻 Top2 痛点
        await page.evaluate("() => window.scrollTo({top: 0, behavior: 'smooth'})")
        await page.wait_for_timeout(1500)
        if await open_pain_point(page, 1):
            await scroll(page, 4, dy=360, wait=1400)
            await ensure_closed(page)

        # 6) 报告预览 + 滚动全文
        await page.evaluate("() => window.scrollTo({top: 0, behavior: 'smooth'})")
        await page.wait_for_timeout(1500)
        await page.click("#viewReportBtn")
        await page.wait_for_selector("#reportModal:not([hidden])", timeout=20000)
        await page.wait_for_timeout(4000)
        await scroll(page, 14, dy=360, wait=1400)

        # 7) 收尾停留
        await page.wait_for_timeout(3500)

        await ctx.close()  # 关闭后视频才落盘
        await browser.close()

    vids = sorted(VIDEO_DIR.glob("*.webm"), key=lambda f: f.stat().st_mtime)
    if vids:
        print(f"[ok] 录屏已生成: {vids[-1]}")
    else:
        print("[warn] 未找到录屏文件")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="VOC Radar 演示视频录制")
    ap.add_argument("--project", default=None)
    args = ap.parse_args()

    pid = args.project
    if not pid:
        with urllib.request.urlopen(f"{BASE_URL}/api/v1/projects", timeout=15) as r:
            items = json.load(r)["data"]["items"]
        done = [x for x in items if x.get("status") == "completed"]
        if not done:
            print("[error] 没有 completed 项目")
            return 1
        pid = done[-1]["id"]
    print(f"[项目] {pid}")
    return asyncio.run(main_async(pid))


if __name__ == "__main__":
    sys.exit(main())
