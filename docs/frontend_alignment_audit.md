# VOC Radar 前端内容与方案吻合度审查清单

> 审查人：许清楚（Xu，产品经理）　|　日期：2026-08-29　|　审查性质：**只读审查，未修改任何代码**
>
> **基线文档**
> 1. `docs/PRD.md`（v1.0，2026-07-29，初赛基线）
> 2. `复赛提交_VOC_Radar说明文档.md`（**v3，2026-08-29，权威最新版**）
>
> **审查范围**：`frontend/` 10 个文件 3512 行；因前端部分文案由后端推送/渲染，已向下追查 `backend/app/api/`、`app/pipeline/`、`app/core/config.py`、`seed_demo.py`。
>
> **严重级别定义**
> - **P0 致命**：评委对照文档与界面会直接发现矛盾，或前端行为与方案陈述冲突
> - **P1 重要**：文案过时误导，但不易被立刻发现
> - **P2 优化**：术语不统一、表述可更准确
>
> **统计**：P0 **10** 条 / P1 **8** 条 / P2 **10** 条，合计 **28** 条。

---

## 一、核心变更专项：归因主力模型 R1 → qwen3.7-max

> 方案 v3 第 2.1 / 2.4 / 7.5 节：根因归因主力已由 `deepseek-r1` 调整为 `qwen3.7-max`，R1 降级为**高难度痛点的可选补充通道**，由配置项 `ATTRIBUTION_MODEL` 控制（默认 `qwen3.7-max`）。

### 1.1 后端实现核对结论（先说好消息）

| 核对项 | 结论 |
|--------|------|
| `ATTRIBUTION_MODEL` 配置项存在且默认正确 | ✅ `backend/app/core/config.py:53`，默认 `qwen3.7-max` |
| S5 主力模型确实走配置项 | ✅ `s5_attribute.py:207` `primary = settings.ATTRIBUTION_MODEL` |
| R1 确实降级为补充通道 | ✅ `s5_attribute.py:208` `secondary = _other_model(primary)`，主力失败才降级 |
| 归因成功/降级统计口径已同步 | ✅ `s5_attribute.py:349` 按 `model_used == ATTRIBUTION_MODEL` 计数 |

**即：后端调度行为与方案陈述一致，模型切换这件事在工程上是真做成了。问题全部出在"说"的层面（文案 / 字段名 / 演示数据）。**

### 1.2 P0：前端可见的 R1 残留

| # | 文件:行号 | 现状文案/行为 | 方案应有表述 | 严重级别 | 建议改法 |
|---|----------|--------------|-------------|---------|---------|
| 1 | `frontend/js/components/detail-panel.js:237` | 下钻面板章节标题 `🔍 R1 根因归因` | `🔍 根因归因` | **P0** | 改为「AI 根因归因」；**建议直接动态化为 `根因归因（{{ attr.model_used }}）`**，让模型名自证，杜绝二次漂移 |
| 2 | `frontend/js/components/detail-panel.js:220` | 摘要条 `归因级别：R1 Top5`（高亮品牌色，视觉醒目） | `归因级别：Top5 深度归因` | **P0** | 去掉 R1 字样；若判定为补充通道产出，可显示「Top5 深度归因（补充通道）」 |
| 3 | `frontend/js/components/progress.js:26` | 7 阶段进度条常驻标签 `label: "R1 根因归因"` | `label: "根因归因"` | **P0** | 同文件 `:26` 的 `tip` 一并改（见 P2-18/19） |
| 4 | `frontend/index.html:46` | 空态首屏：`采集 → 预处理 → 语义聚类 → 痛点分级 → R1 根因归因 → 改进建议 → 报告导出` | `采集 → 预处理 → 语义聚类 → 痛点标签与分级 → 根因归因 → 改进建议 → 报告生成` | **P0** | 同时修正两处阶段名（见 P1-16） |

> ⚠️ **第 1 条是最致命的一处**：同一屏内，标题写着「R1 根因归因」，`detail-panel.js:296` 紧接着渲染 `模型：<span class="model-badge">qwen3.7-max</span>`。评委不需要看任何文档，只看这一屏就能发现自相矛盾。

### 1.3 P0：后端产生、但渲染在前端界面上的 R1 残留（**team-lead 的 grep 未覆盖**）

