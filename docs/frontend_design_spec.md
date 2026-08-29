# VOC Radar 前端视觉重做 — 设计规格（工业精密仪表风 · 深色）

> 面向工程师的可执行规格。**只改视觉，一个字的业务文案都不要动**（"根因归因""qwen3.7-max""Top5"等原样保留）。
> 前置：`.impeccable.md`（本文件不复述其已固化内容）。基线：`frontend/css/style.css`(854) / `index.html` / `js/components/*.js`。

---

## 0. 三个核心决策（其余都是它的展开）

| 决策 | 内容 | 理由 |
|---|---|---|
| **强调色 = 磷光青 Phosphor Cyan-Green** | `oklch(0.82 0.145 172)` ≈ `#2fe0bd` | ① 色相 172 在青-绿之间，**不是蓝色**，规避"蓝+深色"AI 标配；② 雷达 CRT 磷光屏 / 示波器 / 精密面板指示灯的原生色，直接命中"探测仪器"叙事；③ 与严重度色阶（色相 24–95）相距 80°+，语义不串台 |
| **零 webfont** | 不引任何 CDN 字体，个性来自"非默认但系统自带"的字体 | 中国大陆 Google Fonts 不可达 + 路演断网风险。核心视觉不依赖网络才是唯一稳妥解。Windows 自带 **Bahnschrift**、macOS 自带 **DIN Alternate** —— 都是 DIN 工业体，都不在默认字体栈里 |
| **去卡片 = 线条 + 留白 + 排版层级** | 区块间 1px 顶边线 + 大留白；区块内 1px 分隔线 | 卡片是 AI 生成界面的第一特征。仪器面板靠**刻线**分栏，不靠浮起的方块 |

**⚠️ 去卡片化的代价与防线**：只靠留白，投影 5 米外会糊成一片。硬性要求 —— **每个一级区块必须有至少一条结构性线条**（顶边线或左侧竖线），禁止纯留白分区。

---

## 1. 设计 Token（直接照抄）

### 1.1 色彩

先写 hex 兜底，再用 `@supports` 覆盖为 oklch（老浏览器 Chrome<111 也能看）。

```css
:root {
  /* 底层：近中性石墨灰，色度 ≤0.011，几乎无蓝紫偏色，让数据色更跳 */
  --bg-base:#101215; --bg-inset:#0b0d0f;                 /* 页面底 / 凹槽(图表·输入框) */
  --bg-elev-1:#171a1e; --bg-elev-2:#1e2226; --bg-elev-3:#262b30;
  /* 文本（无纯白） */
  --text-primary:#eceef1; --text-secondary:#b6bbc2; --text-muted:#82888f; --text-faint:#5c6268;
  /* 强调色：磷光青 */
  --accent:#2fe0bd; --accent-dim:#17a288;
  --accent-wash:rgba(47,224,189,0.12); --accent-line:rgba(47,224,189,0.38);
  /* 严重度色阶（红→橙→黄＝问题严重度，不是涨跌）。改用数字阶，便于阈值映射 */
  --sev-1:#ffe9a8; --sev-2:#ffcf5c; --sev-3:#ff9f3d; --sev-4:#f4703a; --sev-5:#e0353c;
  /* 四象限：色相 + 明度 + 形状 三重编码 */
  --quad-quick:#2fe0bd;      /* 与 accent 同色＝有意复用，"该动手的地方" */
  --quad-strategic:#b07cf0;  /* 紫：高价值·需投入 */
  --quad-filler:#9aa4b2;     /* 中性灰：可做可不做 */
  --quad-thankless:#5b6472;  /* 暗灰：视觉主动退场 */
  /* 状态色只有 3 个：完成＝accent，不再单独给绿 */
  --ok:var(--accent); --warn:var(--sev-3); --error:var(--sev-5);
  /* 线条由文本色派生，任何底上都协调 */
  --hairline: color-mix(in oklab, var(--text-primary) 7%,  transparent);
  --line:     color-mix(in oklab, var(--text-primary) 13%, transparent);
  --line-str: color-mix(in oklab, var(--text-primary) 26%, transparent);
  --grid-line:color-mix(in oklab, var(--text-primary) 2.5%,transparent);
}
@supports (color: oklch(0.5 0.1 180)) { :root {
  --bg-base:oklch(0.155 0.008 265); --bg-inset:oklch(0.125 0.007 265);
  --bg-elev-1:oklch(0.195 0.009 265); --bg-elev-2:oklch(0.235 0.010 265); --bg-elev-3:oklch(0.285 0.011 265);
  --text-primary:oklch(0.930 0.004 265); --text-secondary:oklch(0.750 0.008 265);
  --text-muted:oklch(0.580 0.010 265);   --text-faint:oklch(0.450 0.010 265);
  --accent:oklch(0.820 0.145 172); --accent-dim:oklch(0.620 0.110 172);
  --sev-1:oklch(0.920 0.090 95); --sev-2:oklch(0.860 0.140 82); --sev-3:oklch(0.780 0.160 62);
  --sev-4:oklch(0.680 0.190 44); --sev-5:oklch(0.580 0.210 24);
  --quad-strategic:oklch(0.680 0.150 305); --quad-filler:oklch(0.700 0.012 265); --quad-thankless:oklch(0.500 0.014 265);
} }
```

