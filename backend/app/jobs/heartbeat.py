"""Background asynchronous heartbeat manager for maintaining worker execution leases."""

import asyncio
import contextlib
import logging
from collections.abc import Callable

from app.jobs.lease import LeaseManagerProtocol
from app.observability.factory import get_metrics

logger = logging.getLogger("researchmind.worker.heartbeat")


class WorkerHeartbeat:
    """Manages an asynchronous background task that periodically renews a worker lease."""

    def __init__(
        self,
        lease_manager: LeaseManagerProtocol,
        run_id: str,
        worker_id: str,
        lease_id: str,
        interval_seconds: float = 10.0,
        lease_duration_seconds: float = 30.0,
        on_lease_lost: Callable[[], None] | None = None,
    ) -> None:
        self.lease_manager = lease_manager
        self.run_id = run_id
        self.worker_id = worker_id
        self.lease_id = lease_id
        self.interval_seconds = max(0.01, interval_seconds)
        self.lease_duration_seconds = max(0.05, lease_duration_seconds)
        self.on_lease_lost = on_lease_lost

        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._is_active = False

    @property
    def is_running(self) -> bool:
        """Return True if background heartbeat loop is currently active."""
        return self._is_active and self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start the background heartbeat renewal loop."""
        if self.is_running:
            return
        self._stop_event.clear()
        self._is_active = True
        self._task = asyncio.create_task(
            self._run_heartbeat_loop(),
            name=f"heartbeat-{self.run_id}-{self.lease_id[:8]}",
        )
        logger.debug(
            "Started worker heartbeat for run '%s' (lease: %s, interval: %.1fs)",
            self.run_id,
            self.lease_id,
            self.interval_seconds,
        )

    async def stop(self, timeout: float = 5.0) -> None:
        """Gracefully stop the background heartbeat loop."""
        if not self._is_active:
            return
        self._is_active = False
        self._stop_event.set()

        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self._task, timeout=timeout)

        logger.debug(
            "Stopped worker heartbeat for run '%s' (lease: %s)",
            self.run_id,
            self.lease_id,
        )

    async def _run_heartbeat_loop(self) -> None:
        """Periodic lease renewal loop."""
        metrics = get_metrics()
        while self._is_active and not self._stop_event.is_set():
            try:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.interval_seconds,
                    )
                    # If stop_event was set during wait, exit loop
                    break
                except TimeoutError:
                    pass

                if not self._is_active or self._stop_event.is_set():
                    break

                # Attempt lease renewal
                renewed = await self.lease_manager.renew_lease(
                    run_id=self.run_id,
                    worker_id=self.worker_id,
                    lease_id=self.lease_id,
                    duration_seconds=self.lease_duration_seconds,
                )

                if renewed is None:
                    logger.warning(
                        "Worker lease '%s' for run '%s' was lost or revoked. Halting heartbeat.",
                        self.lease_id,
                        self.run_id,
                    )
                    metrics.increment_counter(
                        "worker.lease.expired",
                        attributes={"run_id": self.run_id, "worker_id": self.worker_id},
                    )
                    self._is_active = False
                    if self.on_lease_lost is not None:
                        try:
                            self.on_lease_lost()
                        except Exception as cb_err:
                            logger.error("Error in on_lease_lost callback: %s", cb_err)
                    break

                metrics.increment_counter(
                    "worker.lease.renewed",
                    attributes={"run_id": self.run_id, "worker_id": self.worker_id},
                )
                logger.debug(
                    "Renewed worker lease '%s' for run '%s' (expires: %s)",
                    self.lease_id,
                    self.run_id,
                    renewed.lease_expires_at.isoformat(),
                )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(
                    "Transient error during heartbeat renewal for run '%s': %s",
                    self.run_id,
                    e,
                )


__all__ = ["WorkerHeartbeat"]