| # | 文件:行号 | 现状文案/行为 | 方案应有表述 | 严重级别 | 建议改法 |
|---|----------|--------------|-------------|---------|---------|
| 5 | `backend/app/pipeline/orchestrator.py:107` | `StageDef(name="s5_attribute", ..., description="R1 根因归因")` → SSE 推送 `message: "开始执行 R1 根因归因"`，**直接显示在前端进度条消息区**（`progress.js:_onProgress` → `#progressMessage`） | `description="根因归因"` | **P0** | 改为「根因归因」；可选增强为 `f"根因归因（{settings.ATTRIBUTION_MODEL}）"`，让进度条实时展示真实模型 |
| 6 | `backend/app/pipeline/stages/s7_report.py:62` | 报告模板 `\| R1 归因数（Top 5） \| {{ kpis.r1_attribution_count }} \|` → 渲染进报告正文，由前端「预览报告」弹层（`report-view.js`）展示，**截图 3 会拍到** | `\| 根因归因数（Top 5） \|` | **P0** | 改表头为「根因归因数（Top 5）」。该值语义为「进入 Top5 且有归因记录的痛点数」，非「R1 成功数」 |
| 7 | `backend/app/pipeline/stages/s7_report.py:150` | 报告页脚 `*…R1 归因结果为 AI 辅助参考，最终决策请结合卖家自身判断。*` | `*…AI 根因归因结果为辅助参考…*` | **P0** | 去掉 R1 字样。已实测：真实报告 `94cf2906…md:262` 就是这句 |
| 8 | `backend/seed_demo.py:410` | 内置 Demo 项目每条归因 `model_used="DeepSeek-R1"` → 前端 `detail-panel.js:296` 渲染为 `模型：DeepSeek-R1` 徽章 | `model_used="qwen3.7-max"`（或如实标注为历史产物） | **P0** | **这是评委按文档第 5 节「方式 A 免登录体验」打开 `http://127.0.0.1:8000` 会直接看到的内容**，也是截图 1–3 的数据源。改为 `qwen3.7-max`；或重跑 seed 让模型名由真实配置产出 |

> **第 8 条的杀伤力说明**：复赛说明文档 v3 把「内置 Seed Demo 免登录体验」列为评委体验路径（第 5 节方式 A），并把截图 1–3 列为材料。评委点开 Top1 痛点「续航明显短于宣传」下钻，看到「R1 根因归因」标题 + 「模型：DeepSeek-R1」徽章，而文档通篇说主力已切到 qwen3.7-max——**这是文档与产物最正面的一次冲突**。

### 1.4 P1：接口契约与字段名残留

| # | 文件:行号 | 现状文案/行为 | 方案应有表述 | 严重级别 | 建议改法 |
|---|----------|--------------|-------------|---------|---------|
| 9 | `frontend/js/api.js:382` | 轮询兜底映射 `s5_attribute: "R1 根因归因"` | `s5_attribute: "根因归因"` | **P1** | 仅在 SSE 不可用（浏览器不支持 EventSource）时走此路径，故非 P0，但必须改 |
| 10 | `frontend/js/app.js:207, 225` | 传给后端 `enable_r1: true` | 见下方「二、后端接口契约真实情况」 | **P1** | 行为上不会强制走 R1（详见第二节），但命名过时且会被持久化。建议删除，或改名 `enable_deep_attribution: true` |
| 11 | `frontend/js/app.js:115` + 后端 4 处 | KPI 取值 `kpis.r1_attribution_count`；后端 `projects.py:81/183`、`painpoints.py:164`、`s7_report.py:260` 均为 `r1_attribution_count` | `attribution_count` | **P1** | 后端改名为 `attribution_count` 并保留 `r1_attribution_count` 别名做兼容（前端/报告模板同步改） |

---

## 二、后端接口契约真实情况（**给架构师与工程师的专项结论**）

> team-lead 特别要求核查：`enable_r1` / `r1_attribution_count` 到底怎么回事。

### 2.1 `enable_r1`：后端已不再消费，是**死参数**，但**不会**造成"强制走 R1"

证据链：

