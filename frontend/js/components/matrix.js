/**
 * VOC Radar — 改进优先级矩阵组件
 *
 * 职责：
 *  - 用 Chart.js 散点图渲染四象限矩阵
 *  - 横轴：解决难度（difficulty_score 0~1，左易右难）
 *  - 纵轴：影响面（impact_ratio 0~1，下低上高）
 *  - 四象限颜色：Quick Win / Strategic / Filler / Thankless
 *  - 悬停显示痛点 tooltip，点击下钻
 *
 * 依赖：Chart.js 4.4+
 * 挂载到全局 window.VOC_Matrix
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
      textFaint: "#66696f",
      accent: "#2fe0bd",
      grid: "rgba(236,238,241,0.07)",
      gridMid: "rgba(236,238,241,0.26)",
      panel: "#171a1e",
      quad: {
        quick_win: "#2fe0bd",
        strategic: "#b07cf0",
        filler: "#9aa4b2",
        thankless: "#5b6472",
      },
      shape: {
        quick_win: "circle",
        strategic: "triangle",
        filler: "rect",
        thankless: "crossRot",
      },
    };

  const CHART_FONT = T.font;
  const CHART_FONT_MONO = T.fontMono;

  /**
   * 根据象限返回颜色（色相 + 明度 + 形状 三重编码）
   * quick_win: 高影响·易解决（左上）— 磷光青
   * strategic: 高影响·难解决（右上）— 紫
   * filler:    低影响·易解决（左下）— 中性灰
   * thankless: 低影响·难解决（右下）— 暗灰
   */
  function quadrantColor(quadrant) {
    return T.quad[quadrant] || T.accent;
  }

  /** 象限形状：灰度截图 / 色盲 / 黑白打印下也能分辨 */
  function quadrantShape(quadrant) {
    return T.shape[quadrant] || "circle";
  }

  function quadrantLabel(quadrant) {
    switch (quadrant) {
      case "quick_win":
        return "Quick Win 高影响·易解决";
      case "strategic":
        return "Strategic 高影响·难解决";
      case "filler":
        return "Filler 低影响·易解决";
      case "thankless":
        return "Thankless 低影响·难解决";
      default:
        return "未分类";
    }
  }

  // —— 同象限散点避让（确定性，无随机）——
  // difficulty_score 由象限反推（0.3/0.5/0.7 三档），同象限 x 必然相同；
  // 影响面接近的点会完全重叠，导致悬停/点击只能命中最上层。
  // 规则：y 相差 < ROW_DY 的点视为同一行，行内水平对称错开；
  // 错开范围钳制在象限内侧（距中线 ≥0.05），不改变象限归属；
  // 单点行保持真实坐标。tooltip 恒显示真实 difficulty_score / impact_ratio。
  const ROW_DY = 0.035; // ≈30px@380px 图高；链式合并保证跨边界点对也被避让
  const MIN_DX = 0.045; // 行内相邻点最小水平间距
  const X_SPAN = 0.15;  // 水平错开上限（0.3/0.7 ± 0.15 → 距中线 0.05）

  function dodgeRows(items) {
    const sorted = items
      .slice()
      .sort(
        (a, b) =>
          a.y - b.y ||
          String(a.label || "").localeCompare(String(b.label || ""))
      );
    let row = null;
    const rows = [];
    sorted.forEach((p) => {
      // 与行内最后一点比较（链式），y 逐渐爬升的点序列会并入同一行，
      // 避免"与行首差一点超阈值"的跨边界点对漏检
      if (!row || p.y - row.pts[row.pts.length - 1].y > ROW_DY) {
        row = { pts: [] };
        rows.push(row);
      }
      row.pts.push(p);
    });
    rows.forEach(({ pts }) => {
      const n = pts.length;
      if (n < 2) return;
      const base = pts[0].x;
      pts.forEach((p, i) => {
        const off = (i - (n - 1) / 2) * MIN_DX;
        const clamped = Math.max(-X_SPAN, Math.min(X_SPAN, off));
        p._x = base + clamped;
        // 行太长被钳到边缘时，向上微移避免再次重叠
        if (clamped !== off) {
          p._y = p.y + (i % 3) * 0.008;
        }
      });
    });
    return sorted;
  }

  /**
   * Matrix 组件类
   */
  class Matrix {
    constructor(canvasId, options) {
      this.canvasId = canvasId;
      this.chart = null;
      this.data = [];
      this.options = Object.assign(
        {
          onPainPointClick: null,
          // 象限分割阈值（影响面/难度均 0~1）
          impactThreshold: 0.15,
          difficultyThreshold: 0.5,
        },
        options || {}
      );
    }

    /**
     * 渲染矩阵
     * @param {Array} matrixData OverviewVO.matrix
     *  [{pain_point_id, label, impact_ratio, difficulty_score, quadrant, priority}]
     */
    render(matrixData) {
      const canvas = document.getElementById(this.canvasId);
      if (!canvas) {
        console.warn("[Matrix] canvas not found:", this.canvasId);
        return;
      }

      if (!matrixData || !matrixData.length) {
        if (this.chart) {
          this.chart.destroy();
          this.chart = null;
        }
        this.data = [];
        return;
      }

      this.data = matrixData.slice();

      // 按 quadrant 分组，每个象限一个 dataset 以独立配色；
      // 同象限内先做散点避让，再映射为坐标
      const quadrants = ["quick_win", "strategic", "filler", "thankless"];
      const datasets = quadrants.map((q) => {
        const items = dodgeRows(
          matrixData.filter((d) => d.quadrant === q).map((d) => ({
            ...d,
            x: d.difficulty_score != null ? +d.difficulty_score.toFixed(3) : 0.5,
            y: d.impact_ratio != null ? +d.impact_ratio.toFixed(3) : 0,
          }))
        );
        return {
          label: quadrantLabel(q),
          data: items.map((d) => ({
            x: +(d._x != null ? d._x : d.x),
            y: +(d._y != null ? d._y : d.y),
          })),
          // thankless 空心（退场），其余实心
          backgroundColor: q === "thankless" ? "transparent" : quadrantColor(q),
          borderColor: quadrantColor(q),
          borderWidth: 2,
          pointRadius: items.map((d) =>
            d.priority === "high" ? 11 : d.priority === "medium" ? 9 : 7
          ),
          pointHoverRadius: 14,
          pointStyle: quadrantShape(q),
          // 自定义数据
          _raw: items,
        };
      });

      if (this.chart) this.chart.destroy();

      const ctx = canvas.getContext("2d");
      const impactThr = this.options.impactThreshold;
      const diffThr = this.options.difficultyThreshold;

      this.chart = new Chart(ctx, {
        type: "scatter",
        data: { datasets: datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          // 同 heatmap：headless/录屏场景必须直接看到完整散点
          animation: false,
          scales: {
            x: {
              min: 0,
              max: 1,
              title: {
                display: true,
                text: "解决难度  →  难",
                color: T.textMuted,
                font: { family: CHART_FONT, size: 12 },
              },
              grid: {
                color: function (ctx) {
                  // 中线高亮
                  if (ctx.tick.value === diffThr) return T.gridMid;
                  return T.grid;
                },
                lineWidth: function (ctx) {
                  return ctx.tick.value === diffThr ? 1.5 : 1;
                },
              },
              ticks: {
                color: T.textFaint,
                font: { family: CHART_FONT_MONO, size: 11 },
                stepSize: 0.2,
                callback: function (v) {
                  if (v === 0) return "易";
                  if (v === 1) return "难";
                  return v.toFixed(1);
                },
              },
            },
            y: {
              min: 0,
              max: Math.max(
                0.4,
                Math.ceil(Math.max(...matrixData.map((d) => d.impact_ratio || 0)) * 10) / 10 + 0.05
              ),
              title: {
                display: true,
                text: "影响面  →  高",
                color: T.textMuted,
                font: { family: CHART_FONT, size: 12 },
              },
              grid: {
                color: function (ctx) {
                  if (ctx.tick.value === impactThr) return T.gridMid;
                  return T.grid;
                },
                lineWidth: function (ctx) {
                  return ctx.tick.value === impactThr ? 1.5 : 1;
                },
              },
              ticks: {
                color: T.textFaint,
                font: { family: CHART_FONT_MONO, size: 11 },
                callback: function (v) {
                  return (v * 100).toFixed(0) + "%";
                },
              },
            },
          },
          plugins: {
            legend: {
              display: false, // 用外部 HTML 图例
            },
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
              displayColors: true,
              boxWidth: 10,
              boxHeight: 10,
              callbacks: {
                title: function (items) {
                  const raw = items[0].dataset._raw[items[0].dataIndex];
                  return raw ? raw.label : "";
                },
                label: function (item) {
                  const raw = item.dataset._raw[item.dataIndex];
                  if (!raw) return "";
                  const lines = [
                    "象限: " + quadrantLabel(raw.quadrant),
                    "影响面: " + (raw.impact_ratio * 100).toFixed(1) + "%",
                    "解决难度: " + (
                      raw.difficulty_score != null
                        ? (raw.difficulty_score * 100).toFixed(0) + "%"
                        : "—"
                    ),
                  ];
                  if (raw.priority) {
                    lines.push(
                      "优先级: " +
                        (raw.priority === "high"
                          ? "高"
                          : raw.priority === "medium"
                          ? "中"
                          : "低")
                    );
                  }
                  lines.push("（点击查看详情）");
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

      // 在图上叠加四象限标注文本（使用 Chart.js 注解插件不可用，用 dataset 上的 afterDraw 替代）
      // 这里通过自定义 plugin 简单绘制象限标签
    }

    /** 销毁 */
    destroy() {
      if (this.chart) {
        this.chart.destroy();
        this.chart = null;
      }
      this.data = [];
    }
  }

  // 暴露
  global.VOC_Matrix = {
    Matrix,
    quadrantColor,
    quadrantLabel,
  };
})(window);
