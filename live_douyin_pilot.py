"""Small, passive end-to-end pilot for the visible Douyin Web adapter."""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from audit.models import Account, AuditError
from audit.platforms.douyin import DouyinAdapter


TOPICS: list[tuple[str, tuple[str, ...]]] = [
    ("财经", ("财经", "经济", "股票", "基金", "投资", "金融", "房价", "银行", "债券", "汇率", "黄金")),
    ("科技数码", ("科技", "手机", "电脑", "AI", "人工智能", "数码", "芯片", "软件", "机器人", "iPhone")),
    ("旅行", ("旅行", "旅游", "城市", "海滩", "景点", "自驾", "徒步", "露营", "酒店", "vlog",
             "大兴安岭", "风景", "秋天", "非洲", "沙漠", "环游世界")),
    ("美食", ("美食", "料理", "晚餐", "烤", "吃", "咖喱", "面", "甜品", "厨房", "食谱")),
    ("萌宠动物", ("萌宠", "猫咪", "小猫", "狗狗", "宠物", "动物")),
    ("影视娱乐", ("电影", "影视", "短剧", "电视剧", "综艺", "动漫", "音乐", "歌曲", "演员", "剧情")),
    ("教育知识", ("知识", "历史", "英语", "学习", "教程", "公开课", "科普", "读书", "考试")),
    ("体育健身", ("体育", "健身", "足球", "篮球", "跑步", "运动", "比赛")),
    ("游戏", ("游戏", "电竞", "玩家", "通关", "王者", "吃鸡")),
    ("汽车", ("汽车", "车评", "新车", "驾驶", "新能源", "油耗")),
    ("生活情感", ("生活", "日常", "情感", "自由", "妈妈", "宝宝", "家庭", "成长", "治愈")),
]


def classify_topic(text: str | None) -> tuple[str, list[str]]:
    source = text or ""
    scored = [(topic, [word for word in words if word.lower() in source.lower()]) for topic, words in TOPICS]
    scored.sort(key=lambda item: len(item[1]), reverse=True)
    return scored[0] if scored and scored[0][1] else ("其他", [])


def extract_tags(text: str | None) -> list[str]:
    """Extract visible hashtags in display order without opening hashtag pages."""
    tags: list[str] = []
    for tag in re.findall(r"#([^\s#，。！？、；：,.!?;:]+)", text or ""):
        if tag not in tags:
            tags.append(tag)
    return tags


def extract_caption_text(text: str | None) -> str | None:
    """Return visible copy with hashtag tokens removed, preserving line order."""
    lines: list[str] = []
    for line in (text or "").splitlines():
        cleaned = re.sub(r"#([^\s#，。！？、；：,.!?;:]+)", "", line).strip()
        if cleaned:
            lines.append(cleaned)
    if lines:
        return "\n".join(lines)
    tags = extract_tags(text)
    return " ".join(f"#{tag}" for tag in tags) or None


def extract_title(text: str | None) -> str | None:
    """Use the first visible non-tag copy line as the report title."""
    caption = extract_caption_text(text)
    return caption.splitlines()[0] if caption else None


