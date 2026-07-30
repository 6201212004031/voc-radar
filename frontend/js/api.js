/**
 * VOC Radar — API 客户端封装
 *
 * 职责：
 *  - 封装所有后端 REST 接口（fetch + 统一错误处理）
 *  - 提供 SSE 进度流接收器
 *  - 统一解析响应体 {code, message, data, request_id}
 *
 * 后端 API 前缀：/api/v1
 * 挂载到全局 window.VOC_API
 */
(function (global) {
  "use strict";

  // ===== 配置 =====
  const API_BASE =
    (global.VOC_CONFIG && global.VOC_CONFIG.API_BASE) || "/api/v1";
  const DEFAULT_TIMEOUT_MS = 30000;

  // ===== 业务错误码 → 文案 =====
  const ERROR_MESSAGES = {
    1001: "项目不存在",
    1002: "项目状态非法（可能正在运行中）",
    2001: "数据集缺失，请联系管理员放置数据",
    2002: "数据预处理失败",
    3001: "向量化失败",
    3002: "聚类失败",
    4001: "AI 模型调用失败（超时/限流/网络）",
    4002: "AI 输出解析失败",
    5001: "报告渲染失败",
  };

  // ===== 工具：超时 fetch =====
  function fetchWithTimeout(url, options, timeoutMs) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs || DEFAULT_TIMEOUT_MS);
    return fetch(url, Object.assign({ signal: ctrl.signal }, options || {}))
      .finally(() => clearTimeout(timer));
  }

  // ===== 统一响应解析 =====
  async function parseResponse(resp) {
    const requestId = resp.headers.get("X-Request-Id") || "-";
    let body;
    try {
      body = await resp.json();
    } catch (e) {
      throw new ApiError(
        "PARSE_ERROR",
        "响应体解析失败（非 JSON）",
        null,
        requestId,
        resp.status
      );
    }
    if (!resp.ok || body.code !== 0) {
      const msg =
        body.message ||
        ERROR_MESSAGES[body.code] ||
        `HTTP ${resp.status} 请求失败`;
      throw new ApiError(
        body.code || resp.status,
        msg,
        body.data,
        body.request_id || requestId,
        resp.status
      );
    }
    return { data: body.data, requestId: body.request_id || requestId };
  }

  // ===== 自定义异常 =====
  class ApiError extends Error {
    constructor(code, message, data, requestId, httpStatus) {
      super(message);
      this.name = "ApiError";
      this.code = code;
      this.data = data;
      this.requestId = requestId;
      this.httpStatus = httpStatus;
    }
  }

  // ===== 通用请求方法 =====
  async function request(method, path, payload, query, options) {
    const url = buildUrl(path, query);
    const opts = Object.assign({ method, headers: {} }, options || {});
    if (payload != null) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(payload);
    }
    if (options && options.headers) {
      opts.headers = Object.assign({}, opts.headers, options.headers);
    }
    const resp = await fetchWithTimeout(url, opts, options && options.timeoutMs);
    return parseResponse(resp);
  }

  function buildUrl(path, query) {
    const base = API_BASE.replace(/\/$/, "");
    const p = path.startsWith("/") ? path : "/" + path;
    let url = base + p;
    if (query && Object.keys(query).length) {
      const qs = new URLSearchParams();
      Object.keys(query).forEach((k) => {
        if (query[k] !== undefined && query[k] !== null) {
          qs.append(k, query[k]);
        }
      });
      url += "?" + qs.toString();
    }
    return url;
  }

  // ===== API 方法定义 =====
  const api = {
    ApiError,

    /** 健康检查（可选）— /health 挂在根路径，不在 /api/v1 下 */
    health() {
      return fetchWithTimeout("/health", { method: "GET" })
        .then(() => ({ data: { status: "ok" } }))
        .catch(() => ({ data: null }));
    },

    // -------- 项目管理 --------
    /** 创建分析项目 */
    createProject(payload) {
      return request("POST", "/projects", payload).then((r) => r.data);
    },

    /** 项目列表 */
    listProjects(page, size) {
      return request("GET", "/projects", null, {
        page: page || 1,
        size: size || 20,
      }).then((r) => r.data);
    },

    /** 项目详情 */
    getProject(id) {
      return request("GET", "/projects/" + encodeURIComponent(id)).then(
        (r) => r.data
      );
    },

    /** 删除项目 */
    deleteProject(id) {
      return request("DELETE", "/projects/" + encodeURIComponent(id)).then(
        (r) => r.data
      );
    },

    // -------- 触发分析 --------
    /** 触发 pipeline */
    analyze(projectId, config) {
      return request(
        "POST",
        "/projects/" + encodeURIComponent(projectId) + "/analyze",
        { config: config || {} }
      ).then((r) => r.data);
    },

    /** 查询项目状态（非流式） */
    getStatus(projectId) {
      return request(
        "GET",
        "/projects/" + encodeURIComponent(projectId) + "/status"
      ).then((r) => r.data);
    },

    // -------- 分析结果查询 --------
    /** 看板概览（KPI + 热力图 + 矩阵 + 卖点） */
    getOverview(projectId) {
      return request(
        "GET",
        "/projects/" + encodeURIComponent(projectId) + "/overview"
      ).then((r) => r.data);
    },

    /** 痛点列表 */
    listPainPoints(projectId, params) {
      return request(
        "GET",
        "/projects/" + encodeURIComponent(projectId) + "/pain-points",
        null,
        params || {}
      ).then((r) => r.data);
    },

    /** 痛点详情（含归因 + 评论 + 竞品对比） */
    getPainPointDetail(painPointId) {
      return request(
        "GET",
        "/pain-points/" + encodeURIComponent(painPointId)
      ).then((r) => r.data);
    },

    /** 评论列表 */
    listReviews(projectId, params) {
      return request(
        "GET",
        "/projects/" + encodeURIComponent(projectId) + "/reviews",
        null,
        params || {}
      ).then((r) => r.data);
    },

    /** 评论详情 */
    getReview(reviewId) {
      return request("GET", "/reviews/" + encodeURIComponent(reviewId)).then(
        (r) => r.data
      );
    },

    // -------- 报告导出 --------
    /** 获取 Markdown 报告内容 */
    getReport(projectId) {
      return request(
        "GET",
        "/projects/" + encodeURIComponent(projectId) + "/report",
        null,
        { format: "md" }
      ).then((r) => r.data);
    },

    /** 报告下载 URL（构造，浏览器直接跳转下载） */
    reportDownloadUrl(projectId, format) {
      return (
        buildUrl(
          "/projects/" + encodeURIComponent(projectId) + "/report/download",
          { format: format || "md" }
        ) + ""
      );
    },

    // -------- SSE 进度流 --------
    /**
     * 订阅项目进度 SSE 流。
     * @param {string} projectId
     * @param {object} handlers
     *   - onProgress(data)  阶段进度
     *   - onStageDone(data) 阶段完成
     *   - onError(data)     错误
     *   - onComplete(data)  pipeline 完成
     *   - onOpen()          连接建立
     *   - onClose()         连接关闭
     * @returns {function} cancel() 关闭连接
     */
    subscribeProgress(projectId, handlers) {
      const h = handlers || {};
      const url = buildUrl(
        "/projects/" + encodeURIComponent(projectId) + "/progress"
      );
      let es;
      try {
        es = new EventSource(url);
      } catch (e) {
        // 兜底：浏览器不支持 SSE，改用轮询
        return pollStatus(projectId, h);
      }

      es.onopen = function () {
        if (h.onOpen) h.onOpen();
      };

      es.addEventListener("progress", function (ev) {
        try {
          if (h.onProgress) h.onProgress(JSON.parse(ev.data));
        } catch (e) {
          console.warn("[SSE] progress parse error", e);
        }
      });

      es.addEventListener("stage_done", function (ev) {
        try {
          if (h.onStageDone) h.onStageDone(JSON.parse(ev.data));
        } catch (e) {
          console.warn("[SSE] stage_done parse error", e);
        }
      });

      es.addEventListener("error", function (ev) {
        // 优先按业务 error 事件处理
        if (ev && ev.data) {
          try {
            if (h.onError) h.onError(JSON.parse(ev.data));
            return;
          } catch (e) {
            /* fallthrough */
          }
        }
        // 连接级错误（断开/超时）— 浏览器会自动重连
        if (es.readyState === EventSource.CLOSED) {
          if (h.onClose) h.onClose();
        }
      });

      es.addEventListener("complete", function (ev) {
        try {
          if (h.onComplete) h.onComplete(JSON.parse(ev.data));
        } catch (e) {
          console.warn("[SSE] complete parse error", e);
        }
        es.close();
        if (h.onClose) h.onClose();
      });

      return function cancel() {
        try {
          es.close();
        } catch (e) {
          /* noop */
        }
      };
    },
  };

  // ===== 兜底轮询（SSE 不可用时） =====
  function pollStatus(projectId, h) {
    let stopped = false;
    let timer = null;
    let lastStage = null;
    const tick = async function () {
      if (stopped) return;
      try {
        const s = await api.getStatus(projectId);
        if (s && s.current_stage && s.current_stage !== lastStage) {
          lastStage = s.current_stage;
          if (h.onProgress)
            h.onProgress({
              stage: s.current_stage,
              progress: s.progress || 0,
              message: stageLabel(s.current_stage),
              timestamp: new Date().toISOString(),
            });
        } else if (s && s.progress != null) {
          if (h.onProgress)
            h.onProgress({
              stage: s.current_stage,
              progress: s.progress,
              message: stageLabel(s.current_stage),
              timestamp: new Date().toISOString(),
            });
        }
        if (s && s.status === "completed") {
          if (h.onComplete)
            h.onComplete({
              project_id: projectId,
              status: "completed",
              report_url: "/api/v1/projects/" + projectId + "/report",
            });
          return;
        }
        if (s && s.status === "failed") {
          if (h.onError)
            h.onError({
              stage: s.current_stage,
              message: s.error || "pipeline 失败",
              error_code: "PIPELINE_FAILED",
            });
          return;
        }
      } catch (e) {
        console.warn("[poll] status error", e);
      }
      if (!stopped) timer = setTimeout(tick, 2500);
    };
    timer = setTimeout(tick, 500);
    return function cancel() {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }

  function stageLabel(stage) {
    const map = {
      s1_ingest: "数据加载",
      s2_preprocess: "评论预处理",
      s3_cluster: "语义聚类",
      s4_label: "痛点标签生成",
      s5_attribute: "R1 根因归因",
      s6_suggest: "改进建议生成",
      s7_report: "报告整合",
    };
    return map[stage] || stage || "处理中";
  }

  // 暴露到全局
  global.VOC_API = api;
})(window);
