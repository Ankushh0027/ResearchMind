"""Production CLI and entrypoint for standalone asynchronous research job worker."""

import asyncio
import contextlib
import logging
import signal

from app.config import get_settings
from app.jobs.factory import create_job_consumer
from app.jobs.protocols import (
    JobConsumerProtocol,
)
from app.jobs.worker import ResearchJobWorker
from app.orchestration.router import create_default_worker_router
from app.persistence.factory import (
    create_checkpoint_repository,
    create_run_repository,
)
from app.storage.factory import create_artifact_storage

logger = logging.getLogger("researchmind.worker")


class StandaloneWorkerRunner:
    """Coordinates lifecycle of a standalone background job worker process."""

    def __init__(
        self,
        consumer: JobConsumerProtocol | None = None,
        shutdown_timeout: float = 30.0,
    ) -> None:
        self.settings = get_settings()
        self.shutdown_timeout = shutdown_timeout
        self._stop_event = asyncio.Event()

        self._consumer: JobConsumerProtocol
        if consumer is None:
            self._run_repo = create_run_repository(self.settings)
            self._checkpoint_repo = create_checkpoint_repository(self.settings)
            self._artifact_storage = create_artifact_storage(self.settings)
            self._worker = ResearchJobWorker(
                router=create_default_worker_router(),
                run_repo=self._run_repo,
                checkpoint_repo=self._checkpoint_repo,
                artifact_storage=self._artifact_storage,
                max_concurrency=self.settings.max_orchestration_concurrency,
            )
            self._consumer = create_job_consumer(
                handler=self._worker,
                settings=self.settings,
            )
        else:
            self._consumer = consumer

    async def run(self) -> None:
        """Start consumer and wait for termination signal."""
        logger.info(
            "Starting ResearchMind Standalone Job Worker (concurrency: %d)...",
            self.settings.worker_concurrency,
        )
        await self._consumer.start()

        # Wait until stop event is signaled
        await self._stop_event.wait()

        logger.info("Stopping ResearchMind Standalone Job Worker gracefully...")
        try:
            await asyncio.wait_for(self._consumer.stop(), timeout=self.shutdown_timeout)
        except TimeoutError:
            logger.warning(
                "Worker stop timed out after %.1f seconds", self.shutdown_timeout
            )

    def signal_stop(self) -> None:
        """Signal the worker to stop processing and exit."""
        self._stop_event.set()


async def _async_main() -> None:
    runner = StandaloneWorkerRunner()
    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        runner.signal_stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _handle_signal)

    await runner.run()


def main() -> None:
    """Entrypoint for standalone worker process."""
    logging.basicConfig(level=logging.INFO)
    with contextlib.suppress(KeyboardInterrupt, SystemExit):
        asyncio.run(_async_main())


if __name__ == "__main__":
    main()
