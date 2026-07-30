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

  const CHART_FONT =
    '-apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';

  /**
   * 根据影响面返回严重程度颜色（红→橙→黄渐变）
   * @param {number} ratio 0~1
   */
  function severityColor(ratio) {
    if (ratio >= 0.25) return "#ff4d4f"; // critical 红
    if (ratio >= 0.18) return "#ff7a45"; // high 橙
    if (ratio >= 0.12) return "#ffa940"; // medium 深黄
    if (ratio >= 0.06) return "#ffd666"; // low 浅黄
    return "#fff1b8"; // minor 米黄
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
        return "#ff4d4f";
      case "falling":
        return "#52c41a";
      case "stable":
        return "#a6b0cc";
      default:
        return "#6b769a";
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
              backgroundColor: colors,
              borderColor: colors.map((c) => c),
              borderWidth: 1,
              borderRadius: 4,
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
          animation: { duration: 600, easing: "easeOutQuart" },
          layout: { padding: { right: 30 } },
          scales: {
            x: {
              beginAtZero: true,
              max: Math.max(35, Math.ceil(Math.max(...values) / 5) * 5 + 5),
              grid: { color: "rgba(140,160,220,0.08)" },
              ticks: {
                color: "#6b769a",
                font: { family: CHART_FONT, size: 11 },
                callback: function (v) {
                  return v + "%";
                },
              },
              title: {
                display: true,
                text: "影响面占比（占差评总数）",
                color: "#6b769a",
                font: { family: CHART_FONT, size: 11 },
              },
            },
            y: {
              grid: { display: false },
              ticks: {
                color: "#e8ecf6",
                font: { family: CHART_FONT, size: 12 },
              },
            },
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: "rgba(19,26,48,0.95)",
              borderColor: "rgba(140,160,220,0.28)",
              borderWidth: 1,
              titleColor: "#e8ecf6",
              bodyColor: "#a6b0cc",
              titleFont: { family: CHART_FONT, size: 13, weight: "bold" },
              bodyFont: { family: CHART_FONT, size: 12 },
              padding: 10,
              cornerRadius: 8,
              displayColors: false,
              callbacks: {
                title: function (items) {
                  const i = items[0].dataIndex;
                  const ds = items[0].dataset;
                  const label = items[0].label;
                  const top5 = ds._isTop5[i];
                  return top5 ? label + "  ⭐Top5 归因" : label;
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
                  if (ar != null) lines.push("平均星级: ⭐" + ar);
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
