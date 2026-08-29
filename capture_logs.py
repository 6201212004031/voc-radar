"""生成 shot_04 / shot_05：真实调用日志与模型对比实验截图.

shot_04_api_test.png —— check_models.py 的真实调用输出（终端风格）
shot_05_r1_compare.png —— R1 vs qwen-max 对比实验报告（Markdown 渲染）

前置：后端无需启动；需要联网加载 marked.js（CDN）。
用法：python capture_logs.py
"""
from __future__ import annotations

import asyncio
import html
import sys
from pathlib import Path

from playwright.async_api import async_playwright

SHOT_DIR = Path(r"C:\Users\32615\WorkBuddy\2026-07-17-17-59-37\voc-radar-screenshots")
BACKEND = Path(r"E:\projects\voc-radar\backend")

LOG_FILE = BACKEND / "data" / "reports" / "model_check_log.txt"
CMP_FILE = BACKEND / "data" / "reports" / "r1_vs_qwen_compare.md"

VIEWPORT = {"width": 1600, "height": 1000}

TERMINAL_CSS = """
  * { box-sizing: border-box; }
  body { background:#0d1117; color:#c9d1d9; margin:0; padding:28px 32px;
         font-family:'Cascadia Mono','JetBrains Mono',Consolas,'Courier New',monospace;
         font-size:13px; line-height:1.65; }
  pre { margin:0; white-space:pre-wrap; word-break:break-word; }
  h1,h2 { color:#58a6ff; border-bottom:1px solid #30363d; padding-bottom:8px; }
  h3 { color:#7ee787; }
  table { border-collapse:collapse; width:100%; margin:12px 0; font-size:12.5px; }
  th,td { border:1px solid #30363d; padding:7px 10px; text-align:left; }
  th { background:#161b22; color:#58a6ff; }
  code { color:#ffa657; }
  blockquote { margin:8px 0; padding-left:14px; border-left:3px solid #30363d; color:#8b949e; }
  .hdr { background:#161b22; color:#7ee787; padding:10px 14px; margin:-28px -32px 18px -32px;
         border-bottom:1px solid #30363d; font-weight:bold; }
"""


def _terminal_page(title: str, body_html: str) -> str:
    return (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        f"<style>{TERMINAL_CSS}</style></head><body>"
        f"<div class='hdr'>{html.escape(title)}</div>{body_html}</body></html>"
    )


async def main_async() -> int:
    if not LOG_FILE.exists():
        print(f"[error] 缺少日志: {LOG_FILE}")
        return 1
    if not CMP_FILE.exists():
        print(f"[error] 缺少对比报告: {CMP_FILE}")
        return 1

    log_text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
    cmp_text = CMP_FILE.read_text(encoding="utf-8", errors="replace")

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(
            viewport=VIEWPORT, device_scale_factor=2, locale="zh-CN"
        )
        page = await ctx.new_page()

        # ---- shot_04：终端风格日志 ----
        await page.set_content(
            _terminal_page(
                "VOC Radar · 模型连通性自检（check_models.py 真实调用输出）",
                f"<pre>{html.escape(log_text)}</pre>",
            )
        )
        await page.wait_for_timeout(1200)
        await page.screenshot(path=str(SHOT_DIR / "shot_04_api_test.png"))
        print("      ✓ shot_04_api_test.png")

        # ---- shot_05：对比实验报告（marked 渲染）----
        await page.set_content(
            "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
            f"<style>{TERMINAL_CSS}</style>"
            '<script src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script>'
            "</head><body>"
            "<div class='hdr'>VOC Radar · R1 vs qwen-max 归因对比实验（Top5 全样本 · 真实调用）</div>"
            "<div id='md'></div></body></html>"
        )
        # 等 marked.js 就绪；内容用 evaluate 传参，避免 JS 字符串转义问题
        await page.wait_for_function(
            "() => typeof window.marked !== 'undefined'", timeout=25000
        )
        await page.evaluate(
            "(md) => { document.getElementById('md').innerHTML = marked.parse(md); }",
            cmp_text,
        )
        await page.wait_for_function(
            "() => document.querySelector('#md h1')", timeout=20000
        )
        await page.wait_for_timeout(1500)
        await page.screenshot(
            path=str(SHOT_DIR / "shot_05_r1_compare.png"), full_page=True
        )
        print("      ✓ shot_05_r1_compare.png")

        await ctx.close()
        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
