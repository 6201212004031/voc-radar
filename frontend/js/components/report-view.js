/**
 * VOC Radar — 报告预览组件
 *
 * 职责：
 *  - 通过 VOC_API.getReport 拉取 Markdown 报告
 *  - 用 marked.js 渲染为 HTML + DOMPurify 做 XSS 防护
 *  - 提供下载 Markdown 按钮（直接跳转后端下载接口）
 *
 * 挂载到全局 window.VOC_ReportView
 */
(function (global) {
  "use strict";

  /**
   * 初始化 marked.js
   */
  function initMarked() {
    if (typeof marked === "undefined") {
      console.warn("[ReportView] marked.js 未加载");
      return false;
    }
    if (marked.setOptions) {
      marked.setOptions({
        gfm: true,
        breaks: true,
        headerIds: true,
        mangle: false,
      });
    }
    return true;
  }

  /**
   * 渲染 Markdown 为安全 HTML
   */
  function renderMarkdown(md) {
    if (!initMarked()) {
      return "<pre>" + escapeHtml(md || "") + "</pre>";
    }
    let html;
    try {
      // marked v12: marked.parse
      html = typeof marked.parse === "function" ? marked.parse(md) : marked(md);
    } catch (e) {
      console.error("[ReportView] marked parse error", e);
      return "<pre>" + escapeHtml(md || "") + "</pre>";
    }
    if (typeof DOMPurify !== "undefined") {
      html = DOMPurify.sanitize(html, {
        ALLOWED_TAGS: [
          "h1", "h2", "h3", "h4", "h5", "h6",
          "p", "br", "hr",
          "ul", "ol", "li",
          "table", "thead", "tbody", "tr", "th", "td",
          "strong", "em", "del", "b", "i",
          "code", "pre",
          "blockquote",
          "a", "img",
          "span", "div",
        ],
        ALLOWED_ATTR: ["href", "src", "alt", "title", "class"],
      });
    }
    return html;
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

  /**
   * ReportView 组件类
   */
  class ReportView {
    constructor(options) {
      this.options = Object.assign(
        {
          modalId: "reportModal",
          bodyId: "reportBody",
          downloadBtnId: "downloadMdBtn",
        },
        options || {}
      );
      this.currentProjectId = null;
      this.currentMarkdown = null;
      this._bindEvents();
    }

    /** 绑定弹层关闭事件（仅一次） */
    _bindEvents() {
      if (ReportView._bound) return;
      ReportView._bound = true;
      document.addEventListener("click", (e) => {
        const t = e.target;
        if (t && t.dataset && t.dataset.closeReport !== undefined) {
          if (global.VOC_ReportView && global.VOC_ReportView.instance) {
            global.VOC_ReportView.instance.close();
          }
        }
      });
      document.addEventListener("keydown", (e) => {
        if (
          e.key === "Escape" &&
          global.VOC_ReportView &&
          global.VOC_ReportView.instance &&
          global.VOC_ReportView.instance.isOpen()
        ) {
          global.VOC_ReportView.instance.close();
        }
      });
    }

    isOpen() {
      const el = document.getElementById(this.options.modalId);
      return el && !el.hidden;
    }

    /**
     * 打开报告预览弹层并加载报告
     * @param {string} projectId
     */
    async open(projectId) {
      const modal = document.getElementById(this.options.modalId);
      const body = document.getElementById(this.options.bodyId);
      if (!modal || !body) return;

      this.currentProjectId = projectId;
      modal.hidden = false;
      modal.setAttribute("aria-hidden", "false");
      body.innerHTML =
        '<div class="chart-empty"><span class="loading-spinner"></span> 正在加载报告…</div>';

      try {
        const data = await global.VOC_API.getReport(projectId);
        const md =
          (data && (data.content || data.markdown)) || "# 报告为空\n\n暂无报告内容。";
        this.currentMarkdown = md;
        body.innerHTML = renderMarkdown(md);
        body.classList.add("markdown-body");
      } catch (err) {
        console.error("[ReportView] load error", err);
        body.innerHTML =
          '<div class="chart-empty" style="color:var(--error)">报告加载失败：' +
          escapeHtml(err.message || "未知错误") +
          "</div>";
      }
    }

    /** 关闭弹层 */
    close() {
      const modal = document.getElementById(this.options.modalId);
      if (modal) {
        modal.hidden = true;
        modal.setAttribute("aria-hidden", "true");
      }
    }

    /**
     * 下载 Markdown 报告（浏览器直接跳转后端下载接口）
     * @param {string} projectId
     * @param {string} format md | pdf
     */
    download(projectId, format) {
      const fmt = format || "md";
      const url = global.VOC_API.reportDownloadUrl(projectId, fmt);
      // 使用 a 标签触发下载，避免直接跳转丢失页面状态
      const a = document.createElement("a");
      a.href = url;
      a.download = "voc-radar-report-" + projectId + "." + fmt;
      a.target = "_blank";
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      setTimeout(() => a.remove(), 1000);
    }

    /** 渲染到指定容器（不弹层，用于嵌入页面） */
    async renderInto(containerId, projectId) {
      const el = document.getElementById(containerId);
      if (!el) return;
      el.innerHTML =
        '<div class="chart-empty"><span class="loading-spinner"></span> 正在加载报告…</div>';
      try {
        const data = await global.VOC_API.getReport(projectId);
        const md =
          (data && (data.content || data.markdown)) || "# 报告为空";
        this.currentMarkdown = md;
        el.innerHTML = renderMarkdown(md);
        el.classList.add("markdown-body");
      } catch (err) {
        el.innerHTML =
          '<div class="chart-empty" style="color:var(--error)">报告加载失败：' +
          escapeHtml(err.message || "未知错误") +
          "</div>";
      }
    }
  }

  // 暴露
  global.VOC_ReportView = {
    ReportView,
    renderMarkdown,
    instance: null,
  };
})(window);
