"""VOC Radar 演示素材自动生成：真实数据截图 + 全流程录屏.

用途
----
复赛/决赛需要展示「真实数据 + 真实 API」跑出来的看板，而仓库里的旧截图（2026-08-13）
全部基于 Seed Demo 合成数据。本脚本驱动真实运行的后端，用 Playwright 自动：

  1. shot_01_dashboard.png —— 看板首页（KPI + 痛点热力图 + 优先级矩阵 + 卖点清单）
  2. shot_02_detail.png    —— Top1 痛点下钻详情（根因归因 + 评论证据 + 竞品对比）
  3. shot_03_report.png    —— 结构化报告预览
  4. 全流程录屏（.webm）—— 看板 → 下钻 → 报告 的完整操作流

前置条件
--------
- 后端已启动：`uvicorn app.main:app --host 127.0.0.1 --port 8000`（backend/ 目录下）
- 已存在 status=completed 的项目（默认取最新的那个，可用 --project 指定）

用法
----
    python capture_demo.py
    python capture_demo.py --project <项目ID>
    python capture_demo.py --no-video     # 只截图，不录屏
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:8000"
SHOT_DIR = Path(r"C:\Users\32615\WorkBuddy\2026-07-17-17-59-37\voc-radar-screenshots")
VIDEO_DIR = Path(r"E:\projects\voc-radar\_video_tmp")

VIEWPORT = {"width": 1600, "height": 1000}


async def _render_flow(page, tag: str, pace: float = 1.0) -> None:
    """走一遍演示流程：看板 → 下钻 → 报告."""
    await page.goto(BASE_URL, wait_until="networkidle")

    # 加载真实项目（前端暴露了调试入口 window.VOC_App）
    await page.evaluate("(pid) => window.VOC_App.loadOverview(pid)", PROJECT_ID)
    await page.wait_for_selector("#dashboard:not([hidden])", timeout=30000)
    await page.wait_for_timeout(int(2600 * pace))  # 等图表动画

    # 取 Top1 痛点（heatmap 已按影响面排序）
    pp_id = await page.evaluate(
        """() => {
            const h = window.VOC_App.state.overview?.heatmap || [];
            return h.length ? h[0].pain_point_id : null;
        }"""
    )
    if not pp_id:
        raise RuntimeError("未取到痛点 ID（overview.heatmap 为空）")

    # 下钻详情
    await page.evaluate(
        "(id) => window.VOC_App.components.detailPanel.open(id)", pp_id
    )
    await page.wait_for_selector("#detailPanel:not([hidden])", timeout=20000)
    await page.wait_for_timeout(int(2600 * pace))

    # 关闭下钻（兼容 close() 方法与 DOM 按钮两种实现）
    await page.evaluate(
        """() => {
            const d = window.VOC_App.components.detailPanel;
            if (d && typeof d.close === 'function') { d.close(); }
        }"""
    )
    await page.wait_for_timeout(int(600 * pace))
    if await page.locator("#detailPanel .detail-close").count():
        if await page.locator("#detailPanel .detail-close").first.is_visible():
            await page.locator("#detailPanel .detail-close").first.click()
            await page.wait_for_timeout(int(600 * pace))

    # 报告预览
    await page.click("#viewReportBtn")
    await page.wait_for_selector("#reportModal:not([hidden])", timeout=20000)
    await page.wait_for_timeout(int(3000 * pace))


async def main_async(args) -> int:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch()

        # ---------- 1) 高清截图 ----------
        print("[1/2] 生成截图（2x 高清）...")
        shot_ctx = await browser.new_context(
            viewport=VIEWPORT, device_scale_factor=2, locale="zh-CN"
        )
        page = await shot_ctx.new_page()
        try:
            await _render_flow(page, "shot")

            await page.evaluate(
                """() => {
                    const d = window.VOC_App.components.detailPanel;
                    if (d && typeof d.close === 'function') d.close();
                }"""
            )
            # 回到看板：关闭报告弹层
            if await page.locator("#reportModal .report-close").first.is_visible():
                await page.locator("#reportModal .report-close").first.click()
            await page.wait_for_timeout(1800)
            await page.screenshot(path=str(SHOT_DIR / "shot_01_dashboard.png"))
            print("      ✓ shot_01_dashboard.png")

            # 重新下钻截图
            pp_id = await page.evaluate(
                """() => {
                    const h = window.VOC_App.state.overview?.heatmap || [];
                    return h.length ? h[0].pain_point_id : null;
                }"""
            )
            await page.evaluate(
                "(id) => window.VOC_App.components.detailPanel.open(id)", pp_id
            )
            await page.wait_for_selector("#detailPanel:not([hidden])", timeout=20000)
            await page.wait_for_timeout(2600)
            await page.screenshot(path=str(SHOT_DIR / "shot_02_detail.png"))
            print("      ✓ shot_02_detail.png")

            await page.evaluate(
                """() => {
                    const d = window.VOC_App.components.detailPanel;
                    if (d && typeof d.close === 'function') d.close();
                }"""
            )
            await page.wait_for_timeout(800)
            await page.click("#viewReportBtn")
            await page.wait_for_selector("#reportModal:not([hidden])", timeout=20000)
            await page.wait_for_timeout(3000)
            await page.screenshot(path=str(SHOT_DIR / "shot_03_report.png"))
            print("      ✓ shot_03_report.png")
        except Exception as e:  # noqa: BLE001
            print(f"      [error] 截图流程失败: {e}")
            await shot_ctx.close()
            await browser.close()
            return 1
        await shot_ctx.close()

        # ---------- 2) 全流程录屏 ----------
        if not args.no_video:
            print("[2/2] 录制全流程视频（节奏放慢，便于观看）...")
            vid_ctx = await browser.new_context(
                viewport=VIEWPORT,
                device_scale_factor=1,
                locale="zh-CN",
                record_video_dir=str(VIDEO_DIR),
                record_video_size=VIEWPORT,
            )
            vpage = await vid_ctx.new_page()
            try:
                await _render_flow(vpage, "video", pace=1.6)
            except Exception as e:  # noqa: BLE001
                print(f"      [error] 录屏流程失败: {e}")
            await vid_ctx.close()  # 关闭后视频才落盘

        await browser.close()

    if not args.no_video:
        vids = sorted(VIDEO_DIR.glob("*.webm"), key=lambda f: f.stat().st_mtime)
        if vids:
            print(f"\n[ok] 录屏已生成: {vids[-1]}")
        else:
            print("\n[warn] 未找到录屏文件")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="VOC Radar 演示素材自动生成")
    ap.add_argument("--project", default=None, help="项目 ID（默认取最新的 completed 项目）")
    ap.add_argument("--no-video", action="store_true", help="只截图，不录屏")
    args = ap.parse_args()

    global PROJECT_ID
    if args.project:
        PROJECT_ID = args.project
    else:
        import urllib.request

        with urllib.request.urlopen(f"{BASE_URL}/api/v1/projects", timeout=15) as r:
            import json

            data = json.load(r)
        done = [p for p in data["data"]["items"] if p.get("status") == "completed"]
        if not done:
            print("[error] 没有 completed 的项目，请先跑通 Pipeline")
            return 1
        PROJECT_ID = done[-1]["id"]
    print(f"[项目] {PROJECT_ID}")
    return asyncio.run(main_async(args))


PROJECT_ID = ""

if __name__ == "__main__":
    sys.exit(main())
