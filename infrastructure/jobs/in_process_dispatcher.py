from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from agent.runtime.profiler import profile_dataset_version
from application.datasets.jobs import DatasetProfileJob, run_dataset_profile_job
from application.datasets.repository import DatasetRepository, RawFileStorage


logger = logging.getLogger(__name__)


class InProcessDatasetJobDispatcher:
    """Dispatch dataset profiling jobs to lightweight daemon threads."""

    def __init__(
        self,
        *,
        repository_factory: Callable[[], DatasetRepository],
        storage_factory: Callable[[], RawFileStorage],
        profiler=profile_dataset_version,
    ) -> None:
        self._repository_factory = repository_factory
        self._storage_factory = storage_factory
        self._profiler = profiler
        self._threads: set[threading.Thread] = set()
        self._lock = threading.Lock()

    def dispatch_profile(self, version_id: str) -> None:
        job = DatasetProfileJob(version_id=version_id)
        thread = threading.Thread(
            target=self._run_job,
            args=(job,),
            name=f"dataset-profile-{version_id[:12]}",
            daemon=True,
        )
        with self._lock:
            self._threads.add(thread)
        thread.start()

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
        finally:
            current = threading.current_thread()
            with self._lock:
                self._threads.discard(current)

    def shutdown(self, timeout: float = 5.0) -> None:
        deadline = time.perf_counter() + timeout
        while True:
            with self._lock:
                threads = [thread for thread in self._threads if thread.is_alive()]
            if not threads:
                return

            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return

            for thread in threads:
                thread.join(min(0.1, remaining))