### 1.2 字体（三条链，全部零网络依赖）

```css
:root {
  /* 展示：DIN 工业体（Win/macOS 各自自带、都不在默认栈里） */
  --font-display: "Bahnschrift","Bahnschrift SemiCondensed","DIN Alternate","DIN Condensed",
                  "Oswald","Haettenschweiler","Arial Narrow","PingFang SC","Microsoft YaHei",sans-serif;
  /* 正文：优先比雅黑/苹方更精致的国产系统字体，逐级回落 */
  --font-body: "HarmonyOS Sans SC","MiSans","Source Han Sans SC","Noto Sans CJK SC",
               "PingFang SC","Microsoft YaHei","Segoe UI",system-ui,sans-serif;
  /* 等宽数字：所有数字/百分比/ASIN/模型名/坐标轴 */
  --font-mono: "JetBrains Mono","Cascadia Mono","SF Mono","Cascadia Code","Consolas","Menlo",monospace;
}
body { font-family:var(--font-body); font-weight:400; font-synthesis:none;
       -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility; }
```

| 排字规则 | 值 | 说明 |
|---|---|---|
| 中文标题字重 | **≤600**，禁 700+ | 深底浅字，笔画密，粗体会糊 |
| 中文标题字距 | `letter-spacing:.02em` | 给密集笔画呼吸 |
| 西文小标签 | `text-transform:uppercase; letter-spacing:.16em; font-family:var(--font-mono)` | **仪器面板的灵魂**，用于 KPI 标签 / 表头 / 区块序号 |
| 数字 | `font-family:var(--font-mono); font-variant-numeric:tabular-nums` | 数字等宽对齐＝读数仪表感 |
| 正文行高 | 1.6 | 投影可读性 |
| `font-synthesis:none` | 全局 | 禁止中文伪粗体（深底上会糊成一团） |

### 1.3 间距 / 圆角 / 阴影

```css
:root {
  /* 4 基准非线性阶梯（近黄金比），内紧外松制造节奏 */
  --s-1:4px; --s-2:8px; --s-3:12px; --s-4:20px; --s-5:32px; --s-6:52px; --s-7:84px;
  /* 小圆角。禁止 10px+（唯一例外：进度条 Pill） */
  --r-hair:2px; --r-sm:3px; --r-md:4px; --r-lg:6px;
  /* 常态几乎不用外阴影，用"内高光 + 1px 描边"表达凸起 */
  --raised: 0 0 0 1px var(--hairline), inset 0 1px 0 color-mix(in oklab, var(--text-primary) 4%, transparent);
  /* 仅浮层（抽屉/弹层/Toast/灯箱）用强阴影拉开层次 */
  --overlay-shadow: 0 0 0 1px var(--line-str), 0 24px 64px -12px rgb(0 0 0 / 0.72);
}
```
**删除**：`--shadow-sm/md/lg`、`--radius-sm/md/lg`、`--gap-xs~xl`（均匀的 6/10/16/24/32 正是"没有节奏"的元凶）。

### 1.4 流体尺寸（clamp，投影取上限）

```css
:root {
  --fs-micro:clamp(9px,0.62vw + 7px,11px);   --fs-label:clamp(10px,0.70vw + 8px,12px);
  --fs-body:clamp(13px,0.50vw + 12px,15px);  --fs-lead:clamp(15px,0.80vw + 13px,18px);
  --fs-h3:clamp(15px,1.00vw + 12px,19px);    --fs-h2:clamp(18px,1.60vw + 14px,26px);
  --fs-h1:clamp(22px,2.40vw + 16px,34px);    --fs-metric:clamp(28px,3.20vw + 18px,46px);
  --w-page:min(1320px, 100% - 2 * clamp(20px, 4vw, 56px));
}
```

