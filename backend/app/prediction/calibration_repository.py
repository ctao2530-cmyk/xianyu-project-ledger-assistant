from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..database import Database
from ..models import (
    EstimateCalibrationRun,
    EstimateCalibrationSample,
    EstimateCalibrationSuggestion,
)


class CalibrationRepositoryError(RuntimeError):
    safe_message = "估算校准记录暂时无法读取"
    code = "calibration_repository_error"
    status_code = 503


class CalibrationNotFound(CalibrationRepositoryError):
    safe_message = "估算校准建议不存在"
    code = "calibration_not_found"
    status_code = 404


class CalibrationRevisionConflict(CalibrationRepositoryError):
    safe_message = "估算校准建议已经更新，请刷新后重试"
    code = "calibration_revision_conflict"
    status_code = 409


class CalibrationRequestConflict(CalibrationRepositoryError):
    safe_message = "该请求编号已用于不同的估算校准操作"
    code = "calibration_request_conflict"
    status_code = 409


class CalibrationDecisionInvalid(CalibrationRepositoryError):
    safe_message = "当前校准建议不能执行该决定"
    code = "calibration_decision_invalid"
    status_code = 422


class EstimateCalibrationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def latest_run(self) -> EstimateCalibrationRun | None:
        try:
            with self.database.session() as session:
                return session.scalar(
                    select(EstimateCalibrationRun)
                    .order_by(
                        EstimateCalibrationRun.cutoff_at.desc(),
                        EstimateCalibrationRun.created_at.desc(),
                    )
                    .limit(1)
                )
        except SQLAlchemyError as exc:
            raise CalibrationRepositoryError from exc

    def run_by_request(self, request_id: str) -> EstimateCalibrationRun | None:
        try:
            with self.database.session() as session:
                return session.scalar(
                    select(EstimateCalibrationRun).where(
                        EstimateCalibrationRun.request_id == request_id
                    )
                )
        except SQLAlchemyError as exc:
            raise CalibrationRepositoryError from exc

    def latest_suggestion(self, project_id: str) -> EstimateCalibrationSuggestion | None:
        try:
            with self.database.session() as session:
                return session.scalar(
                    select(EstimateCalibrationSuggestion)
                    .where(EstimateCalibrationSuggestion.project_id == project_id)
                    .order_by(EstimateCalibrationSuggestion.created_at.desc())
                    .limit(1)
                )
        except SQLAlchemyError as exc:
            raise CalibrationRepositoryError from exc

    @staticmethod
    def sample_by_hash(session, source_hash: str) -> EstimateCalibrationSample | None:
        return session.scalar(
            select(EstimateCalibrationSample).where(
                EstimateCalibrationSample.source_hash == source_hash
            )
        )

    @staticmethod
    def latest_project_sample(session, project_id: str) -> EstimateCalibrationSample | None:
        return session.scalar(
            select(EstimateCalibrationSample)
            .where(EstimateCalibrationSample.project_id == project_id)
            .order_by(
                EstimateCalibrationSample.cutoff_at.desc(),
                EstimateCalibrationSample.created_at.desc(),
            )
            .limit(1)
        )
