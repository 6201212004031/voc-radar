#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""VOC Radar — 模型连通性自检脚本.

用途
----
一条命令确认「哪个模型名 + 哪个 Base URL」组合真正可用，重点解决官方参赛指南
与本项目 .env 之间的**模型命名前缀疑点**：

- 官方指南（2026-07-24 版）6.2 节模型清单写作带前缀形式，例如
  ``qwen/qwen3.7-max``、``qwen/text-embedding-v4``；
- 本项目 ``backend/.env`` 里配置的是无前缀形式，例如 ``qwen3.7-max``。

前缀到底是否必需，不能靠猜。本脚本对**同一个模型同时测试无前缀与带前缀两种
写法**，一次跑完即可得出结论，并直接给出建议写入 .env 的模型名。

测试方式（最小成本真实调用）
----------------------------
- 对话类模型：发送一条极短消息 ``hi``，``max_tokens=16``；
- 向量类模型：对短文本 ``hello voc radar`` 做一次 embedding。

每个模型超时上限 30 秒，失败不中断，最后输出汇总表格与明确结论。

用法
----
::

    # 最常用：直接跑，读 backend/.env 里的 Key 与 Base URL
    .\\.venv\\Scripts\\python.exe backend\\check_models.py

    # 对比测试赛方 Model Router 通道（用赛方 Key 与赛方额度）
    .\\.venv\\Scripts\\python.exe backend\\check_models.py ^
        --base-url https://model-router.edu-aliyun.com/v1 ^
        --api-key sk-xxxxxx

    # 对比测试阿里云百炼直连通道（个人 Key，自费）
    .\\.venv\\Scripts\\python.exe backend\\check_models.py ^
        --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 ^
        --api-key sk-xxxxxx

    # 追加测试额外前缀 / 额外模型
    .\\.venv\\Scripts\\python.exe backend\\check_models.py --extra-prefix qwen2/ --model qwen/qwq-plus

退出码
------
- ``0``：至少有一个模型调用成功（通道连通）；
- ``1``：全部模型调用失败（通道不通 / Key 无效）；
- ``2``：前置条件不满足（未配置 Key、缺少 openai 库等）。

安全说明
--------
脚本**不会**在任何输出中打印完整的 API Key，仅显示脱敏后的形式（如
``sk-abc1********wxyz``）。也不要把 Key 写进命令行历史之外的任何文件。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- 常量配置

#: 脚本所在目录（backend/），.env 与脚本同级
BACKEND_DIR = Path(__file__).resolve().parent

#: 默认 .env 路径
DEFAULT_ENV_FILE = BACKEND_DIR / ".env"

#: 赛方 Model Router（官方指南指定，走赛方发放的 25000 Credits 额度）
OFFICIAL_BASE_URL = "https://model-router.edu-aliyun.com/v1"

#: 阿里云百炼直连（走个人 Key，自费）
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

#: 待测试的基础模型名（不含前缀）与其在本项目中的角色说明
#: 来源：官方参赛指南 6.2 节模型清单 + 本项目 config.py 默认值
CANDIDATE_MODELS: list[tuple[str, str]] = [
    ("text-embedding-v4", "向量化 / 语义聚类"),
    ("qwen3.7-max", "痛点标签 / 改进建议 / 报告"),
    ("qwen3.5-flash", "评论粗筛分类 / 刷评初判"),
    ("qwen3-vl-plus", "带图评论视觉理解"),
    ("deepseek-r1", "Top5 痛点根因归因"),
]

#: 默认测试的前缀组合：无前缀 + 官方写法前缀
DEFAULT_PREFIXES: list[str] = ["", "qwen/"]

#: 判定为「向量类模型」的关键词
EMBEDDING_KEYWORDS: tuple[str, ...] = ("embedding", "text-embedding", "rerank")

#: 单个模型的超时上限（秒）
DEFAULT_TIMEOUT_SECONDS = 30.0

#: 占位 Key 特征（来自 .env.example，出现即视为未真正填写）
PLACEHOLDER_KEY_HINTS: tuple[str, ...] = (
    "your-personal",
    "your-key",
    "sk-your",
    "changeme",
    "xxx",
)

#: 错误信息最大展示长度
MAX_ERROR_MESSAGE_LEN = 46


# ---------------------------------------------------------------- 数据结构


