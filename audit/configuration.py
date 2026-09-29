import csv
import hashlib
import json
import re
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from .models import Account, ExperimentConfig, SessionPlan

FORBIDDEN = {"search", "like", "follow", "comment", "save", "share", "open_creator", "open_detail"}
MATCH = ("platform", "age_group", "region", "environment_profile", "batch_id",
         "avatar_code", "profile_template", "interest_selection", "scenario_id")


def aware(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("时间必须带时区，例如 2026-09-26T09:00:00+08:00")
    return result


def load_config(accounts_path: Path, experiment_path: Path) -> tuple[list[Account], ExperimentConfig, str]:
    text = experiment_path.read_text(encoding="utf-8-sig")
    try:
        data = json.loads(text)  # Bundled config uses the JSON subset of YAML 1.2.
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:
            raise ValueError("常规 YAML 需要 PyYAML；随附 JSON 风格 YAML 无额外依赖") from exc
        data = yaml.safe_load(text)
    cfg = ExperimentConfig(**data)
    with accounts_path.open(encoding="utf-8-sig", newline="") as stream:
        accounts = []
        for row in csv.DictReader(stream):
            if row.get("is_synthetic") not in ("true", "false"):
                raise ValueError("is_synthetic 只能是 true 或 false")
            row["is_synthetic"] = row["is_synthetic"] == "true"
            accounts.append(Account(**row))
    validate(accounts, cfg)
    canonical = {"accounts": [asdict(a) for a in sorted(accounts, key=lambda a: a.account_id)],
                 "experiment": asdict(cfg)}
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    return accounts, cfg, digest


def validate(accounts: list[Account], cfg: ExperimentConfig) -> None:
    if not accounts:
        raise ValueError("账号表为空")
    if cfg.scenario_id != "passive_cold_start" or set(cfg.forbidden_actions) != FORBIDDEN:
        raise ValueError("主实验只支持 passive_cold_start 且必须禁用所有主动动作")
    for value in (cfg.experiment_id, cfg.protocol_version):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("实验/版本编号仅允许英文字母、数字、下划线和连字符")
    for key in ("days", "items_per_session", "read_attempts"):
        if type(getattr(cfg, key)) is not int or getattr(cfg, key) < 1:
            raise ValueError(f"{key} 必须为正整数")
    for key in ("dwell_seconds", "retry_base_seconds", "max_registration_gap_seconds",
                "max_pair_start_skew_seconds", "max_start_delay_seconds"):
        value = getattr(cfg, key)
        if type(value) not in (int, float) or value < 0:
            raise ValueError(f"{key} 必须为非负数")
    if cfg.dwell_seconds <= 0:
        raise ValueError("停留时长必须大于0")
    start = aware(cfg.first_session_at)
    offsets = cfg.daily_offsets_minutes
    if (not offsets or any(type(x) is not int or x < 0 or x >= 1440 for x in offsets)
            or offsets != sorted(set(offsets)) or offsets[0] != 0):
        raise ValueError("时段偏移必须递增、不重复、从0开始并小于一天")
    if start.hour * 60 + start.minute + offsets[-1] >= 1440:
        raise ValueError("当天偏移不能跨越午夜")
    pairs: dict[str, list[Account]] = {}
    ids: set[str] = set()
    devices: set[str] = set()
    environments: set[str] = set()
    for a in accounts:
        if any(isinstance(v, str) and not v.strip() for v in asdict(a).values()):
            raise ValueError("必填账号字段为空")
        for key in (a.pair_id, a.account_id, a.batch_id):
            if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
                raise ValueError("账号、配对、批次编号格式错误")
        if a.gender not in ("female", "male") or a.platform not in ("douyin", "xiaohongshu"):
            raise ValueError("性别或平台枚举错误")
        if a.account_id in ids or a.device_id in devices or a.environment_id in environments:
            raise ValueError("第一版要求账号、设备、环境编号各自唯一")
        ids.add(a.account_id); devices.add(a.device_id); environments.add(a.environment_id)
        if a.status not in ("PLANNED", "REGISTERED", "READY") or a.scenario_id != cfg.scenario_id:
            raise ValueError("账号状态或 scenario 不匹配")
        if not aware(a.created_at) <= aware(a.gender_set_at) <= start:
            raise ValueError("应先注册、设置性别，再开始观察")
        pairs.setdefault(a.pair_id, []).append(a)
    for pair, members in pairs.items():
        if len(members) != 2 or {m.gender for m in members} != {"female", "male"}:
            raise ValueError(f"{pair}: 每对需要一个男性和一个女性账号")
        if any(getattr(members[0], k) != getattr(members[1], k) for k in MATCH):
            raise ValueError(f"{pair}: 配对资料不一致")
        gap = abs((aware(members[0].created_at) - aware(members[1].created_at)).total_seconds())
        if gap > cfg.max_registration_gap_seconds:
            raise ValueError(f"{pair}: 注册时间差过大")


def plans(cfg: ExperimentConfig) -> list[SessionPlan]:
    start = aware(cfg.first_session_at)
    return [SessionPlan(f"D{d+1:02d}-S{s+1:02d}",
                        (start + timedelta(days=d, minutes=offset)).isoformat(), cfg.items_per_session)
            for d in range(cfg.days) for s, offset in enumerate(cfg.daily_offsets_minutes)]
