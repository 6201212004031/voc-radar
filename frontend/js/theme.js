/**
 * VOC Radar — 图表主题 Token 桥接层
 *
 * 为什么需要这个文件：
 *   Chart.js 画在 canvas 上，**读不到 CSS 变量**（`var(--accent)` 在 canvas 上下文里无意义）。
 *   只能通过 getComputedStyle 取值后再喂给 Chart.js。
 *   若取到空串且无兜底，图表会渲染成黑块 / 默认宋体 —— 这在路演现场是致命的。
 *   因此：**每个 token 都必须带硬编码 fallback**，且 fallback 值与 style.css 的 hex 兜底层保持一致。
 *
 * 为什么还要绕一层临时 DOM 元素（实测结论，勿凭直觉改）：
 *   1. `getPropertyValue('--accent')` 拿到的就是变量原文，例如 `oklch(0.82 0.145 172)`；
 *      对自定义属性，getComputedStyle **不会**把它换算成 rgb/rgba。
 *   2. 把 token 写到一个临时元素的真实颜色属性（color / borderColor / backgroundColor）
 *      上再读 getComputedStyle，能让浏览器先解析一遍：
 *        - `color-mix(in oklab, ...)` → 解析为 `oklab(0.93 ... / 0.18)`（--line 的实测值）
 *        - `oklch(...)`              → 原样返回（仅数值归一化，仍是 oklch）
 *      这一步的价值是把 canvas 未必认得的 `color-mix()` 展开成具体颜色函数。
 *   3. 实测 Chromium 151（Edge 同内核）：canvas 2D 的 fillStyle 能直接吃
 *      `oklch()` 与 `oklab()`，赋值后再读回仍是同值，说明解析成功、未静默失败。
 *   4. 注意：canvas 遇到无法解析的颜色是**静默忽略**（保持上一个 fillStyle），不抛异常，
 *      所以 try/catch 兜不住这种情况 —— 真正兜底的是每个 token 的 fallback 参数。
 *
 * 加载顺序：必须在 api.js 与所有组件脚本**之前**引入（见 index.html）。
 *
 * 挂载到全局 window.VOC_THEME
 */
(function (global) {
  "use strict";

  var cs = getComputedStyle(document.documentElement);
  var body = document.body;

  /** 取原始变量值；空串则回落到 fallback */
  function t(name, fallback) {
    var v = cs.getPropertyValue(name);
    return (v && v.trim()) || fallback;
  }

  /**
   * 取一个颜色 token 的"浏览器已解析值"。
   * 让浏览器先把 color-mix() 之类的写法展开，再交给 canvas。
   * 拿不到值（变量缺失）时回落 fallback —— 这才是防黑块的关键。
   */
  function c(name, fallback, prop) {
    prop = prop || "color";
    var v = t(name, "");
    if (!v) return fallback;
    var test;
    try {
      test = document.createElement("div");
      test.style.position = "absolute";
      test.style.visibility = "hidden";
      test.style[prop] = "var(" + name + ")";
      body.appendChild(test);
      var resolved = getComputedStyle(test)[prop];
      return resolved || fallback;
    } catch (e) {
      return fallback;
    } finally {
      if (test && test.parentNode) test.parentNode.removeChild(test);
    }
  }

  var T = {
    font: t("--font-body", '"PingFang SC","Microsoft YaHei",sans-serif'),
    fontMono: t("--font-mono", "Consolas,monospace"),
    text: c("--text-primary", "#eceef1"),
    textMuted: c("--text-muted", "#82888f"),
    textFaint: c("--text-faint", "#66696f"),
    accent: c("--accent", "#2fe0bd"),
    grid: c("--hairline", "rgba(236,238,241,0.07)", "borderColor"),
    gridMid: c("--line-str", "rgba(236,238,241,0.26)", "borderColor"),
    panel: c("--bg-elev-1", "#171a1e", "backgroundColor"),
    sev: [
      c("--sev-1", "#ffe9a8"),
      c("--sev-2", "#ffcf5c"),
      c("--sev-3", "#ff9f3d"),
      c("--sev-4", "#f4703a"),
      c("--sev-5", "#e0353c"),
    ],
    quad: {
      quick_win: c("--quad-quick", "#2fe0bd"),
      strategic: c("--quad-strategic", "#b07cf0"),
      filler: c("--quad-filler", "#9aa4b2"),
      thankless: c("--quad-thankless", "#5b6472"),
    },
    /* 形状三重编码：投影 / 色盲 / 黑白打印都能分辨象限 */
    shape: {
      quick_win: "circle",
      strategic: "triangle",
      filler: "rect",
      thankless: "crossRot",
    },
  };

  /** 影响面 → 严重度色。阈值是业务逻辑，保持原值不动 */
  T.severity = function (r) {
    return r >= 0.25
      ? T.sev[4]
      : r >= 0.18
      ? T.sev[3]
      : r >= 0.12
      ? T.sev[2]
      : r >= 0.06
      ? T.sev[1]
      : T.sev[0];
  };

  global.VOC_THEME = T;
})(window);