### 1.5 缓动（指数缓动）

```css
:root {
  --ease-out-quart:cubic-bezier(0.25,1,0.50,1); --ease-out-expo:cubic-bezier(0.16,1,0.30,1);
  --dur-fast:140ms; --dur-mid:260ms; --dur-slow:480ms;
}
@media (prefers-reduced-motion: reduce) { *,*::before,*::after {
  animation-duration:.01ms !important; transition-duration:.01ms !important; } }
```
分配：抽屉/弹层 `480ms var(--ease-out-expo)`；进度条 `width` `480ms var(--ease-out-quart)`；hover `140ms var(--ease-out-quart)`。**删除 `progressShine` 无限流光**（廉价感来源），改静态渐变 + 末端 1px 亮线。

---

## 2. style.css 改造清单

按文件从上到下分块。**块 A 必须先落地，其余依赖它。**

### 块 A — 变量层（L7–69 整块替换）
写入 §1 全部 token。删除 `--brand`/`--brand-soft`/`--info`/`--success`/`--warning`/旧 `--sev-*`/`--shadow-*`/`--radius-*`/`--gap-*`/旧 `--font-sans`。
**校验**：`grep -c "var(--brand" style.css` == 0。

### 块 B — 基础层 + 网格底纹（L71–95）
- `body`：`background-color:var(--bg-base)`；**删 `radial-gradient`**，改 48px 细网格：
  ```css
  background-image:
    repeating-linear-gradient(to right,  var(--grid-line) 0 1px, transparent 1px 48px),
    repeating-linear-gradient(to bottom, var(--grid-line) 0 1px, transparent 1px 48px);
  background-attachment: fixed;
  ```
- `h1,h2,h3` → `font-family:var(--font-display)` + 字重 600 + `letter-spacing:.02em`。
- `code`：字色→`--sev-2`，背景→`--bg-inset`，圆角→`--r-hair`，字号 `.92em`。
- 新增 `:focus-visible{ outline:1px solid var(--accent); outline-offset:2px; }`（替换蓝晕 box-shadow）。

### 块 C — 顶栏（L97–179）
- `.topbar`：`backdrop-filter` 降为 **8px**（全站唯一保留的毛玻璃，顶栏是它唯一合理用法）；背景 `color-mix(in oklab, var(--bg-base) 88%, transparent)`；下边框 `--hairline`；padding `--s-3 var(--s-5)`。
- `.brand-logo`：删 `font-size:30px`，改 26×26 的 SVG 容器，`color:var(--accent)`。
- `.brand-text h1`：`--fs-lead` + display 字体 + `letter-spacing:.04em`。`.brand-sub`：`--font-mono` + `--fs-micro` + `uppercase` + `letter-spacing:.14em` + `--text-faint`。
- `.search-box input`：背景 `--bg-inset`，边框 `--line`，圆角 `--r-sm`；focus → 边框 `--accent-line` + `box-shadow:0 0 0 2px var(--accent-wash)`。
- `.btn`：圆角 `--r-sm`，`transition:140ms var(--ease-out-quart)`。
  - `.btn-primary`：**删蓝色渐变** → `background:var(--accent); color:var(--bg-base); font-weight:600`；hover `translateY(-1px)` + `box-shadow:0 4px 16px -4px var(--accent-line)`。深色字压亮青底，对比度最高也最不像 AI。
  - `.btn-ghost`：背景透明 + 边框 `--line` + 字色 `--text-secondary`；hover 边框 `--accent-line`。

### 块 D — 页面骨架 + 空态（L181–201）
- `.main`：`max-width:var(--w-page); margin-inline:auto; padding-block:var(--s-6) var(--s-7)`。
- `.empty-state`：**删 `.empty-illustration` 的 `font-size:64px`**，改 CSS 十字准星（§3.1）；空态改**左对齐** `max-width:62ch`（居中 + 大图标 = AI 空态模板）。

### 块 E — 进度区（L203–261）
- `.progress-section`：**去卡片**（删背景/边框/圆角），改 `border-top:1px solid var(--line); padding-block:var(--s-5)`。
- `.progress-bar-wrap`：高 10px→**6px**（细刻度更像仪表）；背景 `--bg-inset` + `inset 0 0 0 1px var(--hairline)`；圆角保留 999px。
- `.progress-bar-fill`：渐变→`linear-gradient(90deg,var(--accent-dim),var(--accent))`；**删 `progressShine`**；`transition:width 480ms var(--ease-out-quart)`；`::after` 加末端 1px 亮线。
- `.stage-dot`：8px 圆点 → **6px 方块，`border-radius:1px`**（仪器指示灯）。`.active`→`--accent` + `0 0 0 3px var(--accent-wash)`；`.done`→`--accent-dim`；错误→`--sev-5`。
- `.progress-meta`/`.progress-message`：`--font-mono` + `--fs-label` + `tabular-nums`。

