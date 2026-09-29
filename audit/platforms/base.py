from abc import ABC, abstractmethod
from ..models import Account, AuditError, RawObservation


class BasePlatformAdapter(ABC):
    synthetic: bool = False

    @abstractmethod
    def open_session(self, account: Account, session_id: str) -> None:
        """Check the authorized session without searching or opening creators."""

    @abstractmethod
    def read_current(self) -> RawObservation:
        """Read only the visible exposure. Retries must not navigate/refresh."""

    @abstractmethod
    def advance_once(self) -> None:
        """Confirm exactly one protocol-defined advance, or raise uncertainty."""

    def restore_position(self, position: int, phase: str, last_token: str | None) -> bool:
        """Never infer a real feed cursor from a numeric index alone."""
        return False

    def after_manual_verification(self) -> bool:
        """Future adapter must recheck login, feed, current item and timing."""
        return False

    @abstractmethod
    def close(self) -> None:
        """Release resources without further feed interaction."""


class PlaceholderAdapter(BasePlatformAdapter):
    platform_name = "unimplemented"

    def open_session(self, account: Account, session_id: str) -> None:
        raise AuditError("MANUAL_VERIFICATION_REQUIRED",
                         f"{self.platform_name}尚未接入：需要人工确认登录与平台适配")

    def read_current(self) -> RawObservation:
        raise AuditError("ADAPTER_NOT_IMPLEMENTED", self.platform_name)

    def advance_once(self) -> None:
        raise AuditError("ADAPTER_NOT_IMPLEMENTED", self.platform_name)

    def close(self) -> None:
        pass
