/**
 * VOC Radar — 图表主题 Token 桥接层
 *
 * 为什么需要这个文件：
 *   Chart.js 画在 canvas 上，**读不到 CSS 变量**（`var(--accent)` 在 canvas 上下文里无意义）。
 *   只能通过 getComputedStyle 取值后再喂给 Chart.js。
 *   若取到空串且无兜底，图表会渲染成黑块 / 默认宋体 —— 这在路演现场是致命的。
 *   因此：**每个 token 都必须带硬编码 fallback**，且 fallback 值与 style.css 的 hex 兜底层保持一致。
 *
 * 颜色解析策略：
 *   CSS 变量里可能是 oklch() / color-mix() 等高级写法。
 *   canvas 2D 的 fillStyle 在旧浏览器/某些 Chromium 版本可能解析不了 oklch，
 *   导致 silently 填成黑色。我们先把颜色 token 设置到一个临时 DOM 元素上，
 *   再读 getComputedStyle 的已解析值（会回落为 rgb/rgba），确保 canvas 一定能画。
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
   * 把一个颜色 token 解析成 canvas 安全的 rgb/rgba 字符串。
   * 方法：创建一个临时元素，把 token 写到某个真实 CSS 颜色属性上，
   * 再读 getComputedStyle 的已解析值。解析失败就回落 fallback。
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
    textFaint: c("--text-faint", "#5c6268"),
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