1. `backend/app/api/analyze.py:29-32` — `AnalyzeRequest.config: dict[str, Any] | None`，**任意 dict 都接受、无任何字段校验**，因此 `enable_r1: true` 不会报错。
2. `analyze.py:83` — `asyncio.create_task(_run_pipeline_background(project_id, payload.config or {}))` → 传给 `orch.run(..., config=config)`。
3. `orchestrator.py:216-231` — `run()` 签名接收 `config`，但**函数体内 `config` 从头到尾未被读取**；阶段执行只有 `stage_def.fn(project_id)`（`orchestrator.py:279`），配置不向下传递。
4. `orchestrator.py:227` 的 docstring 仍写「config: pipeline 配置（如 k_range / top_n / enable_r1）」——**注释已过期**。

**结论：**
- ✅ **不会导致「R1 被强制启用」**。实际归因模型由 `settings.ATTRIBUTION_MODEL`（默认 `qwen3.7-max`）唯一决定。前端行为与方案陈述**不冲突**。
- ⚠️ 但它是**僵尸契约**：`enable_r1` 会被写进 `project.config`（`projects.py:100`）并由 `GET /projects/{id}` 的 `ProjectVO.config` 原样返回。评委若查看 API 响应，会看到 `{"enable_r1": true, "enable_vision": false, "k_range": [8,15], "top_n": 5}`，与文档「R1 为可选补充通道」的措辞不符。
- ⚠️ 同类死参数还有：`k_range: [8,15]`（后端实际用 `settings.CLUSTER_K_MIN/MAX = 8/15`）、`top_n: 5`（实际用 `settings.TOP_N_FOR_R1 = 5`）、`enable_vision: false`（S4 由 `has_image` 触发）。**前端暗示这些参数可调，实际完全不可调**。

**建议（给架构师）**：删掉 `enable_r1` 或重命名为 `enable_deep_attribution`；同时决定 `config` 要么真正生效（透传到各 stage），要么从前端请求体中移除——**不要保留"传了但没用"的参数**，这本身也是一种不诚实。

### 2.2 `r1_attribution_count`：字段名是残留，**且语义与名字双重不符**

三处实现的真实语义：

| 位置 | 计算方式 | 真实语义 |
|------|---------|---------|
| `painpoints.py:157` | `sum(1 for p in pain_points if p.is_top5)` | **进入 Top5 的痛点个数**（与归因是否成功无关） |
| `projects.py:172-176` | `count(PainPoint).where(is_top5 == True)` | 同上 |
| `s7_report.py:253` | `len(top5_with_attr)`（join attributions） | **进入 Top5 且有归因记录的痛点数** |

**结论：**
- 字段名 `r1_*` 是模型切换前的残留，**当前默认配置下这些归因 100% 由 `qwen3.7-max` 产出，与 R1 无关**。
- 而且它统计的是「Top5 标记数」，不是「归因成功数」。即使 5 条全部降级/失败，KPI 仍显示 5（`s5_attribute.py:354-369` 异常时 `is_top5` 依然为 True）。
- 前端 `app.js:114-116` 的 KPI **label 已是中性的「根因归因」**（无 R1 字样，界面上不暴露矛盾），但 **sub 文案「Top5 痛点归因完成」过度承诺**。

**建议（给工程师）**：后端统一改名为 `attribution_count`（保留 `r1_attribution_count` 做别名兼容一个版本），前端与 Jinja2 模板同步；同时把 sub 文案改为「Top5 已进入深度归因」，或让后端返回真实的 `attribution_success_count`（`primary_success`）与 `fallback_count` 两个字段分别展示。

---

## 三、其他吻合性维度（主动发现，team-lead 未列出）

### 3.1 P0：前端承诺"输入品类/ASIN"，但实际输入完全不参与分析

| # | 文件:行号 | 现状文案/行为 | 方案应有表述 | 严重级别 | 建议改法 |
|---|----------|--------------|-------------|---------|---------|
| 12 | `frontend/index.html:28, 45, 47` + `backend/app/pipeline/stages/s1_ingest.py:105, 111-113, 242` | 前端 placeholder「输入品类关键词或 ASIN（逗号分隔）」、空态「输入品类或竞品 ASIN，开始评论洞察分析」、示例 `bluetooth earbuds` / `B0xxx, B0yyy`。**但 S1 用 `DataLoader().load_dir(pattern="*")` 加载 `backend/data/raw/` 下全部文件，不做任何 ASIN / 品类过滤**——`s1_ingest.py:105` 读出的 `existing_asins` 从未用于过滤（`:242` 是把数据里发现的 ASIN **写回**项目，是输出不是输入） | 方案 1️⃣ 核心功能 1「按 ASIN / 关键词抓取竞品评论」；2️⃣ S1「输入品类关键词 / 竞品 ASIN → 采集评论」 | **P0** | **最低成本修法（推荐）**：改前端文案，如实标注数据源——placeholder 改为「当前原型分析内置数据集：Cell Phones and Accessories（输入仅作项目命名）」，空态补一行灰字说明。**若时间允许**：给 `DataLoader.load_dir()` 加 `asins` 过滤参数，让输入真正生效 |