### 块 F — KPI（L263–306）★去卡片重点
```css
.kpi-row{ display:grid; grid-template-columns:repeat(4,1fr);
  border-top:1px solid var(--line); border-bottom:1px solid var(--line); }
.kpi-card{ padding:var(--s-4); border-left:1px solid var(--hairline); }
.kpi-card:first-child{ border-left:none; padding-left:0; }
.kpi-label{ display:flex; align-items:center; gap:var(--s-2);
  font-family:var(--font-mono); font-size:var(--fs-micro);
  text-transform:uppercase; letter-spacing:.16em; color:var(--text-muted); }
.kpi-label::before{ content:""; width:5px; height:5px; background:var(--kpi-accent, var(--text-faint)); }
.kpi-value{ font-family:var(--font-mono); font-size:var(--fs-metric); font-variant-numeric:tabular-nums;
  letter-spacing:-.02em; color:var(--text-primary); line-height:1.05; margin-top:var(--s-2); }
.kpi-sub{ font-size:var(--fs-label); color:var(--text-faint); margin-top:var(--s-2); }
```
**删除**：`.kpi-card` 的背景/边框/圆角/overflow；`.kpi-card::before` 的 3px 强调竖条；`.kpi-value` 的 `color:var(--kpi-accent)`（彩色大数字＝廉价仪表盘特征，统一 `--text-primary`，颜色只由标签前 5px 方点承担）。

### 块 G — 区块（L308–360）★去卡片重点
- **删 `.panel` 的背景/边框/圆角/overflow**；新增区块头（HTML 同步，见 §3.2）：
```css
.section-head{ display:grid; grid-template-columns:auto 1fr auto; align-items:baseline;
  gap:var(--s-3); padding-top:var(--s-4); border-top:1px solid var(--line); }
.section-index{ font-family:var(--font-mono); font-size:var(--fs-micro); letter-spacing:.14em; color:var(--accent); }
.section-title{ font-family:var(--font-display); font-size:var(--fs-h3); font-weight:600; letter-spacing:.02em; }
.section-tip{ font-size:var(--fs-label); color:var(--text-muted); }
```
- `.panel-body`→`.section-body`：`padding-block:var(--s-5)`，无左右 padding。
- `.chart-wrap` 加 inset 屏效（图表＝仪表屏，需要凹陷感）：
  `background:var(--bg-inset); border:1px solid var(--hairline); border-radius:var(--r-sm); padding:var(--s-3); box-shadow:inset 0 1px 0 color-mix(in oklab,var(--text-primary) 4%,transparent);`
- 图表高度改流体：heatmap `clamp(360px,42vh,520px)`、matrix `clamp(340px,38vh,460px)`（投影自动撑开）。
- `.matrix-legend`：`justify-content:flex-start`（不要居中）+ `--font-mono` + `--fs-micro` + `letter-spacing:.08em`。
- `.dot`：10px 圆 → **8px 方块，圆角 1px**；`.dot-thankless` 加 `border:1px solid var(--quad-thankless); background:transparent`（空心＝退场，呼应矩阵空心点）。

### 块 H — 卖点清单（L362–439）★去卡片重点
```css
.suggestion-item{ position:relative; padding:var(--s-4) 0 var(--s-4) var(--s-6);
  border-top:1px solid var(--hairline); }
.suggestion-item:last-child{ border-bottom:1px solid var(--hairline); }
.suggestion-item::before{ content:counter(suggestion, decimal-leading-zero);
  position:absolute; left:0; top:var(--s-4); font-family:var(--font-mono);
  font-size:var(--fs-label); color:var(--accent); letter-spacing:.06em; }
.suggestion-item::after{ content:""; position:absolute; left:var(--s-4); top:0; bottom:0;
  width:1px; background:var(--hairline); transition:background 140ms var(--ease-out-quart); }
.suggestion-item:hover::after{ background:var(--accent); }
```
其余：删除卡片背景/边框/圆角与 `translateY(-1px)`（弹性位移是通用 UI 套件味）。
`.tag` → 圆角 `--r-hair` + `--font-mono` + `--fs-micro` + `letter-spacing:.06em`，改**描边式**（`color:var(--sev-5); border:1px solid color-mix(in oklab,var(--sev-5) 40%,transparent)`），priority high/medium/low 分别用 `--sev-5`/`--sev-3`/`--text-muted`；field 标签统一 `--text-secondary` + `--line` 边框（去掉紫/绿/橙四色）。
`.suggestion-rationale`：**删 `font-style:italic`**（中文伪斜体难看），改 `--text-faint` + 左 1px 竖线 + `padding-left:var(--s-3)`。

