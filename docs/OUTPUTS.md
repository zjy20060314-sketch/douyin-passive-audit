# 输出格式

## 单条记录

三个平台共用以下过程字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `position` | integer | 本次运行中的采集顺序 |
| `captured_at` | string | ISO 8601 采集时间 |
| `exposure_token` | string | 曝光去重标识 |
| `evidence_path` | string/null | 截图路径；默认不开截图，因此通常为 `null` |
| `dwell_seconds` | number | 本条随机停留秒数 |
| `content_id` | string | 平台内容唯一 ID |
| `title` | string | 页面可见标题 |
| `caption_text` | string/null | 正文或简介；页面没有时为 `null` |
| `tags` | array | 页面可见 Tags；没有时为 `[]` |
| `content_type` | string | 内容类型 |

平台差异：

- 抖音还包含作者、主题等推荐流审计字段。
- 小红书的 `content_type` 为 `image_text` 或 `video`。
- 哔哩哔哩的 `content_id` 通常为 BV/av ID，`content_type` 当前为 `video`。

## 运行文件

| 文件 | 产生时机 | 用途 |
|---|---|---|
| `observations.jsonl` | 采集过程中逐条追加 | 最完整的原始记录，意外停止时也尽量保留 |
| `exposures.csv` | 完成或受控暂停时 | 便于 Excel、R、Python 等读取 |
| `progress.json` | 运行中持续更新 | 状态、条数、耗时和最后内容 ID |
| `summary.json` | 正常完成时 | 总时长、停留范围、截图开关和禁止动作计数 |
| `failure.json` | 失败或暂停时 | 错误代码、原因和已保存条数 |
| `RESULT.md` | 完成或受控暂停时 | 人类可读的验收报告 |

`summary.json` 中的 `passive_actions` 会记录搜索、点赞、关注、评论、收藏、分享和进入创作者主页的次数；合格的被动采集运行中这些值应全部为 `0`。
