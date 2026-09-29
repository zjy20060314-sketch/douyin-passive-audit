from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class Account:
    pair_id: str
    account_id: str
    gender: str
    platform: str
    age_group: str
    region: str
    device_id: str
    environment_id: str
    environment_profile: str
    batch_id: str
    created_at: str
    gender_set_at: str
    status: str
    avatar_code: str
    profile_template: str
    interest_selection: str
    scenario_id: str
    is_synthetic: bool


@dataclass(frozen=True)
class ExperimentConfig:
    experiment_id: str
    protocol_version: str
    scenario_id: str
    first_session_at: str
    days: int
    daily_offsets_minutes: list[int]
    items_per_session: int
    dwell_seconds: float
    read_attempts: int
    retry_base_seconds: float
    max_registration_gap_seconds: float
    max_pair_start_skew_seconds: float
    max_start_delay_seconds: float
    forbidden_actions: list[str]


@dataclass(frozen=True)
class SessionPlan:
    session_id: str
    planned_start: str
    target_items: int


@dataclass
class RawObservation:
    exposure_token: str
    captured_at: str
    metadata: dict[str, Any]
    evidence_path: str | None = None


@dataclass
class FeedRecord:
    experiment_id: str
    run_id: str
    batch_id: str
    pair_id: str
    account_id: str
    gender: str
    platform: str
    session_id: str
    timestamp: str
    position: int
    planned_start: str
    protocol_version: str
    exposure_token: str
    content_id: str | None
    creator_id: str | None
    title_or_text: str | None
    content_type: str | None
    url_or_internal_id: str | None
    sponsored: bool | None
    raw_metadata: dict[str, Any]
    collection_status: str
    is_synthetic: bool
    evidence_path: str | None = None
    error_code: str | None = None
    category: str | None = None
    finance: bool | None = None
    finance_subtype: str | None = None
    label_source: str = "unlabeled"
    label_confidence: float | None = None
    is_repeat_content: bool = False
    exposure_unit: str | None = None
    view_id: str | None = None
    slot_index: int | None = None
    visible_fraction: float | None = None


class AuditError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