### 块 I — 详情抽屉（L441–625）
- `.detail-drawer`：背景 `--bg-elev-1`，左边框 `--line-str`，`box-shadow:var(--overlay-shadow)`，`animation:slideIn 480ms var(--ease-out-expo) forwards`，宽 `min(760px,94vw)`。
- `.detail-header`：删 `rgba(255,255,255,.02)` 底；下边框 `--line`；标题 `--fs-h2` + display 字体。
- `.detail-body`：`gap:var(--s-6)`；`padding:var(--s-5)`。
- **`.detail-summary` 从卡片改读数带**：删背景/圆角 → `display:grid; grid-template-columns:repeat(auto-fit,minmax(96px,1fr)); gap:var(--s-4)` + 上 `--line` / 下 `--hairline` 双线包夹（左侧 `border-left-color` 由 JS 注入的逻辑保留）。
- `.detail-section h3`：**双行标签**（中文 + 等宽英文小字，见 §3.1）。
- **`.attribution-box` 去卡片** → `padding-left:var(--s-4); border-left:2px solid var(--line)` 的缩进引用块。
- `.root-cause`：左边框 2px `--sev-5`，背景 `color-mix(in oklab,var(--sev-5) 7%,transparent)`，圆角 `--r-hair`。
- `.evidence-item`：分隔线 `dashed`→`solid` + `--hairline`；引号色 `--sev-3`→`--text-faint`（引号不该抢戏）。
- `.evidence-link`/`.review-actions a`：`color:var(--accent)`，下划线 `1px solid var(--accent-line)`。
- `.measure-item::before`：`content:"→"` → CSS counter 等宽序号，`color:var(--accent)`。
- `.model-badge`：背景透明 + 边框 `--line` + `--font-mono` + `--fs-micro` + `--text-secondary`（内容仍是后端下发的 `qwen3.7-max`，一字不改）。
- **`.review-card` 去卡片** → `.review-item{padding:var(--s-4) 0; border-top:1px solid var(--hairline);}`；`.highlight` 改 `{background:var(--accent-wash); box-shadow:inset 2px 0 0 var(--accent);}`（内描边代替外发光）。
- `.compare-table`：`th` 用 `--font-mono` + `--fs-micro` + `uppercase` + `letter-spacing:.12em`；行线 `--hairline`；删 `tr:hover` 背景（表格 hover 高亮在投影时是噪声），改 `tr:hover td{color:var(--text-primary)}`。
- `.common-badge`/`.common-hint`：描边式 + 左 2px 竖线，同 `.tag` 规则。

### 块 J — 报告弹层 / Toast / 加载态（L731–833）
- `.report-dialog`：背景 `--bg-elev-1`，圆角 `--r-md`，`box-shadow:var(--overlay-shadow)`；去掉 `top:5%` 的浮动感 → `inset:4vh auto 4vh 50%; transform:translateX(-50%)`。
- `.report-body` Markdown 样式：字号全换 `--fs-*` 变量；`h2` 下边框 `--hairline` **保留**（报告需要层级线）；`blockquote` 左边框 `--accent-dim`（原为 brand 蓝）；`th` 背景 `--bg-elev-2`；`code` 色 `--sev-2`。
- `.toast`：圆角 `--r-sm` + `--font-mono` + `--fs-label` + `var(--overlay-shadow)` + `animation:toastIn 260ms var(--ease-out-expo)`；错误/成功用**左 2px 竖线**表达，不要整块染色。
- `.loading-spinner`：`border-color:var(--line)`，`border-top-color:var(--accent)`，14px。

### 块 K — 滚动条 / 响应式（L835–854）
- 滚动条 10px→**8px**，thumb `--bg-elev-3`→hover `--line-str`，圆角 0（方形滑块更像仪器）。
- 断点 980/640 保留，内部改用 `--s-*`；`.kpi-row` 在 980 以下变 2 列时**要清掉第 1、3 列的 `border-left`**。