@dataclass
class ProbeResult:
    """单个模型名的探测结果."""

    model: str
    base_model: str
    prefix: str
    kind: str  # "embedding" 或 "chat"
    ok: bool = False
    elapsed: float = 0.0
    error_code: str = ""
    error_message: str = ""
    error_category: str = ""  # AUTH / NOT_FOUND / RATE_LIMIT / TIMEOUT / ...
    detail: str = ""

    def as_row(self) -> list[str]:
        """转换为表格行."""
        return [
            self.model,
            self.kind,
            "OK" if self.ok else "FAIL",
            f"{self.elapsed:.2f}s",
            self.error_code if not self.ok else "-",
            (self.detail if self.ok else self.error_message) or "-",
        ]


@dataclass
class ModelRecommendation:
    """单个基础模型名的命名建议（供结论与 .env 片段生成使用）."""

    base_model: str
    plain_ok: bool
    prefixed_ok: bool
    recommended: str  # 建议写入 .env 的模型名；不可用则为空字符串
    note: str  # 人类可读的说明

    @property
    def plain_text(self) -> str:
        """无前缀写法的探测结果文案."""
        return "OK" if self.plain_ok else "FAIL"

    @property
    def prefixed_text(self) -> str:
        """带 qwen/ 前缀写法的探测结果文案."""
        return "OK" if self.prefixed_ok else "FAIL"


@dataclass
class EnvConfig:
    """从 .env / 环境变量 / 命令行解析出的运行配置."""

    api_key: str = ""
    base_url: str = ""
    api_key_source: str = ""
    base_url_source: str = ""
    env_file: Path = DEFAULT_ENV_FILE
    env_file_exists: bool = False
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 工具函数


def _safe_reconfigure_stdout() -> None:
    """尽量把标准输出切到 UTF-8，避免 Windows GBK 控制台出现乱码."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - 非关键路径，失败就沿用默认编码
        pass


def mask_secret(value: str) -> str:
    """对 API Key 做脱敏，只保留前 6 位与后 4 位.

    Args:
        value: 原始密钥字符串。

    Returns:
        脱敏后的字符串，例如 ``sk-abc1********wxyz``；空值返回 ``(未配置)``。
    """
    if not value:
        return "(未配置)"
    if len(value) <= 12:
        return f"{value[:2]}{'*' * max(len(value) - 2, 0)}"
    return f"{value[:6]}{'*' * 8}{value[-4:]}"


def looks_like_placeholder(value: str) -> bool:
    """判断 Key 是否仍是模板占位值."""
    lowered = value.strip().lower()
    if not lowered:
        return True
    return any(hint in lowered for hint in PLACEHOLDER_KEY_HINTS)


def parse_env_file(path: Path) -> dict[str, str]:
    """手工解析 .env 文件（不依赖 python-dotenv，避免新增依赖）.

    支持 ``KEY=VALUE``、``export KEY=VALUE``、``# 注释``、空行，
    并去除成对引号。文件不存在或读取失败时返回空字典。

    Args:
        path: .env 文件路径。

    Returns:
        键值字典。
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return values

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        # 去掉行尾注释（仅处理未加引号的情况）
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        if key:
            values[key] = value
    return values


def display_width(text: str) -> int:
    """计算字符串在等宽终端中的显示宽度（CJK 字符按 2 计算）."""
    width = 0
    for ch in text:
        width += 2 if ord(ch) > 0x2E80 else 1
    return width


def pad_display(text: str, width: int) -> str:
    """按显示宽度右填充空格（用于中文表格对齐）."""
    return text + " " * max(width - display_width(text), 0)


def truncate_display(text: str, max_width: int) -> str:
    """按显示宽度截断，超长结尾补 ``…``."""
    if display_width(text) <= max_width:
        return text
    result = ""
    used = 0
    for ch in text:
        w = 2 if ord(ch) > 0x2E80 else 1
        if used + w > max_width - 1:
            break
        result += ch
        used += w
    return result + "…"


def render_table(headers: list[str], rows: list[list[str]], widths: list[int]) -> str:
    """渲染带中文对齐的等宽文本表格.

    Args:
        headers: 表头。
        rows: 数据行。
        widths: 每列显示宽度。

    Returns:
        拼接好的多行字符串（含分隔线）。
    """
    line_parts: list[str] = []
    sep_parts: list[str] = []
    for header, width in zip(headers, widths):
        line_parts.append(pad_display(header, width))
        sep_parts.append("-" * width)
    lines = ["  ".join(line_parts).rstrip(), "  ".join(sep_parts).rstrip()]
    for row in rows:
        cells: list[str] = []
        for idx, cell in enumerate(row):
            cells.append(pad_display(truncate_display(str(cell), widths[idx]), widths[idx]))
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


