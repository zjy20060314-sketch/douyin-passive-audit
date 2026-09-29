import csv
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Iterator

from ..models import Account, ExperimentConfig, FeedRecord, RawObservation, SessionPlan, now


@contextmanager
def experiment_lock(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "experiment.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(f"运行锁已存在：{lock}。先确认原进程退出，再人工移除此锁。") from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "timestamp": now()}, stream)
        yield
    finally:
        lock.unlink(missing_ok=True)


class DataStore:
    def __init__(self, root: Path, accounts: list[Account], cfg: ExperimentConfig,
                 fingerprint: str, mode: str):
        self.root, self.experiment_id = root, cfg.experiment_id
        root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root / "audit.sqlite3", timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT);
          CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, started_at TEXT, ended_at TEXT, status TEXT);
          CREATE TABLE IF NOT EXISTS sessions(
            account_id TEXT, session_id TEXT, pair_id TEXT, planned_start TEXT,
            target_items INTEGER, state TEXT DEFAULT 'SCHEDULED', phase TEXT DEFAULT 'READY',
            last_position INTEGER DEFAULT 0, last_token TEXT, actual_start TEXT, ended_at TEXT,
            last_run_id TEXT, reason TEXT, PRIMARY KEY(account_id,session_id));
          CREATE TABLE IF NOT EXISTS raw_observations(
            experiment_id TEXT, account_id TEXT, session_id TEXT, position INTEGER, data TEXT,
            PRIMARY KEY(experiment_id,account_id,session_id,position));
          CREATE TABLE IF NOT EXISTS exposures(
            experiment_id TEXT, account_id TEXT, session_id TEXT, position INTEGER,
            platform TEXT, content_id TEXT, data TEXT,
            PRIMARY KEY(experiment_id,account_id,session_id,position));
          CREATE TABLE IF NOT EXISTS contents(
            experiment_id TEXT, platform TEXT, content_id TEXT, data TEXT,
            PRIMARY KEY(experiment_id,platform,content_id));
        ''')
        signature = fingerprint + ":" + mode
        old = self.db.execute("SELECT value FROM metadata WHERE key='signature'").fetchone()
        if old and old[0] != signature:
            self.db.close()
            raise ValueError("配置或模式发生变化：使用新的实验编号/数据目录，不得混写")
        with self.db:
            for key, value in {"signature": signature, "schema_version": "1",
                               "experiment": json.dumps(asdict(cfg), ensure_ascii=False),
                               "accounts": json.dumps([asdict(a) for a in accounts], ensure_ascii=False)}.items():
                self.db.execute("INSERT OR IGNORE INTO metadata VALUES (?,?)", (key, value))

    def start_run(self, run_id: str) -> None:
        with self.db:
            self.db.execute("INSERT INTO runs VALUES (?,?,NULL,'RUNNING')", (run_id, now()))

    def end_run(self, run_id: str, status: str) -> None:
        with self.db:
            self.db.execute("UPDATE runs SET ended_at=?,status=? WHERE run_id=?", (now(), status, run_id))

    def ensure_session(self, a: Account, p: SessionPlan) -> None:
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO sessions(account_id,session_id,pair_id,planned_start,target_items) VALUES (?,?,?,?,?)",
                            (a.account_id, p.session_id, a.pair_id, p.planned_start, p.target_items))

    def session(self, a: Account, p: SessionPlan) -> dict[str, Any]:
        return dict(self.db.execute("SELECT * FROM sessions WHERE account_id=? AND session_id=?",
                                    (a.account_id, p.session_id)).fetchone())

    def update(self, a: Account, p: SessionPlan, **changes: Any) -> None:
        allowed = {"state", "phase", "last_position", "last_token", "actual_start", "ended_at", "last_run_id", "reason"}
        if not changes or not set(changes) <= allowed:
            raise ValueError("未知检查点字段")
        with self.db:
            self.db.execute("UPDATE sessions SET " + ",".join(f"{k}=?" for k in changes)
                            + " WHERE account_id=? AND session_id=?", (*changes.values(), a.account_id, p.session_id))

    def pause_pair(self, pair_id: str, reason: str, run_id: str) -> None:
        with self.db:
            self.db.execute("UPDATE sessions SET state='PAUSED',reason=?,last_run_id=? WHERE pair_id=? AND state NOT IN ('COMPLETED','ABORTED','MISSED')",
                            (reason, run_id, pair_id))

    def held_pairs(self) -> set[str]:
        return {r[0] for r in self.db.execute("SELECT DISTINCT pair_id FROM sessions WHERE state='PAUSED'")}

    def save(self, raw: RawObservation, record: FeedRecord) -> bool:
        key = (record.experiment_id, record.account_id, record.session_id, record.position)
        with self.db:
            existing = self.db.execute("SELECT data FROM exposures WHERE experiment_id=? AND account_id=? AND session_id=? AND position=?", key).fetchone()
            if existing:
                old = json.loads(existing[0])
                if old["exposure_token"] != record.exposure_token or old["content_id"] != record.content_id:
                    raise ValueError("同一曝光位置出现不同内容，拒绝覆盖原记录")
                return False
            if record.content_id:
                record.is_repeat_content = self.db.execute(
                    "SELECT 1 FROM exposures WHERE account_id=? AND platform=? AND content_id=? LIMIT 1",
                    (record.account_id, record.platform, record.content_id)).fetchone() is not None
                self.db.execute("INSERT OR IGNORE INTO contents VALUES (?,?,?,?)",
                                (record.experiment_id, record.platform, record.content_id,
                                 json.dumps(raw.metadata, ensure_ascii=False)))
            raw_data = dict(experiment_id=record.experiment_id, run_id=record.run_id,
                            account_id=record.account_id, pair_id=record.pair_id,
                            session_id=record.session_id, position=record.position,
                            is_synthetic=record.is_synthetic, **asdict(raw))
            self.db.execute("INSERT INTO raw_observations VALUES (?,?,?,?,?)", (*key, json.dumps(raw_data, ensure_ascii=False)))
            self.db.execute("INSERT INTO exposures VALUES (?,?,?,?,?,?,?)",
                            (*key, record.platform, record.content_id, json.dumps(asdict(record), ensure_ascii=False)))
            self.db.execute("UPDATE sessions SET last_position=?,last_token=?,phase='CAPTURED' WHERE account_id=? AND session_id=?",
                            (record.position, record.exposure_token, record.account_id, record.session_id))
        return True

    def summary(self) -> dict[str, Any]:
        return {"sessions": {r[0]: r[1] for r in self.db.execute("SELECT state,COUNT(*) FROM sessions GROUP BY state")},
                "exposures": self.db.execute("SELECT COUNT(*) FROM exposures").fetchone()[0],
                "raw_observations": self.db.execute("SELECT COUNT(*) FROM raw_observations").fetchone()[0],
                "unique_contents": self.db.execute("SELECT COUNT(*) FROM contents").fetchone()[0]}

    def export(self) -> None:
        for name in ("raw", "processed"):
            (self.root / name).mkdir(exist_ok=True)
        raw_target = self.root / "raw" / "observations.jsonl"
        with raw_target.with_suffix(".tmp").open("w", encoding="utf-8") as f:
            for row in self.db.execute("SELECT data FROM raw_observations ORDER BY account_id,session_id,position"):
                f.write(row[0] + "\n")
        raw_target.with_suffix(".tmp").replace(raw_target)
        records = [json.loads(r[0]) for r in self.db.execute("SELECT data FROM exposures ORDER BY account_id,session_id,position")]
        target = self.root / "processed" / "exposures.csv"
        with target.with_suffix(".tmp").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[field.name for field in fields(FeedRecord)])
            writer.writeheader()
            for row in records:
                row["raw_metadata"] = json.dumps(row["raw_metadata"], ensure_ascii=False)
                # Protect human-opened CSV from spreadsheet formula interpretation.
                row = {k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v for k, v in row.items()}
                writer.writerow(row)
        target.with_suffix(".tmp").replace(target)
        for table in ("sessions", "runs", "contents"):
            cursor = self.db.execute(f"SELECT * FROM {table} ORDER BY rowid")
            target = self.root / "processed" / f"{table}.csv"
            with target.with_suffix(".tmp").open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([c[0] for c in cursor.description]); writer.writerows(cursor)
            target.with_suffix(".tmp").replace(target)
        snapshot = {r[0]: json.loads(r[1]) for r in self.db.execute("SELECT key,value FROM metadata WHERE key IN ('accounts','experiment')")}
        (self.root / "config_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    def close(self) -> None:
        self.db.close()
