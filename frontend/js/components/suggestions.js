/**
 * VOC Radar — 差异化卖点建议清单组件
 *
 * 职责：
 *  - 渲染"竞品共性弱点 → Listing 卖点建议"清单
 *  - 标注优先级（高/中/低）和 Listing 字段（title/bullet_point/a_plus_content/image）
 *  - 显示建议理由
 *
 * 数据来源：OverviewVO.listing_suggestions
 * 挂载到全局 window.VOC_Suggestions
 */
(function (global) {
  "use strict";

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function priorityClass(p) {
    switch (p) {
      case "high":
        return "tag-priority-high";
      case "medium":
        return "tag-priority-medium";
      case "low":
        return "tag-priority-low";
      default:
        return "tag-priority-low";
    }
  }

  function priorityText(p) {
    switch (p) {
      case "high":
        return "高优先级";
      case "medium":
        return "中优先级";
      case "low":
        return "低优先级";
      default:
        return p || "—";
    }
  }

  function fieldClass(f) {
    switch (f) {
      case "title":
        return "tag-field-title";
      case "bullet_point":
        return "tag-field-bullet_point";
      case "a_plus_content":
        return "tag-field-a_plus_content";
      case "image":
        return "tag-field-image";
      default:
        return "tag-field-title";
    }
  }

  function fieldText(f) {
    switch (f) {
      case "title":
        return "标题";
      case "bullet_point":
        return "五点描述";
      case "a_plus_content":
        return "A+ 内容";
      case "image":
        return "主图";
      default:
        return f || "—";
    }
  }

  /**
   * Suggestions 组件类
   */
  class Suggestions {
    constructor(listId, options) {
      this.listId = listId;
      this.options = Object.assign(
        {
          emptyHintId: null,
        },
        options || {}
      );
    }

    /**
     * 渲染卖点建议清单
     * @param {Array} suggestions OverviewVO.listing_suggestions
     */
    render(suggestions) {
      const list = document.getElementById(this.listId);
      if (!list) {
        console.warn("[Suggestions] list not found:", this.listId);
        return;
      }

      const emptyEl = this.options.emptyHintId
        ? document.getElementById(this.options.emptyHintId)
        : null;

      if (!suggestions || !suggestions.length) {
        list.innerHTML = "";
        if (emptyEl) emptyEl.hidden = false;
        return;
      }
      if (emptyEl) emptyEl.hidden = true;

      // 按优先级排序：high > medium > low
      const order = { high: 0, medium: 1, low: 2 };
      const sorted = suggestions.slice().sort((a, b) => {
        return (order[a.priority] || 3) - (order[b.priority] || 3);
      });

      list.innerHTML = sorted
        .map((s) => {
          return (
            '<li class="suggestion-item">' +
            '<div class="suggestion-weakness">竞品共性弱点：' +
            escapeHtml(s.competitor_weakness || "—") +
            "</div>" +
            '<div class="suggestion-point">→ ' +
            escapeHtml(s.suggested_selling_point || "—") +
            "</div>" +
            '<div class="suggestion-meta">' +
            '<span class="tag ' +
            priorityClass(s.priority) +
            '">' +
            priorityText(s.priority) +
            "</span>" +
            '<span class="tag ' +
            fieldClass(s.listing_field) +
            '">' +
            fieldText(s.listing_field) +
            "</span>" +
            "</div>" +
            (s.rationale
              ? '<div class="suggestion-rationale">' +
                escapeHtml(s.rationale) +
                "</div>"
              : "") +
            "</li>"
          );
        })
        .join("");
    }

    clear() {
      const list = document.getElementById(this.listId);
      if (list) list.innerHTML = "";
    }
  }

  // 暴露
  global.VOC_Suggestions = {
    Suggestions,
  };
})(window);