# ---------------------------------------------------------------- 环境加载


def load_config(args: argparse.Namespace) -> EnvConfig:
    """按「命令行 > 系统环境变量 > .env 文件 > 默认值」的优先级构建配置."""
    cfg = EnvConfig(env_file=Path(args.env_file).expanduser() if args.env_file else DEFAULT_ENV_FILE)
    cfg.env_file = cfg.env_file.resolve() if cfg.env_file.is_absolute() else (BACKEND_DIR / cfg.env_file).resolve()
    cfg.env_file_exists = cfg.env_file.is_file()

    if not cfg.env_file_exists:
        cfg.warnings.append(
            f"未找到 .env 文件（期望路径：{cfg.env_file}）。"
            f"请先执行 copy backend\\.env.example backend\\.env 并填入 API Key，"
            f"或用 --api-key / --base-url 显式传入。"
        )

    file_values = parse_env_file(cfg.env_file)

    # ---- API Key 优先级 ----
    if args.api_key:
        cfg.api_key = args.api_key.strip()
        cfg.api_key_source = "命令行 --api-key"
    elif os.environ.get("MODEL_ROUTER_API_KEY", "").strip():
        cfg.api_key = os.environ["MODEL_ROUTER_API_KEY"].strip()
        cfg.api_key_source = "系统环境变量 MODEL_ROUTER_API_KEY"
    elif file_values.get("MODEL_ROUTER_API_KEY", "").strip():
        cfg.api_key = file_values["MODEL_ROUTER_API_KEY"].strip()
        cfg.api_key_source = f".env 文件（{cfg.env_file.name}）"
    else:
        cfg.api_key_source = "未找到"

    # ---- Base URL 优先级 ----
    if args.base_url:
        cfg.base_url = args.base_url.strip()
        cfg.base_url_source = "命令行 --base-url"
    elif os.environ.get("MODEL_ROUTER_BASE_URL", "").strip():
        cfg.base_url = os.environ["MODEL_ROUTER_BASE_URL"].strip()
        cfg.base_url_source = "系统环境变量 MODEL_ROUTER_BASE_URL"
    elif file_values.get("MODEL_ROUTER_BASE_URL", "").strip():
        cfg.base_url = file_values["MODEL_ROUTER_BASE_URL"].strip()
        cfg.base_url_source = f".env 文件（{cfg.env_file.name}）"
    else:
        cfg.base_url = OFFICIAL_BASE_URL
        cfg.base_url_source = "内置默认值（赛方 Model Router）"

    cfg.base_url = cfg.base_url.rstrip("/")
    return cfg


# ---------------------------------------------------------------- 错误解析


def classify_error(exc: BaseException) -> tuple[str, str, str]:
    """把异常解析为 ``(错误码, 错误信息, 错误类别)``.

    Args:
        exc: 调用过程中抛出的任意异常。

    Returns:
        三元组：错误码字符串、可读错误信息、错误类别枚举串。
    """
    status_code = getattr(exc, "status_code", None)
    err_code = getattr(exc, "code", None)
    message = str(getattr(exc, "message", "") or exc).strip()

    body: Any = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict):
            err_code = err_code or err.get("code") or err.get("type")
            message = str(err.get("message") or message).strip()

    if not message:
        message = f"{type(exc).__name__}: {exc}"

    # 统一折叠为单行，避免表格错位
    message = " ".join(message.split())
    message = truncate_display(message, MAX_ERROR_MESSAGE_LEN)

    code = str(err_code) if err_code else (str(status_code) if status_code else type(exc).__name__)

    name_lower = type(exc).__name__.lower()
    if status_code == 401 or status_code == 403 or "authentication" in name_lower or "permission" in name_lower:
        category = "AUTH"
    elif status_code == 404 or "notfound" in name_lower:
        category = "NOT_FOUND"
    elif status_code == 429 or "rate" in name_lower:
        category = "RATE_LIMIT"
    elif status_code is not None and int(status_code) >= 500:
        category = "SERVER"
    elif "timeout" in name_lower or "timedout" in name_lower:
        category = "TIMEOUT"
    elif "connection" in name_lower or "network" in name_lower:
        category = "CONNECTION"
    else:
        category = "OTHER"

    if not err_code and status_code:
        code = f"HTTP {status_code}"
    return code, message, category