---

## 3. HTML / JS 配套改动（只碰视觉）

### 3.1 emoji 清零表

| 位置 | 现状 | 替换 | 手段 |
|---|---|---|---|
| `index.html:19` 品牌 | 📡 | **内联 SVG 雷达标**：3 条同心圆 stroke + 40° 扫描扇形（半透明 accent 填充）+ 中心 2px 圆点；`stroke="currentColor" stroke-width="1.5"` | 内联 SVG |
| `index.html:44` 空态 | 📊 | **CSS 十字准星**：`.empty-mark` 72×72，`::before` 竖线 / `::after` 横线（1px `--line-str`）+ 中心 `<span>` 8px 方框 `border:1px solid var(--accent)` `rotate(45deg)` | CSS 伪元素 |
| `index.html:60/75/93` | 🔥🎯💡 | 等宽序号 `01` / `02` / `03` | 纯排版 |
| `index.html:125` | 📄 分析报告预览 | 删图标，只留文字 | 删除 |
| `detail-panel.js:182` | 🔍 痛点：xxx | 删图标 | 删除 |
| `detail-panel.js:237` | 🔍 根因归因 | **双行标签** `<h3><span class="lbl-zh">根因归因</span><span class="lbl-en">ROOT CAUSE</span></h3>` | 纯排版 |
| `detail-panel.js:310` | 📋 代表性评论 | 双行标签 `代表性评论 / EVIDENCE` | 纯排版 |
| `detail-panel.js:367` | 🆚 竞品对比 | 双行标签 `竞品对比 / BENCHMARK` | 纯排版 |
| `detail-panel.js:209/258/394` | ⭐ | 数字 + **CSS 星条**（5 个 3×8px 方块，`--sev-2` 实 / `--bg-elev-3` 空） | CSS |
| `detail-panel.js:258` | 👍 N | `HELPFUL 128`（全大写等宽小标签） | 纯排版 |
| `detail-panel.js:224` | ✅ 是 | `✓`（U+2713）+ `--accent` | 排版字符 |
| `detail-panel.js:400` | ✅ 共性 | 描边式 `.common-badge`，文案「共性」 | 纯排版 |
| `detail-panel.js:411` | 💡 这是品类共性弱点… | 删灯泡，保留文案 + 左 2px `--accent` 竖线 | 删除 |
| `progress.js:189` | ✅ …完成 | `✓`（排版字符） | 排版字符 |
| `progress.js:196` | ❌ … | `!`（等宽，`--sev-5`） | 排版字符 |
| `progress.js:220` | 🎉 分析完成！报告已生成。 | `分析完成 · 报告已生成`（纯文字，不加任何图形） | 纯排版 |
| `heatmap.js:206` | ⭐Top5 归因 | `[TOP5]` 全大写方括号标注 | 纯排版 |
| `detail-panel.js:29` | ⯨ 半星 | 保留（U+2BE8 是排版字符）；若字形缺失风险高，改 0.5 舍入到整星 | 排版字符 |
| `app.js:357` console | `color:#4d8dff` | `color:#2fe0bd` | 代码内 |

**验收**：`grep -nP '[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}\x{FE0F}]' frontend/` 无命中（白名单：U+2197/2198/2192 箭头、U+2605/2606 星、U+2713/27E1）。

### 3.2 HTML 结构（`index.html`）

`<div class="panel panel-heatmap">` → `<section class="section">`，`.panel-header` → `.section-head`：
```html
<div class="section-head">
  <span class="section-index">01</span>
  <h2 class="section-title">痛点热力图</h2>
  <span class="section-tip">按影响面排序 · 点击任一痛点下钻详情</span>
</div>
<div class="section-body">…</div>
```
`.panel-matrix` / `.panel-suggestions` 同理，序号 `02` / `03`。`.dashboard` 的 `gap` → `var(--s-7)`。
空态：`<div class="empty-illustration">📊</div>` → `<div class="empty-mark" aria-hidden="true"><span></span></div>`，并去掉居中。

### 3.3 JS 改动点（新增 `frontend/js/theme.js`，在 `api.js` 之前引入）

