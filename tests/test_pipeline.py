import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from audit.collectors.feed import FeedCollector
from audit.configuration import load_config, plans, validate
from audit.experiment.runner import ExperimentRunner
from audit.models import AuditError
from audit.platforms.douyin import DouyinAdapter
from live_douyin_pilot import classify_topic, extract_caption_text, extract_tags, extract_title
from audit.platforms.mock import MockAdapter
from audit.storage.store import DataStore, experiment_lock
from audit.telemetry.logger import Logger

BASE = Path(__file__).resolve().parents[1]


class PipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.accounts, cfg, _ = load_config(BASE / 'config/accounts.csv', BASE / 'config/experiment.yaml')
        self.cfg = replace(cfg, items_per_session=3, daily_offsets_minutes=[0])
        self.plans = plans(self.cfg)
        self.store = DataStore(self.root, self.accounts, self.cfg, 'test-config', 'mock')

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def runner(self, factory=None) -> ExperimentRunner:
        run_id = uuid4().hex
        return ExperimentRunner(self.cfg, self.store,
                                Logger(self.root, self.cfg.experiment_id, run_id),
                                factory or (lambda a: MockAdapter()), run_id, sleep=lambda _: None)

    def test_complete_and_idempotent_rerun(self) -> None:
        result = self.runner().run(self.accounts, self.plans)
        self.assertEqual(result['exposures'], 24)
        self.assertEqual(result['raw_observations'], 24)
        self.assertEqual(result['sessions'], {'COMPLETED': 8})
        self.assertEqual(self.runner().run(self.accounts, self.plans)['exposures'], 24)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 2)

    def test_pair_mismatch_rejected(self) -> None:
        bad = self.accounts.copy(); bad[1] = replace(bad[1], region='上海')
        with self.assertRaisesRegex(ValueError, '配对资料'):
            validate(bad, self.cfg)

    def test_active_scenario_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate(self.accounts, replace(self.cfg, scenario_id='random_like'))

    def test_repeated_content_retains_exposures(self) -> None:
        self.runner().run(self.accounts, self.plans)
        result = self.store.summary()
        self.assertEqual(result['unique_contents'], 4)
        self.assertEqual(result['exposures'], 24)
        rows = [json.loads(r[0]) for r in self.store.db.execute('SELECT data FROM exposures')]
        self.assertEqual(sum(r['is_repeat_content'] for r in rows), 8)

    def test_unknown_label_preserves_raw(self) -> None:
        self.runner(lambda a: MockAdapter('extract')).run(self.accounts, self.plans)
        rows = [json.loads(r[0]) for r in self.store.db.execute('SELECT data FROM exposures WHERE position=2')]
        self.assertTrue(all(r['finance'] is None and r['sponsored'] is None for r in rows))
        self.assertTrue(all(r['collection_status'] == 'EXTRACTION_FAILED' for r in rows))
        self.assertEqual(self.store.summary()['raw_observations'], 24)

    def test_read_retry_does_not_advance(self) -> None:
        result = self.runner(lambda a: MockAdapter('load_once')).run(self.accounts, self.plans)
        self.assertEqual(result['exposures'], 24)
        lines = ''.join(p.read_text(encoding='utf-8') for p in (self.root / 'logs').glob('*.jsonl'))
        self.assertEqual(lines.count('PAGE_LOAD_FAILED'), 8)

    def test_read_retry_exhaustion_is_bounded(self) -> None:
        result = self.runner(lambda a: MockAdapter('load_always')).run(self.accounts, self.plans)
        self.assertEqual(result['exposures'], 0)
        self.assertEqual(result['sessions'], {'PAUSED': 8})
        events = [json.loads(line) for p in (self.root/'logs').glob('*.jsonl') for line in p.read_text(encoding='utf-8').splitlines()]
        attempts = [e for e in events if e['event'] == 'PAGE_LOAD_FAILED' and 'attempt' in e]
        self.assertEqual(len(attempts), 4 * self.cfg.read_attempts)

    def test_account_failure_does_not_stop_other_pairs(self) -> None:
        result = self.runner(lambda a: MockAdapter('login' if a.account_id == 'DY-A01' else None)).run(self.accounts, self.plans)
        self.assertEqual(result['sessions'], {'COMPLETED': 6, 'PAUSED': 2})
        self.assertEqual(result['exposures'], 18)

    def test_advance_uncertainty_requires_resume(self) -> None:
        result = self.runner(lambda a: MockAdapter('advance' if a.account_id == 'DY-A01' else None)).run(self.accounts, self.plans)
        self.assertEqual(result['exposures'], 19)
        self.assertEqual(self.runner().run(self.accounts, self.plans)['exposures'], 19)
        result = self.runner().run(self.accounts, self.plans, resume=True)
        self.assertEqual(result['sessions'], {'COMPLETED': 8})
        self.assertEqual(result['exposures'], 24)

    def test_interrupt_after_commit_recovers_without_overwrite(self) -> None:
        class InterruptAdapter(MockAdapter):
            def advance_once(self) -> None:
                raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.runner(lambda a: InterruptAdapter()).run(self.accounts, self.plans)
        self.assertEqual(self.store.summary()['exposures'], 1)
        self.assertEqual(self.runner().run(self.accounts, self.plans, resume=True)['exposures'], 24)

    def test_transaction_failure_rolls_back_raw_and_exposure(self) -> None:
        self.store.db.execute("CREATE TRIGGER fail_test BEFORE INSERT ON exposures WHEN NEW.account_id='DY-A01' BEGIN SELECT RAISE(ABORT, 'simulated disk write failure'); END;")
        result = self.runner().run(self.accounts, self.plans)
        self.assertEqual(result['exposures'], 18)
        self.assertEqual(result['raw_observations'], 18)
        self.assertEqual(result['sessions']['PAUSED'], 2)
        logs = ''.join(p.read_text(encoding='utf-8') for p in (self.root/'logs').glob('*.jsonl'))
        self.assertIn('STORAGE_WRITE_FAILED', logs)

    def test_config_change_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, '配置或模式'):
            DataStore(self.root, self.accounts, self.cfg, 'changed', 'mock')

    def test_douyin_adapter_is_real_but_lazy(self) -> None:
        adapter = DouyinAdapter()
        self.assertFalse(adapter.synthetic)
        self.assertIsNone(adapter.process)
        self.assertFalse(adapter.restore_position(2, 'ADVANCE_PENDING', None))

    def test_local_topic_reader(self) -> None:
        self.assertEqual(classify_topic('海滩旅行vlog')[0], '旅行')
        self.assertEqual(classify_topic('股票基金投资入门')[0], '财经')
        self.assertEqual(classify_topic('想成为你的小猫 #猫咪日常 #萌宠')[0], '萌宠动物')
        self.assertEqual(classify_topic('撒哈拉沙漠环游世界')[0], '旅行')
        self.assertEqual(classify_topic('完全没有命中词')[0], '其他')

    def test_visible_tag_extraction_preserves_order_and_uniqueness(self) -> None:
        self.assertEqual(extract_tags('秋天 #旅行 #大兴安岭 #旅行'), ['旅行', '大兴安岭'])
        self.assertEqual(extract_title('每日小习惯成就流利英语\n#英语学习 #英语口语'),
                         '每日小习惯成就流利英语')
        self.assertEqual(extract_caption_text('标题 #标签\n第二行文案'), '标题\n第二行文案')
        self.assertEqual(extract_title('#逆水寒手游 #年上'), '#逆水寒手游 #年上')
        self.assertEqual(extract_caption_text('#技巧\n如何开启手机双击亮屏？'),
                         '如何开启手机双击亮屏？')

    def test_lock_rejects_second_writer(self) -> None:
        with experiment_lock(self.root):
            with self.assertRaises(RuntimeError):
                with experiment_lock(self.root):
                    pass

    def test_duplicate_write_is_ignored_but_conflict_is_rejected(self) -> None:
        a, p = self.accounts[0], self.plans[0]
        self.store.ensure_session(a, p)
        adapter = MockAdapter(); adapter.open_session(a, p.session_id)
        raw = adapter.read_current()
        record = FeedCollector().normalize(raw, a, self.cfg, p, 'unit', 1, True)
        self.assertTrue(self.store.save(raw, record))
        self.assertFalse(self.store.save(raw, record))
        with self.assertRaises(ValueError):
            self.store.save(raw, replace(record, content_id='CONFLICT'))


if __name__ == '__main__':
    unittest.main()