# ---------------------------------------------------------------- 探测逻辑


def probe_chat(client: Any, model: str) -> tuple[str, str]:
    """对话类模型探测：发一条极短消息.

    Args:
        client: OpenAI 兼容客户端。
        model: 待测试模型名。

    Returns:
        ``(detail, error_message)``；成功时 ``error_message`` 为空字符串。
    """
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=16,
        temperature=0.0,
    )
    content = ""
    try:
        content = (resp.choices[0].message.content or "").strip()
    except Exception:  # noqa: BLE001 - 结构异常不影响连通性判定
        content = ""
    tokens = getattr(getattr(resp, "usage", None), "total_tokens", None)
    preview = truncate_display(content.replace("\n", " "), 18) or "(空回复)"
    detail = f"tokens={tokens}" if tokens is not None else f"reply={preview}"
    return detail, ""


def probe_embedding(client: Any, model: str) -> tuple[str, str]:
    """向量类模型探测：对短文本做一次 embedding.

    Args:
        client: OpenAI 兼容客户端。
        model: 待测试模型名。

    Returns:
        ``(detail, error_message)``；成功时 ``error_message`` 为空字符串。
    """
    resp = client.embeddings.create(model=model, input="hello voc radar")
    vector = resp.data[0].embedding
    tokens = getattr(getattr(resp, "usage", None), "total_tokens", None)
    detail = f"dim={len(vector)}" + (f",tokens={tokens}" if tokens is not None else "")
    return detail, ""


def run_probe(client: Any, model: str, base_model: str, prefix: str, timeout: float) -> ProbeResult:
    """对单个模型名执行一次探测，任何异常都被捕获为 FAIL 结果.

    Args:
        client: OpenAI 兼容客户端。
        model: 完整模型名（含前缀）。
        base_model: 基础模型名（不含前缀）。
        prefix: 本次使用的前缀。
        timeout: 超时秒数（用于异常兜底分类）。

    Returns:
        探测结果对象。
    """
    is_embedding = any(keyword in model.lower() for keyword in EMBEDDING_KEYWORDS)
    kind = "embedding" if is_embedding else "chat"
    result = ProbeResult(model=model, base_model=base_model, prefix=prefix, kind=kind)

    started = time.perf_counter()
    try:
        if is_embedding:
            detail, _ = probe_embedding(client, model)
        else:
            detail, _ = probe_chat(client, model)
        result.ok = True
        result.detail = detail
    except BaseException as exc:  # noqa: BLE001 - 自检脚本必须吞掉所有异常继续跑
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        code, message, category = classify_error(exc)
        # openai 超时异常有时不带 status_code，这里按耗时兜底判定
        if category == "OTHER" and (time.perf_counter() - started) >= timeout * 0.95:
            category = "TIMEOUT"
            code = "TIMEOUT"
            message = f"调用超过 {timeout:.0f}s 未返回"
        result.ok = False
        result.error_code = code
        result.error_message = message
        result.error_category = category
    finally:
        result.elapsed = time.perf_counter() - started
    return result


# ---------------------------------------------------------------- 结论生成


def build_model_recommendations(results: list[ProbeResult]) -> list[ModelRecommendation]:
    """按基础模型名汇总「无前缀 vs 带前缀」的可行写法.

    Args:
        results: 全部探测结果。

    Returns:
        命名建议列表（顺序与 CANDIDATE_MODELS 一致）。
    """
    indexed: dict[str, dict[str, ProbeResult]] = {}
    for item in results:
        indexed.setdefault(item.base_model, {})[item.prefix] = item

    recommendations: list[ModelRecommendation] = []
    for base, _role in CANDIDATE_MODELS:
        pair = indexed.get(base)
        if not pair:
            continue
        plain = pair.get("")
        prefixed = pair.get("qwen/")
        plain_ok = bool(plain and plain.ok)
        prefixed_ok = bool(prefixed and prefixed.ok)

        if plain_ok and prefixed_ok:
            recommended = f"qwen/{base}"
            note = "两种均可，采用官方带前缀写法"
        elif plain_ok:
            recommended = base
            note = "仅无前缀可用"
        elif prefixed_ok:
            recommended = f"qwen/{base}"
            note = "仅带前缀可用"
        else:
            recommended = ""
            if plain and not plain.ok:
                note = f"{plain.error_code}: {plain.error_message}"
            else:
                note = "FAIL: 未返回有效结果"

        recommendations.append(
            ModelRecommendation(
                base_model=base,
                plain_ok=plain_ok,
                prefixed_ok=prefixed_ok,
                recommended=recommended,
                note=note,
            )
        )
    return recommendations