**危害**：评委输入 `bluetooth earbuds` → 报告第一章写着「品类: bluetooth earbuds」，但痛点全是「充电不稳定 / 涂层易脱落 / 手机壳」——项目名与内容品类明显对不上，**一眼看穿**。这比任何文案残留都容易被发现。

> 补充证据：`backend/data/raw/` 下只有 `amazon_Cell_Phones_and_Accessories_reviews.jsonl` 一个数据文件。

### 3.2 P0：PRD.md 本身通篇 R1 表述，但它被 v3 列为交付物②

| # | 文件:行号 | 现状文案/行为 | 方案应有表述 | 严重级别 | 建议改法 |
|---|----------|--------------|-------------|---------|---------|
| 13 | `docs/PRD.md` 全文（`:5, 23, 32, 45, 67, 76, 81, 109, 151, 211, 222, 242, 255`） | v1.0 初赛基线，13 处仍写「R1 根因归因 / DeepSeek-R1 / R1 归因是辅助参考 / P0-5 对 Top5 调用 DeepSeek-R1 / KPI 卡片『R1 归因 5』/ 下钻面板『🔍 R1 根因归因』」 | 以复赛说明文档 v3 为准 | **P0** | 复赛说明文档 v3 第 0 节 ② 明确把 `docs/PRD.md` 列为交付物之一，评委**会打开**。建议：① 发布 PRD v1.1 同步模型调度表述；② 若来不及，至少在 PRD 头部加醒目声明「v1.0 为初赛基线；模型调度策略以《复赛提交_VOC_Radar说明文档》v3 第 2.1 / 2.4 节为准」 |

### 3.3 P1：指标定义与数据诚实性

| # | 文件:行号 | 现状文案/行为 | 方案应有表述 | 严重级别 | 建议改法 |
|---|----------|--------------|-------------|---------|---------|
| 14 | `frontend/js/components/matrix.js:106, 141` + `backend/app/api/painpoints.py:202, 358-368` | X 轴「解决难度 → 难」是**由象限反推的常量**：`_infer_difficulty()` 把 `quick_win/filler → 0.3`、`strategic/thankless → 0.7`、无建议 → `0.5`。而 quadrant 本身是 S6 由 LLM 产出 → **循环论证**，难度不是独立评估维度 | 方案 1️⃣ 核心功能 5「改进优先级矩阵（影响面 × 解决难度）」——暗示两个独立维度 | **P1** | 二选一：① 让 S6 的 LLM 直接输出 `difficulty_score`（真正的独立评估）；② 前端 X 轴改名「改进投入（由象限推断）」并加脚注说明。且 `matrix.js:69` 的 `impactThreshold=0.15` 中线与 LLM 判定的高低影响可能不一致，**会出现"点画在高影响区却标注 Filler 低影响"** |
| 15 | 前端无对应实现 vs 复赛说明文档 v3 第 5 节「方式 A」 | 文档承诺「启动服务后访问 `http://127.0.0.1:8000`，系统已内置 Seed Demo 项目……**可直接**：点击看板查看热力图 / 优先级矩阵、点击 Top1 痛点下钻、打开报告预览」。**但 `app.js:init()` 不加载任何项目，前端也没有任何项目列表 / 历史项目入口；`backend/app/main.py` 启动时也不自动 seed** | 评委打开页面能看到 Demo 看板 | **P1** | 评委实际打开只会看到空态，必须自己触发一次完整 pipeline（真实模型调用、数分钟、消耗个人 Key）才能看到任何内容。建议：前端加「载入内置 Demo 数据」按钮（调 `GET /projects` 取最近完成的项目 → `loadOverview`），或改文档措辞为「需先手动触发一次分析」 |
| 16 | `frontend/index.html:46` | 空态 7 阶段命名与方案 2.2 不一致：第 4 段写「痛点分级」（方案 S4 是「标签」+ 分级判断）、第 7 段写「报告导出」（方案 S7 是「报告」） | S1 采集 / S2 预处理 / S3 聚类 / S4 标签 / S5 归因 / S6 建议 / S7 报告 | **P1** | 统一为「采集 → 预处理 → 语义聚类 → 痛点标签与分级 → 根因归因 → 改进建议 → 报告生成」 |
| 17 | `frontend/js/components/detail-panel.js:310` | 标题「代表性评论（Top N，按点赞数排序）」，但后端 `painpoints.py:301` 是 `order_by(is_representative.desc(), helpful_votes.desc()).limit(10)` —— **先按"是否代表性"排，再按点赞数**；且 N=10 而非 PRD 4.2 写的 Top 5 | 「代表性评论（Top N，代表性优先）」 | **P1** | 改排序描述；Top N 已动态显示属诚实做法，保留 |
| 18 | `frontend/js/app.js:114-116` | KPI 第 4 卡：label「根因归因」+ sub「Top5 痛点归因完成」+ 值 `r1_attribution_count`（= `is_top5` 计数，恒为 5） | 「Top5 已进入深度归因」 | **P1** | 见 2.2：值恒等于 5，即使 5 条全部降级失败也显示 5，属过度承诺 |

