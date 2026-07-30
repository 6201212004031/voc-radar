# 原始数据集目录（data/raw/）

VOC Radar 原型阶段使用 **Kaggle Amazon Review 数据集**作为主数据源。

## 推荐数据集

### McAuley Lab - Amazon Reviews 2023

- 主页: https://github.com/McAuley-Lab/amazon_reviews_2023
- Kaggle 镜像: https://www.kaggle.com/datasets/mcauleylab/amazon-reviews-2023
- 字段齐全（rating/title/text/date/verified_purchase/image_url 等），适合本项目

### 备选数据集

- `Amazon Reviews` (https://www.kaggle.com/datasets/bittlingmayer/amazonreviews) — 仅 sentiment 标签，字段不全
- `Amazon Product Reviews` (https://www.kaggle.com/datasets//datafiniti/consumer-reviews-of-amazon-products) — 字段较全但样本少

## 数据文件放置方式

将下载的 CSV / JSON / JSONL 文件放到本目录，例如：

```
data/raw/
├── bluetooth_earbuds_reviews.csv        # 蓝牙耳机品类评论
├── product_asin_B0xxx_reviews.json      # 单 ASIN 评论（手动采集）
├── product_asin_B0yyy_reviews.json
└── meta_bluetooth_earbuds.json          # 商品元数据（可选）
```

## 必需字段

数据加载器 `app/services/data_loader.py` 会做字段映射，识别以下字段（任一命名变体）：

| 业务字段 | 接受的列名（按优先级） | 必需 |
|---------|----------------------|------|
| asin          | `asin`, `product_id`, `parent_asin` | ✅ |
| rating        | `rating`, `star`, `stars`, `overall` | ✅ |
| body          | `text`, `body`, `review_text`, `content`, `review` | ✅ |
| title         | `title`, `review_title`, `summary` | - |
| date          | `date`, `review_date`, `timestamp`, `time` | - |
| verified_purchase | `verified_purchase`, `is_vp`, `verified` | - |
| helpful_votes | `helpful_votes`, `helpful`, `helpfulness`, `votes` | - |
| variant       | `variant`, `style`, `color`, `size` | - |
| image_url     | `image_url`, `images`, `image` (单 URL 或 JSON 数组) | - |
| product_name  | `product_name`, `product_title`, `title` (来自 meta) | - |

## 演示品类建议

蓝牙耳机（Bluetooth Earbuds）：
- 评估评论量充足（>1000 条）
- 痛点直观（续航/连接/佩戴/音质）
- 评委易共鸣

## 注意

- 原始数据文件**不入 git**（已在 .gitignore 排除）
- 演示前请确认 `data/raw/` 下至少有 3 个竞品共 500+ 条评论
- 如使用 McAuley 数据集，可能需要按品类预先筛分子集，避免单文件过大
