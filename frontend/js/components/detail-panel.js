/**
 * VOC Radar — 痛点下钻详情面板组件
 *
 * 职责：
 *  - 渲染右侧抽屉式下钻面板
 *  - 三大区域：
 *    1) 根因归因（根因 + 证据引用 + 改进措施；主力模型由 ATTRIBUTION_MODEL 配置）
 *    2) 代表性评论（代表性优先、按点赞数排序，可展开原文）
 *    3) 竞品对比（各竞品该痛点占比/星级/是否共性）
 *  - 通过 VOC_API.getPainPointDetail 拉取数据
 *  - 支持"查看原文"滚动定位 + 高亮
 *
 * 挂载到全局 window.VOC_DetailPanel
 */
(function (global) {
  "use strict";

  /**
   * 星级渲染 —— CSS 星条：5 个 3×8px 方块，实=sev-2 / 空=bg-elev-3
   * 不用星形字符，避免字形缺失与灰度下的歧义
   * @param {number} rating 1~5
   */
  function renderStars(rating) {
    const r = Math.round((rating || 0) * 2) / 2; // 0.5 步进
    const full = Math.floor(r);
    const half = r - full >= 0.5;
    let s = '<span class="stars" aria-hidden="true">';
    for (let i = 0; i < 5; i++) {
      const on = i < full || (i === full && half);
      s += '<i class="seg' + (on ? " on" : "") + '"></i>';
    }
    s += "</span>";
    return s;
  }

  function trendText(trend) {
    switch (trend) {
      case "rising":
        return "上升 ↗（恶化）";
      case "falling":
        return "下降 ↘（改善）";
      case "stable":
        return "稳定 →";
      default:
        return "未知";
    }
  }

  function trendClass(trend) {
    switch (trend) {
      case "rising":
        return "trend-rising";
      case "falling":
        return "trend-falling";
      default:
        return "trend-stable";
    }
  }

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function costText(cost) {
    switch (cost) {
      case "low":
        return "低";
      case "medium":
        return "中";
      case "high":
        return "高";
      default:
        return cost || "—";
    }
  }

  function priorityText(p) {
    switch (p) {
      case "high":
        return "高";
      case "medium":
        return "中";
      case "low":
        return "低";
      default:
        return p || "—";
    }
  }

  /**
   * DetailPanel 组件类
   */
  class DetailPanel {
    constructor(options) {
      this.options = Object.assign(
        {
          panelId: "detailPanel",
          bodyId: "detailBody",
          titleId: "detailTitle",
          onReviewClick: null, // 点击"查看原文"回调（review_id）
        },
        options || {}
      );
      this.currentData = null;
      this._bindClose();
    }

    /** 绑定关闭事件（仅绑定一次） */
    _bindClose() {
      if (DetailPanel._bound) return;
      DetailPanel._bound = true;
      document.addEventListener("click", function (e) {
        const t = e.target;
        if (t && t.dataset && t.dataset.closeDetail !== undefined) {
          if (global.VOC_DetailPanel && global.VOC_DetailPanel.instance) {
            global.VOC_DetailPanel.instance.close();
          }
        }
      });
      // ESC 关闭
      document.addEventListener("keydown", function (e) {
        if (
          e.key === "Escape" &&
          global.VOC_DetailPanel &&
          global.VOC_DetailPanel.instance &&
          global.VOC_DetailPanel.instance.isOpen()
        ) {
          global.VOC_DetailPanel.instance.close();
        }
      });
    }

    isOpen() {
      const el = document.getElementById(this.options.panelId);
      return el && !el.hidden;
    }

    /**
     * 打开面板并加载痛点详情
     * @param {string} painPointId
     */
    async open(painPointId) {
      const panel = document.getElementById(this.options.panelId);
      const body = document.getElementById(this.options.bodyId);
      const title = document.getElementById(this.options.titleId);
      if (!panel || !body) return;

      panel.hidden = false;
      panel.setAttribute("aria-hidden", "false");
      title.textContent = "痛点详情加载中…";
      body.innerHTML =
        '<div class="chart-empty"><span class="loading-spinner"></span> 正在拉取痛点详情…</div>';

      try {
        const data = await global.VOC_API.getPainPointDetail(painPointId);
        this.currentData = data;
        this._render(data);
      } catch (err) {
        console.error("[DetailPanel] load error", err);
        body.innerHTML =
          '<div class="chart-empty" style="color:var(--error)">加载失败：' +
          escapeHtml(err.message || "未知错误") +
          "</div>";
      }
    }

    /** 渲染详情内容 */
    _render(data) {
      const body = document.getElementById(this.options.bodyId);
      const title = document.getElementById(this.options.titleId);
      const pp = (data && data.pain_point) || {};
      const attr = data && data.attribution;
      const reviews = (data && data.representative_reviews) || [];
      const compare = (data && data.competitor_comparison) || [];

      title.innerHTML = "痛点：" + escapeHtml(pp.label || "—");

      const impactPct = pp.impact_ratio != null
        ? (pp.impact_ratio * 100).toFixed(1)
        : "—";
      const reviewCount = pp.review_count || 0;

      let html = "";

      // ===== 摘要条 =====
      // 阈值是业务逻辑（0.25 / 0.15）不动，颜色改引用 token
      html +=
        '<div class="detail-summary" style="border-left-color:' +
        (pp.impact_ratio >= 0.25
          ? "var(--sev-5)"
          : pp.impact_ratio >= 0.15
          ? "var(--sev-4)"
          : "var(--sev-3)") +
        '">';
      html +=
        '<div class="summary-item"><span class="summary-label">影响面</span><span class="summary-value">' +
        impactPct +
        "%</span></div>";
      html +=
        '<div class="summary-item"><span class="summary-label">评论数</span><span class="summary-value">' +
        reviewCount +
        "</span></div>";
      html +=
        '<div class="summary-item"><span class="summary-label">平均星级</span><span class="summary-value">' +
        (pp.avg_rating != null ? pp.avg_rating.toFixed(1) : "—") +
        "</span></div>";
      html +=
        '<div class="summary-item"><span class="summary-label">趋势</span><span class="summary-value ' +
        trendClass(pp.trend) +
        '">' +
        trendText(pp.trend) +
        "</span></div>";
      if (pp.is_top5) {
        html +=
          '<div class="summary-item"><span class="summary-label">归因级别</span><span class="summary-value" style="color:var(--accent)">Top5 深度归因</span></div>';
      }
      if (pp.is_common_weakness) {
        html +=
          '<div class="summary-item"><span class="summary-label">共性弱点</span><span class="summary-value" style="color:var(--sev-5)">✓ 是</span></div>';
      }
      html += "</div>";

      if (pp.description) {
        html +=
          '<p style="color:var(--text-secondary);font-size:13px;margin-top:-8px;">' +
          escapeHtml(pp.description) +
          "</p>";
      }

      // ===== 根因归因（主力模型由后端 ATTRIBUTION_MODEL 配置决定，默认 qwen3.7-max） =====
      html += '<section class="detail-section">';
      html +=
        '<h3><span class="lbl-zh">根因归因</span><span class="lbl-en">Root Cause</span></h3>';
      if (attr && attr.root_cause) {
        html += '<div class="attribution-box">';
        html +=
          '<div class="root-cause"><strong>根因：</strong>' +
          escapeHtml(attr.root_cause) +
          "</div>";

        if (attr.evidence && attr.evidence.length) {
          html +=
            '<div style="font-size:12px;color:var(--text-muted);margin-bottom:6px;">证据引用（共 ' +
            attr.evidence.length +
            " 条）：</div>";
          html += '<ul class="evidence-list">';
          attr.evidence.forEach((ev) => {
            html += '<li class="evidence-item">';
            html +=
              '<div class="evidence-quote">' +
              escapeHtml(ev.quote || "") +
              "</div>";
            html += '<div class="evidence-meta">';
            html += renderStars(ev.rating);
            // 数值评分必须与星条同时可读：这是评委核对 AI 归因结论可信度的直接依据
            html +=
              '<span class="meta-rating">RATING ' +
              (ev.rating != null ? Number(ev.rating).toFixed(1) : "—") +
              "</span> · ";
            html +=
              '<span class="meta-helpful">HELPFUL ' +
              (ev.helpful_votes || 0) +
              "</span> · ";
            if (ev.asin) html += escapeHtml(ev.asin) + " · ";
            if (ev.review_id) {
              html +=
                '<a class="evidence-link" data-review-id="' +
                escapeHtml(ev.review_id) +
                '">查看原文</a>';
            }
            html += "</div>";
            html += "</li>";
          });
          html += "</ul>";
        }

        if (attr.improvement_measures && attr.improvement_measures.length) {
          html +=
            '<div style="font-size:12px;color:var(--text-muted);margin-bottom:6px;">改进措施：</div>';
          html += '<ul class="measures-list">';
          attr.improvement_measures.forEach((m) => {
            html += '<li class="measure-item">';
            html +=
              '<div><div>' +
              escapeHtml(m.measure || "") +
              "</div>";
            html +=
              '<div style="font-size:11px;color:var(--text-muted);margin-top:2px;">成本：' +
              costText(m.cost) +
              " · 优先级：" +
              priorityText(m.priority) +
              "</div></div>";
            html += "</li>";
          });
          html += "</ul>";
        }

        if (attr.model_used) {
          html +=
            '<div style="margin-top:8px;font-size:11px;color:var(--text-muted);">模型：<span class="model-badge">' +
            escapeHtml(attr.model_used) +
            "</span></div>";
        }
        html += "</div>";
      } else {
        html +=
          '<div class="chart-empty">该痛点未进入根因归因 Top5，无归因数据。<br><span style="font-size:11px;color:var(--text-muted);">说明：仅适合深度推理的痛点（体验型/环境触发型）会进入 Top5 归因。</span></div>';
      }
      html += "</section>";

      // ===== 代表性评论 =====
      html += '<section class="detail-section">';
      html +=
        '<h3><span class="lbl-zh">代表性评论（Top ' +
        reviews.length +
        '，按点赞数排序）</span><span class="lbl-en">Evidence</span></h3>';
      if (reviews.length) {
        html += '<div class="review-list" id="reviewList">';
        reviews.forEach((rv, idx) => {
          const full = !!rv.body;
          html +=
            '<div class="review-card" id="review-' +
            escapeHtml(rv.id || idx) +
            '" data-review-id="' +
            escapeHtml(rv.id || "") +
            '">';
          html += '<div class="review-head">';
          html +=
            renderStars(rv.rating) +
            '<span title="' +
            (rv.rating || 0) +
            '星">' +
            (rv.rating || 0) +
            "星</span>";
          if (rv.date) html += " · " + escapeHtml(rv.date);
          if (rv.variant) html += " · 变体：" + escapeHtml(rv.variant);
          html +=
            ' · <span class="meta-helpful">HELPFUL ' +
            (rv.helpful_votes || 0) +
            "</span>";
          if (rv.asin) html += " · " + escapeHtml(rv.asin);
          html += "</div>";
          if (rv.title) {
            html +=
              '<div class="review-title">' + escapeHtml(rv.title) + "</div>";
          }
          html +=
            '<div class="review-body">' + escapeHtml(rv.body || "") + "</div>";
          html += '<div class="review-actions">';
          if (full) {
            html +=
              '<a data-toggle-review="' +
              escapeHtml(rv.id || idx) +
              '">查看全文</a>';
          }
          if (rv.has_image && rv.image_urls && rv.image_urls.length) {
            html +=
              ' · <a data-view-images="' +
              escapeHtml(rv.id || idx) +
              '">查看买家秀图片 (' +
              rv.image_urls.length +
              ")</a>";
          }
          html += "</div>";
          html += "</div>";
        });
        html += "</div>";
      } else {
        html += '<div class="chart-empty">暂无代表性评论</div>';
      }
      html += "</section>";

      // ===== 竞品对比 =====
      html += '<section class="detail-section">';
      html +=
        '<h3><span class="lbl-zh">竞品对比</span><span class="lbl-en">Benchmark</span></h3>';
      if (compare.length) {
        html += '<table class="compare-table">';
        html += "<thead><tr>";
        html += "<th>竞品</th>";
        html += "<th>痛点占比</th>";
        html += "<th>平均星级</th>";
        html += "<th>是否共性</th>";
        html += "</tr></thead><tbody>";
        compare.forEach((c) => {
          html += "<tr>";
          html +=
            "<td>" +
            escapeHtml(c.product_name || c.asin || "—") +
            (c.asin && c.product_name
              ? '<br><span style="font-size:11px;color:var(--text-muted);">' +
                escapeHtml(c.asin) +
                "</span>"
              : "") +
            "</td>";
          html +=
            "<td>" +
            (c.pain_ratio != null
              ? (c.pain_ratio * 100).toFixed(1) + "%"
              : "—") +
            "</td>";
          html +=
            "<td>" +
            (c.avg_rating != null ? c.avg_rating.toFixed(1) : "—") +
            "</td>";
          html +=
            "<td>" +
            (c.is_common
              ? '<span class="common-badge">共性</span>'
              : '<span style="color:var(--text-faint)">—</span>') +
            "</td>";
          html += "</tr>";
        });
        html += "</tbody></table>";

        // 共性弱点提示
        const commonCount = compare.filter((c) => c.is_common).length;
        if (commonCount >= 2) {
          html +=
            '<div class="common-hint">这是品类共性弱点（' +
            commonCount +
            "/" +
            compare.length +
            ' 个竞品都有），解决它是你的核心差异化机会。</div>';
        }
      } else {
        html += '<div class="chart-empty">暂无竞品对比数据</div>';
      }
      html += "</section>";

      body.innerHTML = html;

      // 绑定交互
      this._bindInteractions(data);
    }

    /** 绑定面板内交互（展开评论、查看原文、查看图片） */
    _bindInteractions(data) {
      const body = document.getElementById(this.options.bodyId);
      if (!body) return;

      const self = this;

      // 展开/收起评论全文
      body.querySelectorAll("[data-toggle-review]").forEach((el) => {
        el.addEventListener("click", function (e) {
          e.preventDefault();
          const id = this.getAttribute("data-toggle-review");
          const card = document.getElementById("review-" + id);
          if (card) {
            card.classList.toggle("expanded");
            this.textContent = card.classList.contains("expanded")
              ? "收起"
              : "查看全文";
          }
        });
      });

      // 查看原文（滚动定位 + 高亮）— 证据引用里的链接
      body.querySelectorAll("[data-review-id]").forEach((el) => {
        el.addEventListener("click", function (e) {
          e.preventDefault();
          const rid = this.getAttribute("data-review-id");
          const card = document.getElementById("review-" + rid);
          if (card) {
            card.classList.add("highlight");
            card.scrollIntoView({ behavior: "smooth", block: "center" });
            // 展开
            card.classList.add("expanded");
            const toggle = card.querySelector("[data-toggle-review]");
            if (toggle) toggle.textContent = "收起";
            setTimeout(() => card.classList.remove("highlight"), 2400);
          } else if (self.options.onReviewClick) {
            self.options.onReviewClick(rid);
          }
        });
      });

      // 查看买家秀图片（原型阶段：简易灯箱）
      body.querySelectorAll("[data-view-images]").forEach((el) => {
        el.addEventListener("click", function (e) {
          e.preventDefault();
          const id = this.getAttribute("data-view-images");
          const reviews = (data && data.representative_reviews) || [];
          const rv = reviews.find((r) => r.id === id);
          if (rv && rv.image_urls && rv.image_urls.length) {
            self._showLightbox(rv.image_urls, rv.title || "买家秀图片");
          }
        });
      });
    }

    /** 简易图片灯箱 */
    _showLightbox(urls, title) {
      const existing = document.getElementById("vocLightbox");
      if (existing) existing.remove();

      const lb = document.createElement("div");
      lb.id = "vocLightbox";
      lb.className = "voc-lightbox";
      lb.innerHTML =
        '<div class="voc-lightbox-title">' +
        escapeHtml(title || "图片预览") +
        '</div><div class="voc-lightbox-images"></div>' +
        '<button class="btn btn-ghost voc-lightbox-close" type="button">关闭</button>';
      const imgBox = lb.querySelector(".voc-lightbox-images");
      urls.forEach((u) => {
        const img = document.createElement("img");
        img.src = u;
        img.alt = title || "买家秀";
        imgBox.appendChild(img);
      });
      lb.querySelector("button").addEventListener("click", () => lb.remove());
      lb.addEventListener("click", (e) => {
        if (e.target === lb) lb.remove();
      });
      document.body.appendChild(lb);
    }

    /** 关闭面板 */
    close() {
      const panel = document.getElementById(this.options.panelId);
      if (panel) {
        panel.hidden = true;
        panel.setAttribute("aria-hidden", "true");
      }
      this.currentData = null;
    }
  }

  // 暴露
  global.VOC_DetailPanel = {
    DetailPanel,
    instance: null,
  };
})(window);