def build_final_conclusion(cfg: EnvConfig, results: list[ProbeResult]) -> list[str]:
    """生成面向用户的中文结论与 .env 修改建议.

    Args:
        cfg: 运行配置。
        results: 全部探测结果。

    Returns:
        待打印的结论文本行列表。
    """
    lines: list[str] = []
    ok_results = [r for r in results if r.ok]
    categories = {r.error_category for r in results if not r.ok}

    lines.append("")
    lines.append("=" * 78)
    lines.append("结论")
    lines.append("=" * 78)

    # ---------- 1. 通道连通性 ----------
    if ok_results:
        lines.append(
            f"1) Base URL「{cfg.base_url}」连通：{len(ok_results)}/{len(results)} 个模型名调用成功。"
        )
    elif categories and categories.issubset({"AUTH"}):
        lines.append(
            f"1) Base URL「{cfg.base_url}」可达，但 API Key 未被接受（全部返回鉴权失败）。"
        )
        lines.append(
            "   → 请确认 Key 与 Base URL 配套：赛方 Model Router 必须用赛方发放的 Key，"
        )
        lines.append(
            "     百炼直连必须用个人百炼 Key。两者额度通道不同，不能混用。"
        )
    elif categories and categories.issubset({"CONNECTION", "TIMEOUT"}):
        lines.append(
            f"1) Base URL「{cfg.base_url}」连不通（网络不可达或超时）。"
        )
        lines.append(
            "   → 请检查本机网络 / 代理 / 防火墙，或改用另一个通道重试。"
        )
    else:
        lines.append(
            f"1) Base URL「{cfg.base_url}」未取得任何成功调用，错误类别："
            f"{', '.join(sorted(categories)) or '未知'}。"
        )

    # ---------- 2. 前缀结论 ----------
    lines.append("")
    recommendations = build_model_recommendations(results)
    both_ok = [r.base_model for r in recommendations if r.plain_ok and r.prefixed_ok]
    plain_only = [r.base_model for r in recommendations if r.plain_ok and not r.prefixed_ok]
    prefix_only = [r.base_model for r in recommendations if not r.plain_ok and r.prefixed_ok]

    lines.append("2) 前缀问题（这是本次自检的核心结论）：")
    if both_ok:
        lines.append("   · 两种写法都能调通（通道兼容无前缀与 qwen/ 前缀）：")
        for name in both_ok:
            lines.append(f"       - {name}  →  .env 可写 {name} 或 qwen/{name}")
    if plain_only:
        lines.append("   · 仅「无前缀」写法可用，带 qwen/ 前缀会失败：")
        for name in plain_only:
            lines.append(f"       - {name}  →  .env 必须写 {name}")
    if prefix_only:
        lines.append("   · 仅「qwen/ 带前缀」写法可用：")
        for name in prefix_only:
            lines.append(f"       - {name}  →  .env 必须写 qwen/{name}")
    unavailable = [r for r in recommendations if not r.recommended]
    if unavailable:
        lines.append("   · 当前通道下不可用的模型（需换通道或换模型名）：")
        for rec in unavailable:
            lines.append(f"       - {rec.base_model}（{rec.note}）")
    if not (both_ok or plain_only or prefix_only):
        lines.append("   · 当前通道下没有任何模型调通，无法判定前缀规则。")
        lines.append("     → 先解决 Key / 网络问题（见结论 1），再重跑本脚本。")

    # ---------- 3. 建议写入 .env 的内容 ----------
    lines.append("")
    lines.append("3) 建议写入 backend/.env 的模型名（按本次实测结果生成，可直接复制）：")
    env_mapping: list[tuple[str, str]] = [
        ("MODEL_EMBEDDING", "text-embedding-v4"),
        ("MODEL_LLM", "qwen3.7-max"),
        ("MODEL_FLASH", "qwen3.5-flash"),
        ("MODEL_VISION", "qwen3-vl-plus"),
        ("MODEL_R1", "deepseek-r1"),
    ]
    rec_map = {rec.base_model: rec for rec in recommendations}
    usable_count = 0
    env_lines: list[str] = []
    for env_name, base in env_mapping:
        rec = rec_map.get(base)
        if rec is None:
            env_lines.append(f"   {env_name}=<本次未测试，保持原值>")
            continue
        if rec.recommended:
            usable_count += 1
            env_lines.append(f"   {env_name}={rec.recommended}")
        else:
            env_lines.append(f"   {env_name}=<保持原值 —— {rec.note}>")
    lines.extend(env_lines)
    lines.append(
        f"   （共 {usable_count}/{len(env_mapping)} 个角色在本通道实测可用；"
        f"修改 .env 后需重启后端 start.bat 才生效）"
    )

    # ---------- 4. 通道选择提示 ----------
    lines.append("")
    lines.append("4) 两个通道的区别与切换方法：")
    lines.append(
        f"   - 赛方 Model Router（推荐用于复赛/决赛提交）：{OFFICIAL_BASE_URL}"
    )
    lines.append("     走赛方发放的 25000 Credits 算力额度，不消耗个人 Key 余额。")
    lines.append(
        f"   - 阿里云百炼直连（本地开发调试）：{DASHSCOPE_BASE_URL}"
    )
    lines.append("     走个人百炼 Key，费用自付。")
    lines.append(
        "   切换方法：同时修改 backend/.env 里的 MODEL_ROUTER_BASE_URL 与 "
        "MODEL_ROUTER_API_KEY 两行，"
    )
    lines.append("   两者必须配套，改完重启后端（start.bat）。可用本脚本先验证：")
    lines.append(f"     python check_models.py --base-url {OFFICIAL_BASE_URL} --api-key <赛方Key>")
    lines.append(f"     python check_models.py --base-url {DASHSCOPE_BASE_URL} --api-key <个人Key>")
    return lines


