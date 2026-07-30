/**
 * VOC Radar — 应用主逻辑
 *
 * 职责：
 *  - 应用状态管理（当前项目、overview 数据）
 *  - 协调所有组件（heatmap / matrix / detail-panel / suggestions / progress / report-view）
 *  - 绑定顶部导航按钮事件
 *  - 输入解析 → 创建项目 → 触发分析 → SSE 进度 → 加载概览
 *  - KPI 卡片渲染
 *
 * 挂载到全局 window.VOC_App
 */
(function (global) {
  "use strict";

  // ===== 应用状态 =====
  const state = {
    currentProjectId: null,
    overview: null,
    analyzing: false,
    subscription: null,
  };

  // ===== 组件实例 =====
  let heatmap, matrix, detailPanel, suggestions, progress, reportView;

  // ===== 工具 =====
  function $(id) {
    return document.getElementById(id);
  }

  function toast(msg, type) {
    const el = $("toast");
    if (!el) return;
    el.className = "toast" + (type ? " toast-" + type : "");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => {
      el.hidden = true;
    }, 3200);
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
   * 解析输入：判断是品类关键词还是 ASIN 列表
   * @returns {{category:string, competitor_asins:string[], name:string}}
   */
  function parseInput(raw) {
    const text = (raw || "").trim();
    if (!text) return null;

    // 按逗号/空格分割
    const parts = text
      .split(/[,，\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);

    // ASIN 格式：B0 开头 + 8~10 位字母数字
    const asinRegex = /^B0[A-Z0-9]{7,8}$/i;
    const asins = parts.filter((p) => asinRegex.test(p));
    const keywords = parts.filter((p) => !asinRegex.test(p));

    if (asins.length >= 1) {
      return {
        category: keywords.join(" ") || "asin-analysis",
        competitor_asins: asins,
        name: "竞品分析-" + asins[0],
      };
    }
    // 纯关键词 → 当作品类
    return {
      category: keywords.join(" ") || text,
      competitor_asins: [],
      name: "品类分析-" + keywords.join(" "),
    };
  }

  // ===== KPI 卡片渲染 =====
  function renderKPIs(kpis) {
    const row = $("kpiRow");
    if (!row || !kpis) return;

    const cards = [
      {
        label: "竞品数",
        value: kpis.competitor_count || 0,
        sub: "已分析竞品",
        accent: "#4d8dff",
      },
      {
        label: "评论数",
        value: kpis.review_count || 0,
        sub:
          (kpis.negative_review_count || 0) + " 条差评用于聚类",
        accent: "#a6b0cc",
      },
      {
        label: "痛点数",
        value: kpis.pain_point_count || 0,
        sub: "语义聚类得到",
        accent: "#ff7a45",
      },
      {
        label: "R1 归因",
        value: kpis.r1_attribution_count || 0,
        sub: "Top5 根因深度推理",
        accent: "#ff4d4f",
      },
    ];

    row.innerHTML = cards
      .map((c) => {
        return (
          '<div class="kpi-card" style="--kpi-accent:' +
          c.accent +
          '">' +
          '<div class="kpi-label">' +
          c.label +
          "</div>" +
          '<div class="kpi-value">' +
          c.value +
          "</div>" +
          '<div class="kpi-sub">' +
          escapeHtml(c.sub) +
          "</div>" +
          "</div>"
        );
      })
      .join("");
  }

  // ===== 加载概览数据 =====
  async function loadOverview(projectId) {
    try {
      const overview = await global.VOC_API.getOverview(projectId);
      state.overview = overview;
      state.currentProjectId = projectId;

      // KPI
      renderKPIs(overview.kpis);

      // 热力图
      heatmap.render(overview.heatmap || []);

      // 矩阵
      matrix.render(overview.matrix || []);

      // 卖点建议
      suggestions.render(overview.listing_suggestions || []);

      // 切换显示
      $("emptyState").hidden = true;
      $("dashboard").hidden = false;

      // 启用报告按钮
      $("exportReportBtn").disabled = false;
      $("viewReportBtn").disabled = false;

      return overview;
    } catch (err) {
      console.error("[App] loadOverview error", err);
      toast("加载看板失败：" + (err.message || "未知错误"), "error");
      throw err;
    }
  }

  // ===== 触发分析 =====
  async function startAnalysis() {
    if (state.analyzing) {
      toast("分析进行中，请稍候…");
      return;
    }

    const input = $("searchInput").value;
    const parsed = parseInput(input);
    if (!parsed) {
      toast("请输入品类关键词或竞品 ASIN", "error");
      return;
    }

    state.analyzing = true;
    const analyzeBtn = $("analyzeBtn");
    analyzeBtn.disabled = true;
    analyzeBtn.innerHTML =
      '<span class="loading-spinner"></span> 分析中…';

    try {
      // 1. 创建项目
      toast("正在创建分析项目…");
      const project = await global.VOC_API.createProject({
        name: parsed.name,
        category: parsed.category,
        competitor_asins: parsed.competitor_asins,
        config: {
          k_range: [8, 15],
          top_n: 5,
          enable_r1: true,
          enable_vision: false,
        },
      });

      const projectId = project.id || (project.project && project.project.id);
      if (!projectId) {
        throw new Error("创建项目失败：未返回项目 ID");
      }
      state.currentProjectId = projectId;

      // 2. 显示进度区
      progress.start(projectId);

      // 3. 触发 pipeline
      await global.VOC_API.analyze(projectId, {
        k_range: [8, 15],
        top_n: 5,
        enable_r1: true,
        enable_vision: false,
      });

      // SSE 由 progress 组件接收，complete 回调里加载 overview
    } catch (err) {
      console.error("[App] startAnalysis error", err);
      toast("分析启动失败：" + (err.message || "未知错误"), "error");
      progress.setMessage("❌ 分析启动失败：" + (err.message || ""), true);
      state.analyzing = false;
      analyzeBtn.disabled = false;
      analyzeBtn.textContent = "开始分析";
    }
  }

  // ===== Pipeline 完成回调 =====
  function onPipelineComplete(data) {
    state.analyzing = false;
    const analyzeBtn = $("analyzeBtn");
    analyzeBtn.disabled = false;
    analyzeBtn.textContent = "重新分析";

    toast("分析完成，正在加载看板…", "success");

    // 延迟一下让用户看到完成提示
    setTimeout(async () => {
      if (state.currentProjectId) {
        try {
          await loadOverview(state.currentProjectId);
          progress.hide();
        } catch (e) {
          /* 已有 toast */
        }
      }
    }, 600);
  }

  function onPipelineError(data) {
    state.analyzing = false;
    const analyzeBtn = $("analyzeBtn");
    analyzeBtn.disabled = false;
    analyzeBtn.textContent = "重新分析";
    toast(
      "Pipeline 出错：" + ((data && data.message) || "未知错误"),
      "error"
    );
  }

  // ===== 痛点点击下钻 =====
  function onPainPointClick(item) {
    if (!item || !item.pain_point_id) return;
    detailPanel.open(item.pain_point_id);
  }

  // ===== 导出报告 =====
  function exportReport() {
    if (!state.currentProjectId) {
      toast("请先完成一次分析", "error");
      return;
    }
    reportView.download(state.currentProjectId, "md");
    toast("正在下载 Markdown 报告…", "success");
  }

  // ===== 预览报告 =====
  function viewReport() {
    if (!state.currentProjectId) {
      toast("请先完成一次分析", "error");
      return;
    }
    reportView.open(state.currentProjectId);
  }

  // ===== 初始化 =====
  function init() {
    // 实例化组件
    heatmap = new global.VOC_Heatmap.Heatmap("heatmapCanvas", {
      onPainPointClick: onPainPointClick,
      emptyHintId: "heatmapEmpty",
    });

    matrix = new global.VOC_Matrix.Matrix("matrixCanvas", {
      onPainPointClick: onPainPointClick,
    });

    detailPanel = new global.VOC_DetailPanel.DetailPanel({
      onReviewClick: null,
    });
    global.VOC_DetailPanel.instance = detailPanel;

    suggestions = new global.VOC_Suggestions.Suggestions("suggestionsList", {
      emptyHintId: "suggestionsEmpty",
    });

    progress = new global.VOC_Progress.Progress("progressSection", {
      onComplete: onPipelineComplete,
      onError: onPipelineError,
    });

    reportView = new global.VOC_ReportView.ReportView();
    global.VOC_ReportView.instance = reportView;

    // 绑定顶部导航事件
    $("analyzeBtn").addEventListener("click", startAnalysis);
    $("exportReportBtn").addEventListener("click", exportReport);
    $("viewReportBtn").addEventListener("click", viewReport);

    // 回车触发分析
    $("searchInput").addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        startAnalysis();
      }
    });

    // 下载 Markdown 按钮
    const dlBtn = $("downloadMdBtn");
    if (dlBtn) {
      dlBtn.addEventListener("click", function () {
        if (state.currentProjectId) {
          reportView.download(state.currentProjectId, "md");
        }
      });
    }

    // 暴露调试入口
    global.VOC_App = {
      state: state,
      loadOverview: loadOverview,
      startAnalysis: startAnalysis,
      openPainPoint: onPainPointClick,
      components: {
        heatmap: heatmap,
        matrix: matrix,
        detailPanel: detailPanel,
        suggestions: suggestions,
        progress: progress,
        reportView: reportView,
      },
    };

    console.info(
      "%cVOC Radar 评论雷达 已就绪",
      "color:#4d8dff;font-weight:bold;font-size:14px;"
    );
  }

  // DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
