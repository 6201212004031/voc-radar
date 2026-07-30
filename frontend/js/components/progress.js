/**
 * VOC Radar — Pipeline 进度条组件
 *
 * 职责：
 *  - 通过 SSE 接收后端 pipeline 进度（VOC_API.subscribeProgress）
 *  - 渲染进度条 + 当前阶段 + 阶段提示
 *  - 支持 7 个阶段：s1_ingest ~ s7_report
 *  - 错误/完成状态展示
 *
 * SSE 事件：
 *  - progress   {stage, progress, message, timestamp}
 *  - stage_done {stage, duration_ms, output_summary}
 *  - error      {stage, message, error_code}
 *  - complete   {project_id, status, report_url}
 *
 * 挂载到全局 window.VOC_Progress
 */
(function (global) {
  "use strict";

  const STAGES = [
    { key: "s1_ingest", label: "数据加载", tip: "加载 Kaggle 评论数据集 / 手动采集评论" },
    { key: "s2_preprocess", label: "评论预处理", tip: "去重、过滤非 VP、元数据提取" },
    { key: "s3_cluster", label: "语义聚类", tip: "text-embedding-v4 向量化 + K-Means 聚类" },
    { key: "s4_label", label: "痛点标签生成", tip: "qwen-max 为每簇生成标签 + 分级判断" },
    { key: "s5_attribute", label: "R1 根因归因", tip: "DeepSeek-R1 对 Top 5 痛点深度推理" },
    { key: "s6_suggest", label: "改进建议生成", tip: "qwen-max 整合归因 → 改进建议 + Listing 卖点" },
    { key: "s7_report", label: "报告整合", tip: "Jinja2 渲染 Markdown 报告" },
  ];

  // 阶段进度区间（用于进度条平滑显示）
  const STAGE_RANGES = {
    s1_ingest: [0.0, 0.15],
    s2_preprocess: [0.15, 0.25],
    s3_cluster: [0.25, 0.45],
    s4_label: [0.45, 0.6],
    s5_attribute: [0.6, 0.8],
    s6_suggest: [0.8, 0.92],
    s7_report: [0.92, 1.0],
  };

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
   * Progress 组件类
   */
  class Progress {
    constructor(sectionId, options) {
      this.sectionId = sectionId;
      this.options = Object.assign(
        {
          onComplete: null, // pipeline 完成回调
          onError: null, // pipeline 错误回调
        },
        options || {}
      );
      this.cancelSubscription = null;
      this.completedStages = new Set();
      this.currentStage = null;
      this.lastProgress = 0;
    }

    /** 显示进度区并初始化骨架 */
    show() {
      const sec = document.getElementById(this.sectionId);
      if (!sec) return;
      sec.hidden = false;
      this._renderSkeleton();
    }

    hide() {
      const sec = document.getElementById(this.sectionId);
      if (sec) sec.hidden = true;
      this.stop();
    }

    _renderSkeleton() {
      const sec = document.getElementById(this.sectionId);
      sec.innerHTML =
        '<div class="progress-bar-wrap"><div class="progress-bar-fill" id="progressBarFill" style="width:0%"></div></div>' +
        '<div class="progress-meta">' +
        '  <div class="progress-stages" id="progressStages"></div>' +
        '  <div class="progress-message" id="progressMessage">等待 pipeline 启动…</div>' +
        "</div>";

      const stagesEl = document.getElementById("progressStages");
      stagesEl.innerHTML = STAGES.map((s) => {
        return (
          '<span class="progress-stage" data-stage="' +
          s.key +
          '">' +
          '<span class="stage-dot"></span>' +
          '<span class="stage-label">' +
          s.label +
          "</span></span>"
        );
      }).join('<span style="color:var(--text-muted);margin:0 4px;">›</span>');
    }

    /**
     * 订阅 SSE 进度流
     * @param {string} projectId
     */
    start(projectId) {
      this.show();
      this.completedStages = new Set();
      this.currentStage = null;
      this.lastProgress = 0;

      const self = this;
      this.cancelSubscription = global.VOC_API.subscribeProgress(projectId, {
        onOpen: function () {
          self._setMessage("已连接，等待 pipeline 推送进度…");
        },
        onProgress: function (data) {
          self._onProgress(data);
        },
        onStageDone: function (data) {
          self._onStageDone(data);
        },
        onError: function (data) {
          self._onError(data);
        },
        onComplete: function (data) {
          self._onComplete(data);
        },
        onClose: function () {
          // 连接关闭（非 complete）— 视为正常结束或后端主动断开
        },
      });
    }

    /** 停止订阅 */
    stop() {
      if (this.cancelSubscription) {
        try {
          this.cancelSubscription();
        } catch (e) {
          /* noop */
        }
        this.cancelSubscription = null;
      }
    }

    _onProgress(data) {
      if (!data) return;
      const stage = data.stage;
      const progress = data.progress != null ? data.progress : this.lastProgress;
      this.currentStage = stage;

      // 进度条
      const fill = document.getElementById("progressBarFill");
      if (fill) {
        // 后端给的 progress 是 0~1 的全局进度；如果只是阶段进度，按区间映射
        let pct;
        if (progress > 1) pct = Math.min(100, progress);
        else pct = Math.min(100, progress * 100);
        fill.style.width = pct + "%";
        this.lastProgress = progress;
      }

      // 阶段点状态
      this._updateStageDots(stage);

      // 消息
      if (data.message) {
        this._setMessage(data.message);
      }
    }

    _onStageDone(data) {
      if (!data || !data.stage) return;
      this.completedStages.add(data.stage);
      this._updateStageDots(this.currentStage);

      // 阶段完成提示
      const stageInfo = STAGES.find((s) => s.key === data.stage);
      if (stageInfo && data.output_summary) {
        this._setMessage(
          "✅ " + stageInfo.label + " 完成：" + data.output_summary
        );
      }
    }

    _onError(data) {
      const msg = (data && data.message) || "pipeline 执行出错";
      const code = (data && data.error_code) || "UNKNOWN";
      this._setMessage("❌ " + msg + "（错误码：" + code + "）", true);

      // 标记当前阶段为错误
      if (data && data.stage) {
        const stageEl = document.querySelector(
          '.progress-stage[data-stage="' + data.stage + '"] .stage-dot'
        );
        if (stageEl) {
          stageEl.style.background = "var(--error)";
          stageEl.style.boxShadow = "0 0 0 4px rgba(255,77,79,0.18)";
        }
      }

      if (this.options.onError) this.options.onError(data);
    }

    _onComplete(data) {
      const fill = document.getElementById("progressBarFill");
      if (fill) fill.style.width = "100%";

      // 全部阶段标记完成
      STAGES.forEach((s) => this.completedStages.add(s.key));
      this._updateStageDots(null);

      this._setMessage("🎉 分析完成！报告已生成。", false, true);

      if (this.options.onComplete) this.options.onComplete(data);
    }

    _updateStageDots(currentStage) {
      const dots = document.querySelectorAll(".progress-stage");
      dots.forEach((el) => {
        const stage = el.getAttribute("data-stage");
        const dot = el.querySelector(".stage-dot");
        if (!dot) return;
        dot.classList.remove("active", "done");
        if (this.completedStages.has(stage)) {
          dot.classList.add("done");
        } else if (stage === currentStage) {
          dot.classList.add("active");
        }
      });
    }

    _setMessage(msg, isError, isSuccess) {
      const el = document.getElementById("progressMessage");
      if (!el) return;
      el.className = "progress-message";
      if (isError) el.classList.add("progress-error");
      el.innerHTML = escapeHtml(msg);
    }

    /** 设置静态消息（外部调用，如未启动时） */
    setMessage(msg, isError) {
      this._setMessage(msg, isError);
    }
  }

  // 暴露
  global.VOC_Progress = {
    Progress,
    STAGES,
  };
})(window);