**⚠️ 本项目最高风险**：Chart.js 画在 canvas 上，**读不到 CSS 变量**。若 `getPropertyValue` 拿到空串且无兜底，图表会渲染成黑块 / 默认宋体，整个看板毁掉。**每个 token 必须带硬编码 fallback。**
```js
(function (g) {
  "use strict";
  var cs = getComputedStyle(document.documentElement);
  function t(n, fb) { return cs.getPropertyValue(n).trim() || fb; }
  var T = {
    font:t("--font-body",'"PingFang SC","Microsoft YaHei",sans-serif'),
    fontMono:t("--font-mono","Consolas,monospace"),
    text:t("--text-primary","#eceef1"), textMuted:t("--text-muted","#82888f"), textFaint:t("--text-faint","#5c6268"),
    grid:t("--hairline","rgba(236,238,241,0.07)"), gridMid:t("--line-str","rgba(236,238,241,0.26)"),
    panel:t("--bg-elev-1","#171a1e"),
    sev:[t("--sev-1","#ffe9a8"),t("--sev-2","#ffcf5c"),t("--sev-3","#ff9f3d"),t("--sev-4","#f4703a"),t("--sev-5","#e0353c")],
    quad:{ quick_win:t("--quad-quick","#2fe0bd"), strategic:t("--quad-strategic","#b07cf0"),
           filler:t("--quad-filler","#9aa4b2"), thankless:t("--quad-thankless","#5b6472") },
    shape:{ quick_win:"circle", strategic:"triangle", filler:"rect", thankless:"crossRot" }
  };
  T.severity = function (r) {           // 阈值是业务逻辑，保持原值不动
    return r >= 0.25 ? T.sev[4] : r >= 0.18 ? T.sev[3] : r >= 0.12 ? T.sev[2] : r >= 0.06 ? T.sev[1] : T.sev[0];
  };
  g.VOC_THEME = T;
})(window);
```

**`heatmap.js`**：L16 `CHART_FONT`→`VOC_THEME.font`；L23 `severityColor()`→`VOC_THEME.severity(r)`；L48 `trendColor()` rising→`sev[4]`、falling→`--accent` 值（**不再用绿色**）、stable→`textMuted`；轴/网格/tooltip 颜色全部改读 token（`grid`/`gridMid`/`text`/`textMuted`/`panel`）；`borderRadius:4`→**0**，加 `borderWidth:0`；`backgroundColor` 改 scriptable，用 `createLinearGradient` 生成同色相左→右渐变（末端提亮 12%）表达"信号强度"；tooltip `cornerRadius:8`→**2**，背景改 `VOC_THEME.panel` 实色（去半透明），`bodyFont` 用 `fontMono` 让数字对齐。

**`matrix.js`**：L17 `CHART_FONT` 同上；L27 `quadrantColor()`→`VOC_THEME.quad[q]`；每个 dataset 加 **`pointStyle:VOC_THEME.shape[q]`**（形状三重编码，投影/色盲/黑白打印都能分辨）；`thankless` 改 `backgroundColor:"transparent"` + 实心 `borderColor`（空心＝退场）；L146–154 / L180–188 的 `rgba(140,160,220,...)` → `gridMid`/`grid`；tooltip 同 heatmap。

**`detail-panel.js`**：L193–198 硬编码 `#ff4d4f`/`#ff7a45`/`#ffa940` → `var(--sev-5)`/`var(--sev-4)`/`var(--sev-3)`（阈值 0.25/0.15 不动）；L220 `var(--brand)`→`var(--accent)`；L224 `var(--sev-critical)`→`var(--sev-5)`；**L492–503 `_showLightbox` 的内联硬编码色**（`#1a2342`/`#2c3760`/`#e8ecf6`）→ 加 `class="voc-lightbox"`，样式全移到 CSS（用 `--bg-elev-1`/`--line`/`--text-primary`）；emoji 按 §3.1。

**`progress.js`**：L204–205 内联 `style.background="var(--error)"` / `boxShadow:"rgba(255,77,79,0.18)"` → 改 `stageEl.classList.add("stage-error")`，样式移入 CSS；emoji 按 §3.1。

**`app.js`**：L98/105/111/117 KPI accent 值 → 改为传 CSS 变量名字符串（`"var(--quad-filler)"` / `"var(--text-muted)"` / `"var(--sev-3)"` / `"var(--sev-5)"`），让 JS 不再持有颜色值；L357 console 色 `#4d8dff`→`#2fe0bd`。

---

## 4. 实现顺序（每批可独立验证）

