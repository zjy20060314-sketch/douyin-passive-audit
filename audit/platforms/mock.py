from .base import BasePlatformAdapter
from ..models import Account, AuditError, RawObservation, now


class MockAdapter(BasePlatformAdapter):
    synthetic = True

    def __init__(self, fault: str | None = None):
        self.fault = fault
        self.fired = False
        self.position = 1

    def open_session(self, account: Account, session_id: str) -> None:
        if not account.is_synthetic:
            raise AuditError("MODE_MISMATCH", "mock不能与真实账号记录混用")
        self.account, self.session_id = account, session_id
        code = {"login": "LOGIN_EXPIRED", "offline": "ACCOUNT_OFFLINE",
                "verification": "MANUAL_VERIFICATION_REQUIRED"}.get(self.fault)
        if code:
            raise AuditError(code, "模拟故障；没有连接真实平台")

    def read_current(self) -> RawObservation:
        if self.fault == "load_once" and not self.fired:
            self.fired = True
            raise AuditError("PAGE_LOAD_FAILED", "模拟当前视图读取超时", True)
        if self.fault == "load_always":
            raise AuditError("PAGE_LOAD_FAILED", "模拟持续加载失败", True)
        token = f"{self.account.account_id}:{self.session_id}:{self.position}"
        if self.fault == "extract" and self.position == 2:
            return RawObservation(token, now(), {"unparsed_visible_text": "模拟无法识别的卡片",
                                                  "parse_error": "mock missing content fields"})
        # Deterministic repeats, identical behavior across genders.
        content = (self.position + 1) // 2
        return RawObservation(token, now(), {
            "content_id": f"MOCK-{self.account.platform}-{content}",
            "creator_id": "MOCK-CREATOR", "title_or_text": f"模拟内容 {content}，不可用于统计推断",
            "content_type": "video" if self.account.platform == "douyin" else "image_text",
            "url_or_internal_id": f"MOCK-{content}", "sponsored": None,
            "exposure_unit": "video" if self.account.platform == "douyin" else "card",
            "view_id": token, "slot_index": 1, "visible_fraction": 1.0,
            "is_synthetic": True})

    def advance_once(self) -> None:
        self.position += 1
        if self.fault == "advance" and not self.fired:
            self.fired = True
            raise AuditError("ADVANCE_UNCERTAIN", "模拟已翻页但确认丢失")

    def restore_position(self, position: int, phase: str, last_token: str | None) -> bool:
        self.position = position
        return True

    def after_manual_verification(self) -> bool:
        return True

    def close(self) -> None:
        pass
