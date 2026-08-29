"""VOC Radar — 演示数据灌库脚本（mock，仅用于截图/录屏）.

直接通过 SQLAlchemy 连接 backend/data/voc_radar.db，插入一份结构完整、
字段对齐 overview/heatmap/matrix/report 契约的示例分析结果。

不触发任何 LLM 调用，纯静态 mock。运行：
    cd backend
    .venv/Scripts/python.exe seed_demo.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.schemas import (  # noqa: E402
    Project,
    Review,
    PainPoint,
    Attribution,
    Suggestion,
    ListingSuggestion,
)

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "voc_radar.db")
engine = create_engine(f"sqlite:///{DB}", connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine)

now = datetime.now(timezone.utc)
asin_list = ["B0XASIN001", "B0XASIN002", "B0XASIN003"]


def reviews_for(cluster_texts: dict[int, list[str]], ratings: dict[int, int]):
    """生成 review 行（按 cluster 组织）。"""
    rows = []
    day = 0
    for cid, texts in cluster_texts.items():
        for i, body in enumerate(texts):
            day += 1
            rows.append(
                Review(
                    project_id="__PID__",
                    asin=asin_list[cid % len(asin_list)],
                    product_name="竞品无线蓝牙耳机",
                    rating=ratings.get(cid, 2),
                    title=("差评" if ratings.get(cid, 2) <= 2 else "中评"),
                    body=body,
                    date=now - timedelta(days=day),
                    variant=("标准版" if cid % 2 == 0 else "Pro 版"),
                    helpful_votes=(30 - i * 3) if i == 0 else max(0, 12 - i * 2),
                    is_vp=True,
                    has_image=(cid in (2, 4) and i == 0),
                    is_negative=True,
                    cluster_id=cid,
                    is_representative=(i == 0),
                    is_suspicious=False,
                )
            )
    return rows


# ---------------- 代表性评论文本 ----------------
cluster_texts = {
    0: [
        "宣传续航8小时，实际通勤听歌3小时就剩5%了，虚假宣传实锤。",
        "打游戏开降噪续航直接砍半，充一次电用不了一上午。",
        "早上满电出门，中午吃饭就没电了，太离谱。",
        "比我三年前的老耳机续航还短，退了。",
        "官方说的续航是怎么测出来的？我反正没体验到。",
    ],
    1: [
        "连上后走两步就断，地铁里基本处于半失联状态。",
        "左耳和手机经常断连，看视频音画不同步很烦。",
        "口袋里手机稍微隔一下就卡顿，蓝牙稳定性太差。",
        "双设备切换后经常连不回来，要重新配对。",
        "办公室隔一堵墙就断流，根本没法用。",
    ],
    2: [
        "充电仓合盖有咯吱咯吱的异响，像要散架。",
        "放桌上充电仓嗡嗡震动声很明显，晚上吵。",
        "开盖弹簧声音很大很廉价，质感拉胯。",
        "充电时充电仓内部有电流声，吓人。",
    ],
    3: [
        "触控区域太小，戴着手套完全点不动。",
        "双击切歌经常没反应，要戳好几下。",
        "误触严重，调整耳机就暂停了。",
        "戴久了耳朵出汗触控就失灵。",
    ],
    4: [
        "宣传主动降噪，地铁里该吵还是吵，不如我耳塞。",
        "风噪完全压不住，骑车戴就是受罪。",
        "降噪开了反而有电流底噪，更难受。",
        "通勤降噪几乎没感觉，和不开一样。",
    ],
    5: [
        "收到右耳就没声音，左耳正常，直接报废。",
        "用一周左耳突然不出声，重启也没用。",
        "单边音量忽大忽小，像接触不良。",
    ],
    6: [
        "戴不稳，跑步必掉，配的耳塞套也不贴合。",
        "小耳朵戴这个巨疼，半小时就摘了。",
        "耳翼太硬，久戴耳廓生疼。",
    ],
    7: [
        "低频几乎没有，听流行像蒙了层布。",
        "人声发虚，乐器糊成一团。",
        "对比同价位竞品音质明显单薄。",
    ],
    8: [
        "说明书全是机翻，看不懂怎么配对多设备。",
        "英文说明书都没写清楚按键逻辑，懵。",
        "APP 引导混乱，新手根本不会用。",
    ],
    9: [
        "盒子薄得像纸，收到都压瘪了。",
        "没送备用耳塞套，只有一种尺寸。",
        "包装一股塑料味，配件也少。",
    ],
}
ratings = {0: 2, 1: 2, 2: 3, 3: 3, 4: 3, 5: 2, 6: 3, 7: 3, 8: 3, 9: 4}

# 几条好评（非负面，用于平衡）
positive_reviews = [
    "外观挺好看的，白色很干净，同事问链接。",
    "价格便宜，当备用机够用了。",
    "配送快，当天就到了，包装完好。",
    "轻巧不压耳，通勤戴一天也不累。",
]


# ---------------- 痛点 + 归因 + 建议 ----------------
# 字段: cluster, label, count, impact, rating, trend, top5, common, reasoning, reason,
#        desc, root_cause, evidence[], measures[], suggestions[]
pp_defs = [
    {
        "cluster": 0, "label": "续航明显短于宣传", "count": 45, "impact": 0.28,
        "rating": 2.1, "trend": "rising", "top5": True, "common": True, "reasoning": True,
        "reason": "体验型痛点，涉及电池容量/电源管理策略，需根因推理",
        "desc": "标称 8 小时续航，实测重度使用仅 2.5~3.5 小时，差评高频集中。",
        "root_cause": "电池标称容量（40mAh/耳）与实际放电曲线不匹配：① 蓝牙+降噪全开时峰值功耗约 12mA，电池实际可用容量被过放保护截断；② 电源管理固件未做自适应降功耗，空闲也满功率。根因在电芯选型偏小 + 固件功耗策略缺失，而非单个元件故障。",
        "evidence": [
            {"quote": "宣传续航8小时，实际通勤听歌3小时就剩5%了", "rating": 2, "asin": "B0XASIN001"},
            {"quote": "打游戏开降噪续航直接砍半，充一次电用不了一上午", "rating": 2, "asin": "B0XASIN002"},
            {"quote": "比我三年前的老耳机续航还短", "rating": 2, "asin": "B0XASIN003"},
        ],
        "measures": [
            {"measure": "升级电芯至 55mAh/耳并重新标定放电曲线", "cost": "medium", "priority": "high"},
            {"measure": "固件增加自适应降功耗：空闲 30s 降频蓝牙", "cost": "low", "priority": "high"},
        ],
        "suggestions": [
            {"type": "product_improvement", "content": "将标称续航回归真实区间（重度 4h/轻度 7h），避免虚假宣传引发的信任崩塌", "cost": "low", "priority": "high", "quadrant": "quick_win"},
            {"type": "listing_optimization", "content": "Listing 主图用真实续航场景图（地铁通勤 1 日），替代理想化 8h 数字", "cost": "low", "priority": "medium", "quadrant": "quick_win"},
        ],
    },
    {
        "cluster": 1, "label": "连接不稳定易断连", "count": 39, "impact": 0.24,
        "rating": 2.3, "trend": "rising", "top5": True, "common": True, "reasoning": True,
        "reason": "环境触发型痛点，与蓝牙协议栈/天线有关，需根因推理",
        "desc": "隔墙、口袋、地铁等弱信号场景断连频繁，三竞品均高频出现。",
        "root_cause": "① 采用低成本单天线布局，人体（手/头）遮挡后 RSSI 骤降 15dBm；② 蓝牙协议栈未实现抗丢包重传优化，2.4G 干扰下直接断链。属天线设计 + 协议栈两层缺陷，非偶发。",
        "evidence": [
            {"quote": "连上后走两步就断，地铁里基本处于半失联状态", "rating": 2, "asin": "B0XASIN001"},
            {"quote": "口袋里手机稍微隔一下就卡顿，蓝牙稳定性太差", "rating": 2, "asin": "B0XASIN002"},
            {"quote": "办公室隔一堵墙就断流", "rating": 2, "asin": "B0XASIN003"},
        ],
        "measures": [
            {"measure": "改用双天线分集 + 陶瓷天线提升穿透", "cost": "high", "priority": "high"},
            {"measure": "协议栈开启 LE Audio 抗干扰重传", "cost": "medium", "priority": "medium"},
        ],
        "suggestions": [
            {"type": "product_improvement", "content": "下一代硬件上双天线分集方案，重点解决人体遮挡断连", "cost": "high", "priority": "high", "quadrant": "strategic"},
            {"type": "listing_optimization", "content": "强调『稳定连接』卖点时需配实测视频（隔墙/口袋场景），否则与差评矛盾", "cost": "low", "priority": "medium", "quadrant": "filler"},
        ],
    },
    {
        "cluster": 2, "label": "充电仓异响/廉价感", "count": 28, "impact": 0.19,
        "rating": 2.6, "trend": "stable", "top5": True, "common": False, "reasoning": True,
        "reason": "硬件装配工艺问题，需根因推理",
        "desc": "充电仓合盖异响、电流声、弹簧声，集中指向结构装配公差。",
        "root_cause": "① 转轴 hinge 间隙公差 ±0.3mm 偏大，合盖共振异响；② 充电仓未做磁屏蔽，线圈啸叫经塑料壳放大。属结构件公差 + 电磁兼容两层工艺问题。",
        "evidence": [
            {"quote": "充电仓合盖有咯吱咯吱的异响，像要散架", "rating": 3, "asin": "B0XASIN001"},
            {"quote": "充电时充电仓内部有电流声", "rating": 3, "asin": "B0XASIN002"},
        ],
        "measures": [
            {"measure": "收紧 hinge 公差至 ±0.1mm 并加阻尼脂", "cost": "low", "priority": "high"},
            {"measure": "充电仓内壁贴吸波材料抑制啸叫", "cost": "low", "priority": "medium"},
        ],
        "suggestions": [
            {"type": "product_improvement", "content": "结构件公差收紧 + 吸波材料，消除异响提升质感", "cost": "low", "priority": "high", "quadrant": "quick_win"},
        ],
    },
    {
        "cluster": 3, "label": "触控不灵敏/误触", "count": 24, "impact": 0.16,
        "rating": 2.8, "trend": "stable", "top5": True, "common": False, "reasoning": True,
        "reason": "固件算法问题，需根因推理",
        "desc": "触控区域小、误触、汗湿失灵，指向触控算法与区域定义。",
        "root_cause": "① 触控感应区仅耳柄上 1/3，有效面积小；② 算法未区分「调整佩戴」与「点击」手势，导致误触。属交互定义 + 算法两层问题，软件可迭代优化。",
        "evidence": [
            {"quote": "双击切歌经常没反应，要戳好几下", "rating": 3, "asin": "B0XASIN001"},
            {"quote": "误触严重，调整耳机就暂停了", "rating": 3, "asin": "B0XASIN003"},
        ],
        "measures": [
            {"measure": "扩大触控区 + 加手势去抖算法", "cost": "low", "priority": "medium"},
        ],
        "suggestions": [
            {"type": "product_improvement", "content": "固件 OTA 扩大触控区并加手势去抖，低成本高感知", "cost": "low", "priority": "medium", "quadrant": "quick_win"},
        ],
    },
    {
        "cluster": 4, "label": "主动降噪效果差", "count": 22, "impact": 0.15,
        "rating": 2.9, "trend": "rising", "top5": True, "common": True, "reasoning": True,
        "reason": "算法+硬件问题，需根因推理",
        "desc": "地铁/风噪场景降噪几乎无效甚至引入底噪，三竞品共性。",
        "root_cause": "① 单反馈麦克风 + 低端 DSP，ANC 深度仅 ~15dB（行业 25dB+）；② 未做风噪检测与抑制（wind detection）。属麦克风配置 + ANC 算法两层短板。",
        "evidence": [
            {"quote": "宣传主动降噪，地铁里该吵还是吵", "rating": 3, "asin": "B0XASIN001"},
            {"quote": "降噪开了反而有电流底噪", "rating": 3, "asin": "B0XASIN002"},
        ],
        "measures": [
            {"measure": "双馈 ANC + 加风噪检测通道", "cost": "high", "priority": "high"},
        ],
        "suggestions": [
            {"type": "product_improvement", "content": "下一代上双馈 ANC 与风噪检测，拉开与同价位差距", "cost": "high", "priority": "high", "quadrant": "strategic"},
        ],
    },
    {
        "cluster": 5, "label": "单耳无声/接触不良", "count": 18, "impact": 0.13,
        "rating": 2.4, "trend": "stable", "top5": False, "common": False, "reasoning": True,
        "reason": "硬件良率问题，可推理但不进 Top5",
        "desc": "单耳无声多为受潮/焊点虚焊，属良率而非设计，列入观察。",
        "root_cause": "初步判断为电池触点氧化 + 焊点虚焊良率问题，样本量不足以定为设计缺陷，建议产线增加耳机组装后老化测试。",
        "evidence": [{"quote": "收到右耳就没声音，左耳正常", "rating": 2, "asin": "B0XASIN003"}],
        "measures": [{"measure": "产线增加 100% 老化测试筛选虚焊", "cost": "low", "priority": "medium"}],
        "suggestions": [
            {"type": "product_improvement", "content": "产线加老化测试控良率，降低单耳失效退货率", "cost": "low", "priority": "medium", "quadrant": "filler"},
        ],
    },
    {
        "cluster": 6, "label": "佩戴不稳易掉落", "count": 15, "impact": 0.12,
        "rating": 3.0, "trend": "stable", "top5": False, "common": False, "reasoning": False,
        "reason": "简单事实型：耳塞套尺寸单一，无需深度推理",
        "desc": "仅配单一尺寸耳塞套，小耳用户必掉，属配件缺失。",
        "root_cause": "配置层面问题：未附多尺寸耳塞套，非技术根因。",
        "evidence": [{"quote": "戴不稳，跑步必掉", "rating": 3, "asin": "B0XASIN001"}],
        "measures": [{"measure": "附赠 S/M/L 三套耳塞 + 耳翼", "cost": "low", "priority": "low"}],
        "suggestions": [
            {"type": "product_improvement", "content": "标配多尺寸耳塞套+耳翼，零成本解决佩戴", "cost": "low", "priority": "low", "quadrant": "filler"},
        ],
    },
    {
        "cluster": 7, "label": "音质平淡缺低频", "count": 12, "impact": 0.10,
        "rating": 3.2, "trend": "stable", "top5": False, "common": False, "reasoning": False,
        "reason": "简单事实型：调音风格，无需根因推理",
        "desc": "低频缺失为调音取向，非缺陷，可差异化。",
        "root_cause": "调音偏薄，属产品定位选择，可针对运动场景强化低频。",
        "evidence": [{"quote": "低频几乎没有，听流行像蒙了层布", "rating": 3, "asin": "B0XASIN002"}],
        "measures": [{"measure": "推出「重低音」EQ 预设", "cost": "low", "priority": "low"}],
        "suggestions": [
            {"type": "listing_optimization", "content": "以『运动重低音』为差异化卖点，避开与音质旗舰正面竞争", "cost": "low", "priority": "low", "quadrant": "filler"},
        ],
    },
    {
        "cluster": 8, "label": "说明书/引导混乱", "count": 9, "impact": 0.07,
        "rating": 3.4, "trend": "stable", "top5": False, "common": False, "reasoning": False,
        "reason": "简单事实型：本地化缺失",
        "desc": "机翻说明书 + APP 引导差，新手上手成本高。",
        "root_cause": "本地化与 onboarding 投入不足，纯文档/交互问题。",
        "evidence": [{"quote": "说明书全是机翻，看不懂怎么配对多设备", "rating": 3, "asin": "B0XASIN001"}],
        "measures": [{"measure": "重做中文图文快速指南 + APP 引导", "cost": "low", "priority": "low"}],
        "suggestions": [
            {"type": "listing_optimization", "content": "详情页放 30 秒上手短视频，降低认知门槛", "cost": "low", "priority": "low", "quadrant": "filler"},
        ],
    },
    {
        "cluster": 9, "label": "包装简陋配件少", "count": 7, "impact": 0.05,
        "rating": 3.6, "trend": "stable", "top5": False, "common": False, "reasoning": False,
        "reason": "简单事实型：物料成本",
        "desc": "包装薄、无备用耳塞，开箱体验差但影响低。",
        "root_cause": "物料成本压缩，低优先级。",
        "evidence": [{"quote": "盒子薄得像纸，收到都压瘪了", "rating": 4, "asin": "B0XASIN003"}],
        "measures": [{"measure": "升级彩盒 + 附备用耳塞", "cost": "low", "priority": "low"}],
        "suggestions": [
            {"type": "listing_optimization", "content": "开箱体验轻升级即可，ROI 低，低优先级", "cost": "low", "priority": "low", "quadrant": "thankless"},
        ],
    },
]

listing_defs = [
    {
        "weak": "三竞品续航均虚标（实测仅宣传的 40%~50%）",
        "sp": "主推『真实续航 7 小时』+ 第三方实测截图背书，直击品类信任痛点",
        "field": "bullet_point", "priority": "high",
        "rationale": "续航是 Top1 共性弱点，谁先说真话谁赢得信任",
    },
    {
        "weak": "连接不稳定为品类第二共性弱点",
        "sp": "强调『双天线稳定连接·隔墙不断』并配实测对比视频",
        "field": "bullet_point", "priority": "high",
        "rationale": "连接稳定性差异化空间大，配视频可证伪竞品差评",
    },
    {
        "weak": "降噪效果差且三竞品都弱",
        "sp": "若上双馈 ANC，主打『地铁级深度降噪』抢占空白心智",
        "field": "a_plus_content", "priority": "medium",
        "rationale": "降噪是上升痛点，做好即品类领导",
    },
    {
        "weak": "佩戴不适/单一耳塞套",
        "sp": "标配 S/M/L 耳塞+耳翼，主打『运动不掉』场景化卖点",
        "field": "title", "priority": "medium",
        "rationale": "配件补齐零成本，运动场景差异化明确",
    },
]


def main():
    # 清旧 demo
    with Session() as s:
        old = s.query(Project).filter(Project.name.like("VOC Radar Demo%")).all()
        for p in old:
            s.delete(p)
        s.commit()

    with Session() as s:
        proj = Project(
            name="VOC Radar Demo · 无线蓝牙耳机竞品分析",
            category="Wireless Bluetooth Earbuds（无线蓝牙耳机）",
            status="completed",
            current_stage="s7_report",
            progress=1.0,
            config={"max_competitors": 3, "top_n_attribution": 5, "category": "wireless_earbuds"},
        )
        proj.competitor_asin_list = asin_list
        proj.completed_at = now
        s.add(proj)
        s.flush()
        pid = proj.id

        # 差评
        rev_rows = reviews_for(cluster_texts, ratings)
        for r in rev_rows:
            r.project_id = pid
            s.add(r)
        # 好评
        for i, body in enumerate(positive_reviews):
            s.add(
                Review(
                    project_id=pid,
                    asin=asin_list[i % 3],
                    product_name="竞品无线蓝牙耳机",
                    rating=4 + (i % 2),
                    title="好评",
                    body=body,
                    date=now - timedelta(days=i + 1),
                    variant="标准版",
                    helpful_votes=8 - i,
                    is_vp=True,
                    has_image=False,
                    is_negative=False,
                    cluster_id=None,
                    is_representative=False,
                    is_suspicious=False,
                )
            )
        s.flush()

        # 痛点 + 归因 + 建议
        for d in pp_defs:
            pp = PainPoint(
                project_id=pid,
                cluster_id=d["cluster"],
                label=d["label"],
                description=d.get("desc"),
                review_count=d["count"],
                impact_ratio=d["impact"],
                avg_rating=d["rating"],
                trend=d["trend"],
                is_common_weakness=d["common"],
                suitable_for_reasoning=d["reasoning"],
                reasoning_reason=d.get("reason"),
                rank_by_impact=d["cluster"] + 1,
                is_top5=d["top5"],
                competitor_breakdown=json.dumps(
                    [
                        {"asin": a, "count": max(1, d["count"] // len(asin_list) + (1 if j == 0 else 0))}
                        for j, a in enumerate(asin_list)
                    ],
                    ensure_ascii=False,
                ),
            )
            s.add(pp)
            s.flush()

            if d.get("top5") and d.get("root_cause"):
                attr = Attribution(
                    pain_point_id=pp.id,
                    project_id=pid,
                    root_cause=d["root_cause"],
                    evidence=json.dumps(d["evidence"], ensure_ascii=False),
                    improvement_measures=json.dumps(d["measures"], ensure_ascii=False),
                    model_used="qwen3.7-max",
                    prompt_tokens=1820,
                    completion_tokens=640,
                    latency_ms=4200,
                )
                s.add(attr)

            for sug in d["suggestions"]:
                s.add(
                    Suggestion(
                        pain_point_id=pp.id,
                        project_id=pid,
                        type=sug["type"],
                        content=sug["content"],
                        cost=sug.get("cost"),
                        priority=sug["priority"],
                        quadrant=sug["quadrant"],
                    )
                )

        # Listing 卖点
        for ls in listing_defs:
            s.add(
                ListingSuggestion(
                    project_id=pid,
                    competitor_weakness=ls["weak"],
                    suggested_selling_point=ls["sp"],
                    listing_field=ls["field"],
                    priority=ls["priority"],
                    rationale=ls["rationale"],
                )
            )

        s.commit()
        print("✅ seed 完成 | project_id =", pid)
        print("   痛点簇:", len(pp_defs), "| 归因:", sum(1 for d in pp_defs if d.get("root_cause")),
              "| 评论:", len(rev_rows) + len(positive_reviews), "| Listing:", len(listing_defs))


if __name__ == "__main__":
    main()
