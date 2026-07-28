from __future__ import annotations

import os
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from collections.abc import Callable

from agent.runtime.profiler import profile_dataset_version
from application.datasets.jobs import DatasetProfileJob, run_dataset_profile_job
from application.datasets.repository import DatasetRepository, RawFileStorage
from application.datasets.service import DatasetService


logger = logging.getLogger(__name__)
DEFAULT_MAX_WORKERS = 2


class InProcessDatasetJobDispatcher:
    """Dispatch dataset profiling jobs to a bounded thread pool."""

    def __init__(
        self,
        *,
        repository_factory: Callable[[], DatasetRepository],
        storage_factory: Callable[[], RawFileStorage],
        max_workers: int | None = None,
        profiler=profile_dataset_version,
    ) -> None:
        self._repository_factory = repository_factory
        self._storage_factory = storage_factory
        self._profiler = profiler
        self._max_workers = max_workers or int(
            os.getenv("DATASET_PROFILE_MAX_WORKERS", str(DEFAULT_MAX_WORKERS))
        )
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="dataset-profile",
        )
        self._futures: set[Future] = set()

    def dispatch_profile(self, version_id: str) -> None:
        job = DatasetProfileJob(version_id=version_id)
        future = self._executor.submit(self._run_job, job)
        self._futures.add(future)
        future.add_done_callback(self._futures.discard)

    def _run_job(self, job: DatasetProfileJob) -> None:
        started_at = time.perf_counter()
        logger.info("dataset_profile_started version_id=%s", job.version_id)
        try:
            repository = self._repository_factory()
            storage = self._storage_factory()
            version = run_dataset_profile_job(
                job,
                repository=repository,
                storage=storage,
                profiler=self._profiler,
            )
            if version is None:
                logger.warning("dataset_profile_skipped_missing version_id=%s", job.version_id)
                return

            duration_ms = int((time.perf_counter() - started_at) * 1000)
            if version.status == "ready":
                logger.info(
                    "dataset_profile_completed version_id=%s status=%s format=%s duration_ms=%s",
                    job.version_id,
                    version.status,
                    version.format,
                    duration_ms,
                )
            elif version.status == "invalid":
                issue_codes = ",".join(issue.code for issue in version.issues) or "none"
                logger.info(
                    "dataset_profile_failed version_id=%s status=%s issue_codes=%s duration_ms=%s",
                    job.version_id,
                    version.status,
                    issue_codes,
                    duration_ms,
                )
        except Exception:
            logger.exception("dataset_profile_failed version_id=%s", job.version_id)
            try:
                service = DatasetService(self._repository_factory(), self)
                service.fail_profile(
                    job.version_id,
                    code="profile_runtime_error",
                    message="Dataset profiling failed unexpectedly",
                )
            except Exception:
                logger.exception("dataset_profile_fail_marking_failed version_id=%s", job.version_id)
        finally:
            pass

    def shutdown(self, timeout: float = 5.0) -> None:
        pending = [future for future in self._futures if not future.done()]
        if pending:
            wait(pending, timeout=timeout)
        self._executor.shutdown(wait=True, cancel_futures=False)