| 批 | 内容 | 依赖 | 验证 |
|---|---|---|---|
| **0** | 备份 `style.css`；顶部**只加**新变量层，不动任何选择器 | — | 外观不变，控制台无报错 |
| **1** | 块 B + C + K（基础层/网格/顶栏/滚动条） | 0 | 字体·底色·网格·顶栏全变，布局不崩 |
| **2** | 块 F + G + §3.2（KPI 与区块去卡片、图表 inset、HTML 结构） | 1 | 三区块靠线条+留白分层，无任何卡片边 |
| **3** | 块 E + D（进度区、空态准星） | 1 | 跑一次分析，7 阶段正常，无流光 |
| **4** | 新增 `theme.js` + 改 `heatmap.js` / `matrix.js` | 0（不依赖样式改造） | 两图配色字体与新 token 一致；**断网也正常渲染** |
| **5** | §3.1 emoji 清零（index.html + 4 个 JS） | 1 | grep emoji 无命中，界面无豆腐块 |
| **6** | 块 H + I + J（卖点清单、抽屉、弹层/Toast） | 1、2 | 抽屉分隔线层级清晰，动画 480ms expo |
| **7** | 打磨：focus ring、hover 态、reduced-motion、断点竖线清理 | 全部 | 逐条过 §5 |

> 批 4 与批 1/2/3 **无依赖**，可提前做。批 2 与批 5 都改 `index.html`，需串行。

---

## 5. 验收标准

**硬指标（可 grep / 可测）**
- [ ] `var(--brand` 与 `#4d8dff` 全库 **0** 命中；`#000` / `#fff` **0** 命中（允许 `rgb(0 0 0 / .72)` 阴影 alpha）
- [ ] `border-radius` 除进度条外 **无 ≥8px** 的值
- [ ] JS 中 **0** 处 `-apple-system` / `Segoe UI` 系统默认字体栈
- [ ] emoji 正则全库 **0** 命中（白名单见 §3.1）
- [ ] **无**任何 webfont `<link>` / `@font-face` 外链
- [ ] style.css 中不再出现 `--gap-*` / `--radius-lg` / `--shadow-md`
- [ ] DevTools → Offline 刷新，界面**完整可用**（仅图表数据为空）

**视觉指标（投影 + 截图双场景）**
- [ ] 缩放到 150%（模拟大屏远距），每个一级区块仍靠线条分辨边界；KPI 数字 ≥28px
- [ ] 100% 缩放下 12px 的 `--text-muted` 不发虚（字重 ≤500 + `font-synthesis:none`）
- [ ] 对比度：正文 on `--bg-base` ≥ **12:1**；`--text-muted` ≥ **4.5:1**
- [ ] 严重度 5 色在**灰度滤镜**下明度单调递增
- [ ] 四象限 4 类点在**灰度截图**下可区分（靠明度 + 形状，不靠色相）
- [ ] 强调色 + 严重度色 + 象限色合计占屏 **<15% 像素**（克制＝高级）
- [ ] 抽屉动画 480ms expo 无卡顿；`prefers-reduced-motion` 开启时动画关闭

**AI Slop Test（决定性）** — 把截图给人看说"这是 AI 做的"，他会立刻相信吗？出现**任意一条**即失败：
- [ ] 主按钮蓝色渐变 + 深色底 → 已改磷光青实色 + 深色字
- [ ] 每块都是带圆角阴影的卡片、卡里套卡 → 已改线条 + 留白
- [ ] 标题旁有 emoji → 已清零
- [ ] 字体像 Inter / 系统默认 → 已是 DIN 工业体 + 等宽数字
- [ ] 空态是居中的大图标 + 一句话 → 已改左对齐十字准星
- [ ] 所有间距均匀 → 已用 4/8/12/20/32/52/84 非线性节奏
- [ ] 有无限循环渐变流光 → 已删除
- [ ] 数字用彩色大字 → KPI 数字已统一 `--text-primary`
- [ ] 非顶栏处有 `backdrop-filter` → 全站仅顶栏保留 8px
- [ ] "换个 logo 就是任何一个 SaaS 后台" → 细网格 + 等宽序号 + 双行中英标签 + 方角控件，应让人第一反应是**仪器面板**

**反向检验**：问"这看起来像什么？"，期望回答落在「仪器 / 雷达 / 终端 / 监控台」，而不是「AI 生成的后台模板」。

**一致性红线（不可因视觉改造破坏）**
- [ ] 「根因归因」「qwen3.7-max」「Top5」「7 阶段」等业务文案**一字未改**（对照 `.impeccable.md`）
- [ ] `model-badge` 仍由后端 `attr.model_used` 下发，前端未硬编码
- [ ] `progress.js` 的 7 个 stage label / tip 文案未改
