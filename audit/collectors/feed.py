from ..models import Account, AuditError, ExperimentConfig, FeedRecord, RawObservation, SessionPlan


class FeedCollector:
    def normalize(self, raw: RawObservation, account: Account, cfg: ExperimentConfig,
                  plan: SessionPlan, run_id: str, position: int, synthetic: bool) -> FeedRecord:
        if not raw.exposure_token:
            raise AuditError("EXPOSURE_NOT_IDENTIFIED", "无法确认当前曝光，不允许继续翻页")
        m = raw.metadata
        failed = bool(m.get("parse_error")) or not m.get("content_id")
        # Only trusted shape conversions; never auto-classify missing finance as False.
        sponsor = m.get("sponsored")
        if type(sponsor) not in (bool, type(None)):
            sponsor = None
            failed = True
        def string(key: str) -> str | None:
            value = m.get(key)
            return str(value) if value is not None else None
        return FeedRecord(
            experiment_id=cfg.experiment_id, run_id=run_id, batch_id=account.batch_id,
            pair_id=account.pair_id, account_id=account.account_id, gender=account.gender,
            platform=account.platform, session_id=plan.session_id, timestamp=raw.captured_at,
            position=position, planned_start=plan.planned_start, protocol_version=cfg.protocol_version,
            exposure_token=raw.exposure_token, content_id=string("content_id"),
            creator_id=string("creator_id"), title_or_text=string("title_or_text"),
            content_type=string("content_type"), url_or_internal_id=string("url_or_internal_id"),
            sponsored=sponsor, raw_metadata=m, collection_status="EXTRACTION_FAILED" if failed else "OK",
            is_synthetic=synthetic, evidence_path=raw.evidence_path,
            error_code="CONTENT_EXTRACTION_FAILED" if failed else None,
            exposure_unit=string("exposure_unit"), view_id=string("view_id"),
            slot_index=m.get("slot_index"), visible_fraction=m.get("visible_fraction"))