### 3.4 P2：术语统一、表述精度、代码注释

| # | 文件:行号 | 现状文案/行为 | 方案应有表述 | 严重级别 | 建议改法 |
|---|----------|--------------|-------------|---------|---------|
| 19 | `frontend/js/components/progress.js:25, 27` | tip 中模型名写 `qwen-max`（s4 / s6） | `qwen3.7-max` | **P2** | 精确模型名。注：tip 当前是**死代码**（`_renderSkeleton` 只渲染 `label`），故非 P1，但 `STAGES` 已导出，建议一并修正 |
| 20 | `frontend/js/components/progress.js:26` | tip `DeepSeek-R1 对 Top 5 痛点深度推理` | `qwen3.7-max（默认）对 Top 5 痛点深度归因，R1 为可选补充通道` | **P2** | 同上（死代码） |
| 21 | `frontend/js/app.js:109` | KPI「痛点数」 | 「痛点簇数」 | **P2** | 方案 2.2 S3、报告模板 `s7_report.py:61`「痛点簇数」、PRD US-2「8-15 个痛点簇」均用「簇」，前端单独用「痛点数」，术语不统一 |
| 22 | `frontend/js/components/heatmap.js:206` | tooltip 标题 `⭐Top5 归因` | `⭐Top5 深度归因` | **P2** | 该 flag 实为 `is_top5`（进入归因队列），非"已归因成功"，措辞可更精确 |
| 23 | `frontend/js/app.js:205, 223` | `k_range: [8,15]` / `top_n: 5` 随请求发送 | — | **P2** | 死参数（后端用 settings），与 #10 的 `enable_r1` / `enable_vision` 一并处理 |
| 24 | `frontend/js/components/detail-panel.js:348-355` | 「查看买家秀图片」只弹原图灯箱，未展示 `qwen3-vl-plus` 识别的缺陷标注 | PRD 4.3 交互表：「显示 qwen3-vl-plus 识别的缺陷标注」；方案 2.2 S4「带图评论触发 qwen3-vl-plus 图片缺陷识别」 | **P2** | 本次真实数据带图评论为 0 条（文档已如实说明），但前端入口存在却无标注能力。建议：无标注时明确提示「该评论暂无 AI 缺陷识别结果」，避免评委追问 |
| 25 | `backend/app/pipeline/stages/s5_attribute.py:1, 7, 11, 12, 48, 180, 187, 331, 430` | 模块 docstring「Stage 5: R1 根因归因」「对每个 Top 5 痛点调用 DeepSeek-R1」「写入 attributions 表（model_used='deepseek-r1'）」「R1 失败时降级用 qwen3.7-max」、命令行 `description="s5_attribute: R1 根因归因"` | 与代码实际行为（主力 `ATTRIBUTION_MODEL`）一致的表述 | **P2** | **代码行为正确，仅注释过时**。这些注释与已修正的实现方向相反，会误导后续维护者，建议同步 |
| 26 | `backend/app/pipeline/prompts/labels.py:25`、`prompts/suggestions.py:9, 57` | Prompt 内「判断该痛点是否适合深度推理（R1 根因归因）」「基于 R1 归因结果」「【R1 已建议的改进措施（供参考整合…）】」 | 「深度归因」 | **P2** | 内部 prompt，不影响界面，但会随 prompt 进日志/截图。建议改为模型无关表述，与"不绑定单一模型"的方案主张一致 |
| 27 | `backend/app/core/config.py:81-85` | `TOP_N_FOR_R1` / `TOP_N_CANDIDATES` / `R1_MAX_RETRIES` 命名残留 | `TOP_N_FOR_ATTRIBUTION` 等 | **P2** | 不影响界面，建议重命名（需同步 `s5_attribute.py:98, 105` 与 `model_router.py:206, 218`） |
| 28 | `backend/app/pipeline/stages/s7_report.py:7` | docstring「概览（竞品数/评论数/痛点数/R1归因数）」 | 「根因归因数」 | **P2** | 与 #6 同一处认知，一并改 |