# ---------------------------------------------------------------- 主流程


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数."""
    parser = argparse.ArgumentParser(
        prog="check_models.py",
        description="VOC Radar 模型连通性自检：验证模型名与 Base URL 组合是否可用",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python check_models.py\n"
            f"  python check_models.py --base-url {OFFICIAL_BASE_URL} --api-key sk-xxx\n"
            f"  python check_models.py --base-url {DASHSCOPE_BASE_URL}\n"
        ),
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="覆盖 Base URL（默认读 .env 的 MODEL_ROUTER_BASE_URL）",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="覆盖 API Key（默认读 .env 的 MODEL_ROUTER_API_KEY；输出中始终脱敏）",
    )
    parser.add_argument(
        "--env-file",
        default="",
        help=f"指定 .env 路径（默认 {DEFAULT_ENV_FILE}）",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"单模型超时秒数（默认 {DEFAULT_TIMEOUT_SECONDS:.0f}s，建议不超过 30s）",
    )
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        metavar="NAME",
        help="追加测试一个模型名（可重复使用，会同时测试其无前缀/带前缀形式）",
    )
    parser.add_argument(
        "--extra-prefix",
        action="append",
        default=[],
        metavar="PFX",
        help="追加测试一个前缀（如 qwen2/，可重复使用）",
    )
    parser.add_argument(
        "--skip-prefixed",
        action="store_true",
        help="只测无前缀写法（跳过 qwen/ 前缀对照，用于快速回归）",
    )
    return parser.parse_args(argv)


def build_candidates(args: argparse.Namespace) -> list[tuple[str, str, str]]:
    """构造完整待测试模型名列表，返回 ``(完整名, 基础名, 前缀)``."""
    prefixes: list[str] = [""] if args.skip_prefixed else list(DEFAULT_PREFIXES)
    for pfx in args.extra_prefix:
        pfx = pfx.strip()
        if pfx and not pfx.endswith("/"):
            pfx += "/"
        if pfx and pfx not in prefixes:
            prefixes.append(pfx)

    bases: list[str] = [name for name, _role in CANDIDATE_MODELS]
    for name in args.model:
        name = name.strip()
        if not name:
            continue
        # 用户传入的可能是带前缀的完整名，这里归一化为「基础名」
        bare = name.split("/")[-1]
        if bare not in bases:
            bases.append(bare)
        head = name[: len(name) - len(bare)]
        if head and head not in prefixes:
            prefixes.append(head)

    candidates: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for base in bases:
        for pfx in prefixes:
            full = f"{pfx}{base}"
            if full in seen:
                continue
            seen.add(full)
            candidates.append((full, base, pfx))
    return candidates


def main(argv: list[str] | None = None) -> int:
    """脚本入口.

    Args:
        argv: 命令行参数列表（供测试调用，默认取 sys.argv[1:]）。

    Returns:
        进程退出码（0 全部/部分成功，1 全失败，2 前置条件不满足）。
    """
    _safe_reconfigure_stdout()
    args = parse_args(argv)

    print("=" * 78)
    print("VOC Radar · 模型连通性自检")
    print("=" * 78)
    print("用途：确认「模型名 + Base URL」组合是否真正可用，并判定模型名前缀是否必需。")
    print()

    try:
        from openai import OpenAI  # 延迟导入，缺库时给出友好提示
    except ImportError:
        print("[错误] 未找到 openai 库。请先在 venv 中安装依赖：")
        print("       .\\.venv\\Scripts\\python.exe -m pip install -r backend\\requirements.txt")
        return 2

    cfg = load_config(args)

    # ---------- 打印配置摘要（Key 脱敏） ----------
    print("[配置]")
    print(f"  .env 文件    : {cfg.env_file}（{'存在' if cfg.env_file_exists else '缺失'}）")
    print(f"  Base URL     : {cfg.base_url}")
    print(f"  Base URL 来源: {cfg.base_url_source}")
    print(f"  API Key      : {mask_secret(cfg.api_key)}（来源：{cfg.api_key_source}）")
    print(f"  单模型超时   : {args.timeout:.0f}s")
    print()

    for warning in cfg.warnings:
        print(f"[警告] {warning}")

    if not cfg.api_key:
        print()
        print("[错误] 未配置 API Key，无法发起真实调用。")
        print("       请编辑 backend/.env 填写 MODEL_ROUTER_API_KEY，或用 --api-key 传入。")
        return 2
    if looks_like_placeholder(cfg.api_key):
        print()
        print("[错误] API Key 仍是模板占位值（如 sk-your-personal-bailian-key）。")
        print("       请替换为真实 Key 后重跑。")
        return 2

    candidates = build_candidates(args)
    print(f"[开始] 共需测试 {len(candidates)} 个模型名（每个做一次最小成本真实调用）")
    print()

    client = OpenAI(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        timeout=args.timeout,
        max_retries=0,
    )

    results: list[ProbeResult] = []
    for full, base, pfx in candidates:
        print(f"  测试 {full} ... ", end="", flush=True)
        result = run_probe(client, full, base, pfx, args.timeout)
        results.append(result)
        if result.ok:
            print(f"OK  ({result.elapsed:.2f}s, {result.detail})")
        else:
            print(f"FAIL({result.elapsed:.2f}s, {result.error_code})")

    # ---------- 汇总表格 ----------
    print()
    print("=" * 78)
    print("汇总表格")
    print("=" * 78)
    table = render_table(
        headers=["模型名", "类型", "结果", "耗时", "错误码", "详情 / 错误信息"],
        rows=[r.as_row() for r in results],
        widths=[30, 10, 6, 8, 14, 46],
    )
    print(table)

    # ---------- 前缀对照 ----------
    print()
    print("前缀对照（无前缀 vs 官方 qwen/ 前缀）")
    print("-" * 78)
    recommendations = build_model_recommendations(results)
    print(
        render_table(
            headers=["基础模型名", "无前缀", "qwen/ 前缀", "建议写入 .env 的模型名"],
            rows=[
                [
                    rec.base_model,
                    rec.plain_text,
                    rec.prefixed_text,
                    rec.recommended or f"不可用（{rec.note}）",
                ]
                for rec in recommendations
            ],
            widths=[24, 8, 12, 42],
        )
    )

    # ---------- 最终结论 ----------
    for line in build_final_conclusion(cfg, results):
        print(line)

    print()
    print("说明：以上结论来自本次真实调用，可直接作为 .env 配置依据。")
    print("      若需对比两个通道，请分别用 --base-url 跑一次并保存输出。")

    return 0 if any(r.ok for r in results) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[中断] 用户取消，未产生完整结论。")
        sys.exit(130)
