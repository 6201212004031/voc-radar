"""Pipeline 各阶段 Prompt 模板.

模块组织:
- labels.py             痛点标签生成（s4_label）
- r1_attribution.py     R1 根因归因（s5_attribute）
- suggestions.py        改进建议生成（s6_suggest）
- listing.py            Listing 卖点建议（s6_suggest）

每个模块导出:
- SYSTEM_PROMPT   系统提示
- USER_TEMPLATE   用户消息模板（Python str.format 或 Jinja2）
- OUTPUT_SCHEMA   期望的 JSON 输出 schema（用于 prompt 提示）

所有模板都用中文输出（保留评论原文为英文/原始语言）。
"""
from app.pipeline.prompts import labels, listing, r1_attribution, suggestions

__all__ = ["labels", "r1_attribution", "suggestions", "listing"]
