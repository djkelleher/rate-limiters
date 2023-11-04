import os
import signal
from socket import gethostname
from time import sleep, time

import redis

from .utils import ScopedMap


class DistTargetRateLimiters:
    def __init__(
        self,
        redis_url: str = os.getenv("REDIS_URL", "redis://localhost"),
        limit_by_worker_hostname: bool = True,
        **kwargs,
    ):
        """Distributed rate limiter that determines appropriate sleep times.

        Args:
            redis_url (str): Address of Redis server.
            limit_by_worker_hostname (bool): Apply limits on a per-worker hostname basis. i.e. Two worker hosts will be able to make twice and many requests as a single worker.
        """
        super().__init__(**kwargs)
        self._keyspace_hostname = gethostname() if limit_by_worker_hostname else ""
        self._redis = redis.from_url(redis_url, decode_responses=True)
        self._last_request = ScopedMap()
        for s in (signal.SIGINT, signal.SIGTERM):
            signal.signal(s, self.sig_catch)

    async def maybe_sleep(self, url: str) -> float:
        host = self._host(url)
        if _pause_end := self._redis.get(f"pause::{self._keyspace_hostname}::{host}"):
            # sleep until pause period is over.
            sleep_t = float(_pause_end) - time()
            sleep(sleep_t)
        sleep_time = 0.0
        # check if a specific rate limit has been assigned to this host.
        if (rates := self._host_rates.get(host)) is None:
            if self.default_limit is None:
                # host does not have an assigned rate limit and there is no default. no need to sleep.
                return sleep_time
            rate = self.default_limit.rate
        else:
            rate = rates.rate(url)
        if rate:
            with self._last_request:
                # key to a one-member list. list is used because we can't block waiting for normal key.
                self._last_request.key = f"tlr::{self._keyspace_hostname}::{host}"
                if not self._redis.exists(self._last_request.key):
                    # set new time last request so it can be used by the next task waiting on brpop.
                    self._redis.lpush(self._last_request.key, time())
                    return sleep_time
                # blocks so only one tasks can create a sleep time based on the current time_last_request.
                _, self._last_request.value = self._redis.blpop(self._last_request.key)
                if (
                    sleep_time := rate - (time() - float(self._last_request.value))
                ) > 0:
                    # sleep_time = s/req - time since last request.
                    sleep(sleep_time)
                # set new time last request so it can be used by the next task waiting on brpop.
                self._redis.lpush(self._last_request.key, time())
        return sleep_time

    def pause(self, host: str, duration_seconds: int) -> None:
        """Force `host` to pause for `duration_seconds` seconds.

        Args:
            host (str): The host that should be paused.
            duration_seconds (int): Number of seconds to pause for.
        """
        pause_end = time() + duration_seconds
        self._redis.set(
            f"pause::{self._keyspace_hostname}::{self._host(host)}", pause_end
        )

    def sig_catch(self, signum, frame):
        if self._last_request.is_set():
            self._redis.lpush(self._last_request.key, self._last_request.value)
