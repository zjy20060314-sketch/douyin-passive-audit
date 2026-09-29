"""Validate a completed passive-collection output directory."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_FIELDS = ("content_id", "title", "caption_text", "tags", "topic", "dwell_seconds")
FORBIDDEN_ACTIONS = ("search", "like", "follow", "comment", "favorite", "share", "creator_page")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--expected-items", type=int)
    parser.add_argument("--expected-duration-minutes", type=float)
    args = parser.parse_args()
    root = args.output.resolve()
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    records = [json.loads(line) for line in (root / "observations.jsonl").read_text(
        encoding="utf-8").splitlines() if line.strip()]
    errors: list[str] = []
    if summary.get("status") != "COMPLETED":
        errors.append(f"status={summary.get('status')!r}")
    if summary.get("screenshots_enabled") is not False:
        errors.append("截图并非关闭状态")
    if args.expected_items is not None and len(records) != args.expected_items:
        errors.append(f"条数应为{args.expected_items}，实际为{len(records)}")
    if args.expected_duration_minutes is not None:
        requested = summary.get("requested_duration_minutes")
        if requested != args.expected_duration_minutes:
            errors.append(f"请求时长应为{args.expected_duration_minutes}，实际为{requested}")
    ids = [str(row.get("content_id") or "") for row in records]
    if len(set(ids)) != len(ids) or "" in ids:
        errors.append("内容ID缺失或重复")
    for index, row in enumerate(records, 1):
        missing = [field for field in REQUIRED_FIELDS if row.get(field) in (None, "", [])]
        if missing:
            errors.append(f"第{index}条缺少字段：{', '.join(missing)}")
        dwell = row.get("dwell_seconds")
        if not isinstance(dwell, (int, float)) or not 3 <= dwell <= 15:
            errors.append(f"第{index}条停留时间异常：{dwell!r}")
    actions = summary.get("passive_actions") or {}
    for action in FORBIDDEN_ACTIONS:
        if actions.get(action) != 0:
            errors.append(f"禁止动作{action}不为0")
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"valid": True, "items": len(records), "output": str(root)},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