def write_csv(output: Path, records: list[dict]) -> None:
    if not records:
        return
    fields = sorted({key for row in records for key in row})
    with (output / "exposures.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in records:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                             for k, v in row.items()})


def write_progress(output: Path, *, status: str, started_at: str, elapsed_seconds: float,
                   records: list[dict], duration_minutes: float | None,
                   error_code: str | None = None) -> None:
    progress = {"status": status, "started_at": started_at,
                "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "elapsed_seconds": round(elapsed_seconds, 3), "items": len(records),
                "requested_duration_minutes": duration_minutes,
                "last_content_id": records[-1]["content_id"] if records else None,
                "error_code": error_code}
    (output / "progress.json").write_text(json.dumps(progress, ensure_ascii=False, indent=2),
                                          encoding="utf-8")


def write_result_report(output: Path, *, status: str, records: list[dict],
                        duration_minutes: float | None, elapsed_seconds: float,
                        error_code: str | None = None) -> None:
    def cell(value: object) -> str:
        return str(value or "").replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    lines = ["# 抖音网页版被动采集报告", "", f"- 状态：`{status}`",
             f"- 已采集：{len(records)} 条", f"- 请求时长：{duration_minutes or 0:g} 分钟",
             f"- 实际采集时长：{elapsed_seconds:.3f} 秒", "- 截图：关闭",
             "- 禁止动作：搜索、点赞、关注、评论、收藏、分享、进入创作者页均为 0"]
    if error_code:
        lines.append(f"- 停止原因：`{error_code}`")
    lines.extend(["", "| 位置 | 内容 ID | 作者 | 题目 | 文案 | Tags | 主题 | 停留/秒 |",
                  "|---:|---|---|---|---|---|---|---:|"])
    for row in records:
        lines.append("| " + " | ".join([
            str(row.get("position", "")), cell(row.get("content_id")), cell(row.get("author")),
            cell(row.get("title")), cell(row.get("caption_text")),
            cell("、".join(row.get("tags") or [])), cell(row.get("topic")),
            str(row.get("dwell_seconds", "")),
        ]) + " |")
    (output / "RESULT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_account() -> Account:
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    return Account(pair_id="DEBUG", account_id="DY-WEB-TEST", gender="UNSPECIFIED",
                   platform="douyin", age_group="UNSPECIFIED", region="UNSPECIFIED",
                   device_id="EDGE-DEDICATED", environment_id="EDGE-PROFILE",
                   environment_profile="dedicated_visible_edge", batch_id="DEBUG",
                   created_at=stamp, gender_set_at=stamp, status="READY", avatar_code="",
                   profile_template="dedicated_test_account", interest_selection="none",
                   scenario_id="passive_random_dwell", is_synthetic=False)


def main() -> int:
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="抖音网页版少量被动采集：可见Edge、结构化字段、标签与本地主题读取")
    limit = parser.add_mutually_exclusive_group()
    limit.add_argument("--items", type=int)
    limit.add_argument("--duration-minutes", type=float,
                       help="按实际经过时间连续采集；例如60表示运行1小时")
    parser.add_argument("--min-dwell-seconds", type=float, default=3.0)
    parser.add_argument("--max-dwell-seconds", type=float, default=15.0)
    parser.add_argument("--screenshots", action="store_true", help="可选保存逐条截图；默认关闭")
    parser.add_argument("--login-wait-seconds", type=float, default=0.0,
                        help="首次设置专用资料时等待人工完成登录；登录后同一次运行自动续采")
    parser.add_argument("--output", type=Path,
                        default=base / "data_live_debug" / datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--profile", type=Path, default=base / "runtime/douyin-edge-profile")
    args = parser.parse_args()
    if args.items is None and args.duration_minutes is None:
        args.items = 3
    if args.items is not None and not 1 <= args.items <= 10:
        raise ValueError("调试采集条数必须在1到10之间")
    if args.duration_minutes is not None and not 0.05 <= args.duration_minutes <= 180:
        raise ValueError("持续时间必须在0.05到180分钟之间")
    if args.min_dwell_seconds < 1 or args.max_dwell_seconds < args.min_dwell_seconds:
        raise ValueError("随机停留下限至少1秒，且上限不能小于下限")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    adapter = DouyinAdapter(output_dir=output, profile_dir=args.profile.resolve(),
                            login_wait_seconds=args.login_wait_seconds,
                            capture_screenshots=args.screenshots)
    records: list[dict] = []
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    started_monotonic = time.monotonic()
    try:
        adapter.open_session(test_account(), "WEB-DEBUG")
        collection_started = time.monotonic()
        deadline = (collection_started + args.duration_minutes * 60
                    if args.duration_minutes is not None else None)
        rng = random.SystemRandom()
        position = 1
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                break
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining < args.min_dwell_seconds:
                    time.sleep(max(0.0, remaining))
                    break
            if args.items is not None and position > args.items:
                break
            raw = adapter.read_current()
            topic, hits = classify_topic(raw.metadata.get("title_or_text"))
            dwell_seconds = rng.uniform(args.min_dwell_seconds, args.max_dwell_seconds)
            if deadline is not None:
                dwell_seconds = min(dwell_seconds, deadline - time.monotonic())
            record = {"position": position, "captured_at": raw.captured_at,
                      "exposure_token": raw.exposure_token, "evidence_path": raw.evidence_path,
                      "topic": topic, "topic_keyword_hits": hits,
                      "tags": extract_tags(raw.metadata.get("title_or_text")),
                      "title": extract_title(raw.metadata.get("title_or_text")),
                      "caption_text": extract_caption_text(raw.metadata.get("title_or_text")),
                      "dwell_seconds": round(dwell_seconds, 3), **raw.metadata}
            records.append(record)
            with (output / "observations.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            write_progress(output, status="RUNNING", started_at=started_at,
                           elapsed_seconds=time.monotonic() - started_monotonic,
                           records=records, duration_minutes=args.duration_minutes)
            time.sleep(dwell_seconds)
            if deadline is not None and time.monotonic() >= deadline:
                break
            if args.items is not None and position >= args.items:
                break
            adapter.advance_once()
            position += 1
        write_csv(output, records)
        summary = {"status": "COMPLETED", "items": len(records), "synthetic": False,
                   "started_at": started_at,
                   "ended_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                   "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
                   "collection_elapsed_seconds": round(time.monotonic() - collection_started, 3),
                   "requested_duration_minutes": args.duration_minutes,
                   "dwell_seconds_range": [args.min_dwell_seconds, args.max_dwell_seconds],
                   "screenshots_enabled": args.screenshots,
                   "passive_actions": {"search": 0, "like": 0, "follow": 0, "comment": 0,
                                       "favorite": 0, "share": 0, "creator_page": 0},
                   "output": str(output), "records": records}
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        write_result_report(output, status="COMPLETED", records=records,
                            duration_minutes=args.duration_minutes,
                            elapsed_seconds=time.monotonic() - collection_started)
        write_progress(output, status="COMPLETED", started_at=started_at,
                       elapsed_seconds=time.monotonic() - started_monotonic,
                       records=records, duration_minutes=args.duration_minutes)
        print(json.dumps({k: v for k, v in summary.items() if k != "records"},
                         ensure_ascii=False, indent=2))
        return 0
    except AuditError as exc:
        write_csv(output, records)
        failure = {"status": "PAUSED", "error_code": exc.code, "message": str(exc),
                   "completed_items": len(records), "output": str(output),
                   "started_at": started_at,
                   "ended_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                   "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
                   "requested_duration_minutes": args.duration_minutes}
        (output / "failure.json").write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
        write_result_report(output, status="PAUSED", records=records,
                            duration_minutes=args.duration_minutes,
                            elapsed_seconds=time.monotonic() - started_monotonic,
                            error_code=exc.code)
        write_progress(output, status="PAUSED", started_at=started_at,
                       elapsed_seconds=time.monotonic() - started_monotonic,
                       records=records, duration_minutes=args.duration_minutes,
                       error_code=exc.code)
        print(json.dumps(failure, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    finally:
        adapter.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
