import json
import os
import sys
from pathlib import Path
from typing import Any
from ..models import now


class Logger:
    def __init__(self, root: Path, experiment_id: str, run_id: str):
        folder = root / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / f"{run_id}.jsonl"
        self.experiment_id, self.run_id = experiment_id, run_id

    def emit(self, event: str, level: str = "INFO", **context: Any) -> None:
        data = dict(timestamp=now(), experiment_id=self.experiment_id, run_id=self.run_id,
                    event=event, level=level, **context)
        line = json.dumps(data, ensure_ascii=False, default=str)
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            print(line, file=sys.stderr)
            raise  # Do not silently continue collecting without an audit trail.