---

## 四、已核对**无问题**的项（供 team-lead 排除疑虑）

| 核对项 | 结论 |
|--------|------|
| 影响面口径（占差评总数） | ✅ 一致。`s4_label.py:311` `impact_ratio = review_count / total_negative`；前端 `heatmap.js:174` 轴标题「影响面占比（占差评总数）」；与文档 7.3「充电不稳定 18.1% = 24/133 差评」吻合。（注：PRD 4.2 示例写的「28% (345/1245 条)」是占总评论数，与实现不符——PRD 示例属初赛示意，已并入 #13 处理） |
| 7 阶段顺序 | ✅ 前端 `progress.js:21-29` 与 `api.js:377-385` 的 7 个 key 与方案 2.2 完全一致 |
| 报告渲染技术栈 | ✅ `progress.js:28` tip 写「Jinja2 渲染 Markdown 报告」，后端 `s7_report.py:25` 确为 `from jinja2 import Template`。描述准确 |
| 竞品对比 / 共性弱点 | ✅ `detail-panel.js:407-416` 与 PRD 4.2、方案 1️⃣ 核心功能 4 一致；共性判定阈值后端 `config.py:87-97`（占比 0.15 + 至少 2 个竞品） |
| 报告导出格式 | ✅ 只导出 Markdown，与方案 P0 范围一致（PDF 为 P1，未实现也未承诺） |
| 证据引用可点击回溯 | ✅ `detail-panel.js:261-266` 生成 `[data-review-id]` 链接，`:451-468` 实现滚动+高亮+展开，符合方案「证据驱动」主张 |
| KPI 卡片结构 | ✅ 竞品数 / 评论数 / 痛点数 / 根因归因，与 PRD 4.1 布局一致，无缺失项 |
| 四象限图例 | ✅ `index.html:82-85` 与 `matrix.js:42-54` 命名一致 |

---

## 五、给工程师寇豆码的修改优先级建议

**第一批（P0，10 条，必须在截图/视频重录前完成）**
1. 前端 4 处：`detail-panel.js:220, 237`、`progress.js:26`、`index.html:46`
2. 后端 4 处：`orchestrator.py:107`、`s7_report.py:62, 150`、`seed_demo.py:410`
3. 数据/能力 1 处：`s1_ingest.py` 输入过滤（**或**改前端文案为如实标注数据源，二选一）
4. 文档 1 处：`docs/PRD.md` 加版本声明或升 v1.1

**第二批（P1，8 条）**：`#9 api.js:382`、`#10 enable_r1`、`#11 r1_attribution_count 改名`、`#14 难度维度`、`#15 Demo 载入入口`、`#16 阶段命名`、`#17 代表性评论排序描述`、`#18 KPI sub 文案`

**第三批（P2，10 条）**：术语与注释清理，可与第一批同文件一并处理，边际成本低

> ⚠️ **修改后必须重新验证**：改完 `seed_demo.py` 需重跑 seed 并**重新生成截图 1–3**；改完 `s7_report.py` 模板需重跑该项目的报告（旧报告文件 `94cf2906….md` 里的「R1 归因数」不会自动更新，若这份报告要放进材料需重新生成）。

---

*本清单基于 2026-08-29 代码快照静态审查得出，未启动或修改任何服务。所有行号对应当前工作区文件。*
