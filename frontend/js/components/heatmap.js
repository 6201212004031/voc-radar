/**
 * VOC Radar — 痛点热力图组件
 *
 * 职责：
 *  - 用 Chart.js 横向条形图渲染痛点热力图
 *  - 按影响面（impact_ratio）降序排列
 *  - 痛点严重程度用红/橙/黄渐变表示
 *  - 点击痛点条 → 触发下钻回调
 *
 * 依赖：Chart.js 4.4+（CDN）
 * 挂载到全局 window.VOC_Heatmap
 */
(function (global) {
  "use strict";

  // 图表 token：来自 theme.js（Canvas 读不到 CSS 变量，只能走桥接层）
  const T =
    global.VOC_THEME || {
      font: '"PingFang SC","Microsoft YaHei",sans-serif',
      fontMono: "Consolas,monospace",
      text: "#eceef1",
      textMuted: "#82888f",
      textFaint: "#5c6268",
      accent: "#2fe0bd",
      grid: "rgba(236,238,241,0.07)",
      gridMid: "rgba(236,238,241,0.26)",
      panel: "#171a1e",
      sev: ["#ffe9a8", "#ffcf5c", "#ff9f3d", "#f4703a", "#e0353c"],
      severity: function (r) {
        return r >= 0.25
          ? "#e0353c"
          : r >= 0.18
          ? "#f4703a"
          : r >= 0.12
          ? "#ff9f3d"
          : r >= 0.06
          ? "#ffcf5c"
          : "#ffe9a8";
      },
    };

  const CHART_FONT = T.font;
  const CHART_FONT_MONO = T.fontMono;

  /**
   * 提亮 12%（用于条形末端，表达"信号强度"）。
   * 支持 oklch() / #rrggbb / rgb() / rgba()（theme.js 通常会把它们解析成 rgb/rgba）。
   * 认不出来的格式原样返回 —— 宁可不提亮，也绝不返回空串导致黑块。
   */
  function lighten(c, amt) {
    if (typeof c !== "string") return c;
    // oklch：增加 L 通道
    var m = /^oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)/i.exec(c);
    if (m) {
      var L = Math.min(1, parseFloat(m[1]) + amt);
      return "oklch(" + L.toFixed(3) + " " + m[2] + " " + m[3] + ")";
    }
    // #rrggbb
    m = /^#([0-9a-f]{6})$/i.exec(c);
    if (m) {
      var n = parseInt(m[1], 16);
      var d = Math.round(amt * 255);
      var r = Math.min(255, ((n >> 16) & 255) + d);
      var g = Math.min(255, ((n >> 8) & 255) + d);
      var b = Math.min(255, (n & 255) + d);
      return "rgb(" + r + "," + g + "," + b + ")";
    }
    // rgb() / rgba()
    m = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)(?:\s*,\s*([\d.]+))?\s*\)$/i.exec(c);
    if (m) {
      d = Math.round(amt * 255);
      var rr = Math.min(255, Math.round(parseFloat(m[1]) + d));
      var gg = Math.min(255, Math.round(parseFloat(m[2]) + d));
      var bb = Math.min(255, Math.round(parseFloat(m[3]) + d));
      var a = m[4] !== undefined ? m[4] : "1";
      return "rgba(" + rr + "," + gg + "," + bb + "," + a + ")";
    }
    return c;
  }

  /** 条形渐变：同色相左→右，末端提亮。任何异常都回落为实色 */
  function barGradient(ctx, area, color) {
    if (!ctx || !area) return color;
    try {
      var g = ctx.createLinearGradient(area.left, 0, area.right, 0);
      g.addColorStop(0, color);
      g.addColorStop(1, lighten(color, 0.12));
      return g;
    } catch (e) {
      return color;
    }
  }

  /**
   * 根据影响面返回严重程度颜色（红→橙→黄渐变）
   * 阈值是业务逻辑，保持原值不动
   * @param {number} ratio 0~1
   */
  function severityColor(ratio) {
    return T.severity(ratio);
  }

  /**
   * 趋势图标
   * @param {string} trend rising|falling|stable|unknown
   */
  function trendIcon(trend) {
    switch (trend) {
      case "rising":
        return "↗";
      case "falling":
        return "↘";
      case "stable":
        return "→";
      default:
        return "·";
    }
  }

  function trendColor(trend) {
    switch (trend) {
      case "rising":
        return T.sev[4];      /* 恶化＝严重度最高 */
      case "falling":
        return T.accent;      /* 改善＝强调色，不再用绿色 */
      case "stable":
        return T.textMuted;
      default:
        return T.textFaint;
    }
  }

  /**
   * Heatmap 组件类
   */
  class Heatmap {
    constructor(canvasId, options) {
      this.canvasId = canvasId;
      this.chart = null;
      this.data = [];
      this.options = Object.assign(
        {
          onPainPointClick: null,
          emptyHintId: null,
        },
        options || {}
      );
    }

    /**
     * 渲染热力图
     * @param {Array} heatmapData OverviewVO.heatmap
     *  [{pain_point_id, label, impact_ratio, review_count, avg_rating, trend, is_top5}]
     */
    render(heatmapData) {
      const canvas = document.getElementById(this.canvasId);
      if (!canvas) {
        console.warn("[Heatmap] canvas not found:", this.canvasId);
        return;
      }

      // 空态
      const emptyEl = this.options.emptyHintId
        ? document.getElementById(this.options.emptyHintId)
        : null;
      if (!heatmapData || !heatmapData.length) {
        if (emptyEl) emptyEl.hidden = false;
        if (this.chart) {
          this.chart.destroy();
          this.chart = null;
        }
        this.data = [];
        return;
      }
      if (emptyEl) emptyEl.hidden = true;

      // 按影响面降序
      const sorted = heatmapData
        .slice()
        .sort((a, b) => (b.impact_ratio || 0) - (a.impact_ratio || 0));
      this.data = sorted;

      // Chart.js 横向条形图：标签从上到下，把最大的放最上方
      // 反转数组使最大的显示在顶部
      const reversed = sorted.slice().reverse();
      const labels = reversed.map((d) => d.label || "未命名痛点");
      const values = reversed.map((d) => +(d.impact_ratio * 100).toFixed(1));
      const colors = reversed.map((d) => severityColor(d.impact_ratio));
      const avgRatings = reversed.map((d) =>
        d.avg_rating != null ? +d.avg_rating.toFixed(2) : null
      );
      const reviewCounts = reversed.map((d) => d.review_count || 0);
      const trends = reversed.map((d) => d.trend || "unknown");
      const top5Flags = reversed.map((d) => !!d.is_top5);

      // 销毁旧图
      if (this.chart) {
        this.chart.destroy();
      }

      const ctx = canvas.getContext("2d");
      this.chart = new Chart(ctx, {
        type: "bar",
        data: {
          labels: labels,
          datasets: [
            {
              label: "影响面占比 (%)",
              data: values,
              // 方角 + 无描边 + 同色相渐变（末端提亮）表达信号强度
              backgroundColor: function (c) {
                var area = c.chart && c.chart.chartArea;
                return barGradient(c.chart && c.chart.ctx, area, colors[c.dataIndex]);
              },
              borderWidth: 0,
              borderRadius: 0,
              barPercentage: 0.78,
              categoryPercentage: 0.82,
              // 自定义数据，供 tooltip/点击使用
              _painPointIds: reversed.map((d) => d.pain_point_id),
              _avgRatings: avgRatings,
              _reviewCounts: reviewCounts,
              _trends: trends,
              _isTop5: top5Flags,
              _raw: reversed,
            },
          ],
        },
        options: {
          indexAxis: "y", // 横向条形图
          responsive: true,
          maintainAspectRatio: false,
          // 路演/截图场景下，headless 浏览器 requestAnimationFrame 可能不推进，
          // 导致动画永远停在初始状态（条形宽度为 0）。关闭 Chart.js 动画，
          // 保证任何截图/录屏/现场投影都直接看到完整图表。
          animation: false,
          layout: { padding: { right: 30 } },
          scales: {
            x: {
              beginAtZero: true,
              max: Math.max(35, Math.ceil(Math.max(...values) / 5) * 5 + 5),
              grid: { color: T.grid },
              ticks: {
                color: T.textMuted,
                font: { family: CHART_FONT_MONO, size: 11 },
                callback: function (v) {
                  return v + "%";
                },
              },
              title: {
                display: true,
                text: "影响面占比（占差评总数）",
                color: T.textFaint,
                font: { family: CHART_FONT, size: 11 },
              },
            },
            y: {
              grid: { display: false },
              ticks: {
                color: T.text,
                font: { family: CHART_FONT, size: 12 },
              },
            },
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: T.panel,
              borderColor: T.gridMid,
              borderWidth: 1,
              titleColor: T.text,
              bodyColor: T.textMuted,
              titleFont: { family: CHART_FONT, size: 13, weight: "600" },
              bodyFont: { family: CHART_FONT_MONO, size: 12 },
              padding: 10,
              cornerRadius: 2,
              displayColors: false,
              callbacks: {
                title: function (items) {
                  const i = items[0].dataIndex;
                  const ds = items[0].dataset;
                  const label = items[0].label;
                  const top5 = ds._isTop5[i];
                  return top5 ? label + "  [TOP5]" : label;
                },
                label: function (item) {
                  const i = item.dataIndex;
                  const ds = item.dataset;
                  const ratio = item.parsed.x;
                  const rc = ds._reviewCounts[i];
                  const ar = ds._avgRatings[i];
                  const tr = ds._trends[i];
                  const lines = [
                    "影响面: " + ratio + "%（" + rc + " 条评论）",
                  ];
                  if (ar != null) lines.push("平均星级: " + ar);
                  lines.push(
                    "趋势: " +
                      trendIcon(tr) +
                      " " +
                      (tr === "rising"
                        ? "上升（恶化）"
                        : tr === "falling"
                        ? "下降（改善）"
                        : tr === "stable"
                        ? "稳定"
                        : "未知")
                  );
                  return lines;
                },
              },
            },
          },
          onClick: (e, elements) => {
            if (!elements || !elements.length) return;
            const el = elements[0];
            const ds = this.chart.data.datasets[el.datasetIndex];
            const raw = ds._raw[el.index];
            if (raw && this.options.onPainPointClick) {
              this.options.onPainPointClick(raw);
            }
          },
          onHover: (e, elements) => {
            e.native.target.style.cursor = elements.length
              ? "pointer"
              : "default";
          },
        },
      });
    }

    /** 销毁 */
    destroy() {
      if (this.chart) {
        this.chart.destroy();
        this.chart = null;
      }
      this.data = [];
    }

    /** 高亮指定痛点（滚动到并闪烁） */
    highlight(painPointId) {
      if (!this.chart || !painPointId) return;
      const idx = this.data.findIndex((d) => d.pain_point_id === painPointId);
      if (idx >= 0) {
        // Chart.js 反转过，原 index 对应反转后位置
        const reversedIdx = this.data.length - 1 - idx;
        this.chart.setActiveElements([
          { datasetIndex: 0, index: reversedIdx },
        ]);
        this.chart.tooltip.setActiveElements(
          [{ datasetIndex: 0, index: reversedIdx }],
          { x: 0, y: 0 }
        );
        this.chart.update();
      }
    }
  }

  // 暴露
  global.VOC_Heatmap = {
    Heatmap,
    severityColor,
    trendIcon,
  };
})(window);
