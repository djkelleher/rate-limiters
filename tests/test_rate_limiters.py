import asyncio
from random import randint
from time import time

import pytest
from rate_limiters.rate_limiters import RateLimiter

pytestmark = pytest.mark.asyncio


async def get_times_slept(rate_limiter, n_sleeps: int = 10):
    async def do_sleep() -> float:
        """perform sleep and return the amount of time that was slept."""
        start = time()
        await rate_limiter.maybe_sleep()
        return time() - start

    times = await asyncio.gather(
        *[asyncio.create_task(do_sleep()) for _ in range(n_sleeps)]
    )

    # on first loop there should be no sleep.
    assert times.pop(0) < 0.001

    sleep_times = [
        (times[next_idx] - t) for next_idx, t in enumerate(times[:-1], start=1)
    ]

    return sleep_times


async def test_pause():
    rate_limiter = RateLimiter.from_uniform_rate(
        n_requests=randint(200, 300), seconds=randint(1, 2)
    )
    rate_limiter.pause(2)
    before = time()
    await rate_limiter.maybe_sleep()
    after = time()
    assert after - before > 1.95


async def test_sleep():
    rate_limiter = RateLimiter.from_uniform_rate(
        n_requests=randint(200, 300), seconds=randint(1, 2)
    )
    times_slept = await get_times_slept(rate_limiter)
    assert all((t - rate_limiter.rate.sleep_seconds) < 0.008 for t in times_slept)
