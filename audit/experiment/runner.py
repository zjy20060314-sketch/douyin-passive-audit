import sqlite3
import time
from collections.abc import Callable
from typing import Any

from ..collectors.feed import FeedCollector
from ..models import Account, AuditError, ExperimentConfig, SessionPlan, now
from ..platforms.base import BasePlatformAdapter
from ..storage.store import DataStore
from ..telemetry.logger import Logger
from .scenario import PassiveBrowsingScenario


class ExperimentRunner:
    def __init__(self, cfg: ExperimentConfig, store: DataStore, logger: Logger,
                 factory: Callable[[Account], BasePlatformAdapter], run_id: str,
                 sleep: Callable[[float], None] = time.sleep):
        self.cfg, self.store, self.logger = cfg, store, logger
        self.factory, self.run_id, self.sleep = factory, run_id, sleep
        self.collector = FeedCollector()
        self.scenario = PassiveBrowsingScenario(cfg.dwell_seconds)

    def run(self, accounts: list[Account], plans: list[SessionPlan], resume: bool = False) -> dict[str, Any]:
        self.store.start_run(self.run_id)
        self.logger.emit("RUN_START", scenario_id=self.cfg.scenario_id)
        held = set() if resume else self.store.held_pairs()
        try:
            for p in plans:
                for a in accounts:
                    self.store.ensure_session(a, p)
            for p in plans:
                for a in sorted(accounts, key=lambda x: (x.pair_id, x.account_id)):
                    if a.pair_id in held:
                        self.logger.emit("PAIR_HELD", account_id=a.account_id, pair_id=a.pair_id, session_id=p.session_id)
                        continue
                    if not self._session(a, p, resume):
                        held.add(a.pair_id)
            status = "NEEDS_ATTENTION" if held else "COMPLETED"
            self.store.end_run(self.run_id, status)
            self.store.export()
            summary = self.store.summary()
            self.logger.emit("RUN_END", status=status, summary=summary)
            return summary
        except BaseException as exc:
            # Includes keyboard interrupts: preserve committed rows and require review.
            self.logger.emit("RUN_INTERRUPTED", "ERROR", error_type=type(exc).__name__)
            try:
                self.store.end_run(self.run_id, "INTERRUPTED")
            except sqlite3.Error:
                self.logger.emit("STORAGE_WRITE_FAILED", "ERROR", stage="end_run")
            raise

    def _session(self, a: Account, p: SessionPlan, resume: bool) -> bool:
        adapter: BasePlatformAdapter | None = None
        context = dict(account_id=a.account_id, pair_id=a.pair_id, batch_id=a.batch_id,
                       platform=a.platform, session_id=p.session_id)
        result = False
        try:
            checkpoint = self.store.session(a, p)
            if checkpoint["state"] in ("COMPLETED", "ABORTED", "MISSED"):
                result = True
                self.logger.emit("SESSION_SKIPPED_TERMINAL", state=checkpoint["state"], **context)
                return True
            self.logger.emit("SESSION_START", planned_start=p.planned_start, **context)
            if a.status != "READY":
                raise AuditError("ACCOUNT_NOT_READY", "请先人工核验账号准备状态")
            recovering = checkpoint["state"] != "SCHEDULED"
            if recovering and not resume:
                raise AuditError("RECOVERY_REVIEW_REQUIRED", "未完成会话需要显式 --resume")
            adapter = self.factory(a)
            self.store.update(a, p, state="PRECHECK", last_run_id=self.run_id)
            adapter.open_session(a, p.session_id)
            # Only mock is runnable in v0.1; real adapters fail closed at this gate.
            if not adapter.synthetic:
                raise AuditError("REAL_ADAPTER_NOT_VALIDATED", "真实适配器及时间门控尚未验收")
            next_position = checkpoint["last_position"] + 1
            if recovering:
                if not adapter.restore_position(next_position, checkpoint["phase"], checkpoint["last_token"]):
                    raise AuditError("MANUAL_VERIFICATION_REQUIRED", "无法确认页面游标，停止自动恢复")
                self.logger.emit("RESUME_CONFIRMED", next_position=next_position,
                                 prior_phase=checkpoint["phase"], synthetic=adapter.synthetic, **context)
            self.store.update(a, p, state="COLLECTING", phase="READY", reason=None,
                              actual_start=checkpoint["actual_start"] or now())
            for position in range(next_position, p.target_items + 1):
                started = time.monotonic()
                raw = None
                for attempt in range(1, self.cfg.read_attempts + 1):
                    try:
                        raw = adapter.read_current()
                        break
                    except AuditError as exc:
                        self.logger.emit(exc.code, "WARNING", attempt=attempt, position=position, **context)
                        if not exc.retryable or attempt == self.cfg.read_attempts:
                            raise
                        self.sleep(self.cfg.retry_base_seconds * 2 ** (attempt - 1))
                assert raw is not None
                record = self.collector.normalize(raw, a, self.cfg, p, self.run_id, position, adapter.synthetic)
                inserted = self.store.save(raw, record)
                self.logger.emit("EXPOSURE_SAVED" if inserted else "DUPLICATE_WRITE_SKIPPED", position=position, **context)
                if record.is_repeat_content:
                    self.logger.emit("REPEATED_CONTENT", position=position, content_id=record.content_id, **context)
                if record.error_code:
                    self.logger.emit(record.error_code, "WARNING", position=position, **context)
                timing = self.scenario.wait_remaining(started, self.sleep)
                self.logger.emit("DWELL_FINISHED", position=position, synthetic=adapter.synthetic, **timing, **context)
                if position < p.target_items:
                    self.store.update(a, p, phase="ADVANCE_PENDING")
                    self.logger.emit("ADVANCE_INTENT", position=position, **context)
                    adapter.advance_once()
                    self.store.update(a, p, phase="READY")
                    self.logger.emit("ADVANCE_CONFIRMED", position=position, **context)
            self.store.update(a, p, state="COMPLETED", phase="DONE", ended_at=now())
            result = True
        except Exception as exc:
            code = exc.code if isinstance(exc, AuditError) else (
                "STORAGE_WRITE_FAILED" if isinstance(exc, (sqlite3.Error, OSError)) else "UNEXPECTED_ERROR")
            self.logger.emit(code, "ERROR", error_type=type(exc).__name__, message=str(exc), **context)
            try:
                self.store.pause_pair(a.pair_id, code, self.run_id)
            except (sqlite3.Error, OSError):
                self.logger.emit("CHECKPOINT_WRITE_FAILED", "ERROR", **context)
        finally:
            if adapter is not None:
                try:
                    adapter.close()
                except Exception as exc:
                    result = False
                    self.logger.emit("ADAPTER_CLOSE_FAILED", "ERROR", message=str(exc), **context)
                    self.store.pause_pair(a.pair_id, "ADAPTER_CLOSE_FAILED", self.run_id)
            self.logger.emit("SESSION_END", outcome="COMPLETED_OR_SKIPPED" if result else "PAUSED_OR_INTERRUPTED", **context)
        return result
