import asyncio
import os
from random import randint
from time import time

import pytest
import redis
from rate_limiters.distributed_rate_limiter import DistTargetRateLimiters
from rate_limiters.rates import HostRates, RateLimit, VariableRate

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def empty_redis_db():
    r = redis.from_url(os.environ["REDIS_URL"])
    r.flushdb()
    r.close()


async def get_times_slept(rate_limiter, url, n_requests: int = 5):
    sleep_times = await asyncio.gather(
        *[asyncio.create_task(rate_limiter.maybe_sleep(url)) for _ in range(n_requests)]
    )
    # on first loop there should be no sleep.
    assert sleep_times.pop(0) == 0.0

    return sleep_times


async def test_pause():
    rate_limiter = DistTargetRateLimiters.from_uniform_rate(n_requests=1, seconds=1)
    url = "http://www.google.com"
    rate_limiter.pause(url, 2)
    before = time()
    await rate_limiter.maybe_sleep(url)
    after = time()
    assert after - before > 1.95


async def test_host_url_rates_fixed():
    rate_limit = RateLimit(n_requests=randint(2, 10), seconds=randint(2, 3))
    rl = DistTargetRateLimiters(
        host_rates=HostRates(host="test.com", url_rates={"test.com/api": rate_limit})
    )
    times_slept = await get_times_slept(rl, "http://www.test.com/api/some/path")
    assert all((t - rate_limit.rate) < 0.008 for t in times_slept)


async def test_host_url_rates_variable():
    rate_limit = VariableRate(
        min_n_requests=randint(2, 10),
        max_n_requests=randint(11, 20),
        seconds=randint(2, 3),
    )
    rl = DistTargetRateLimiters(
        host_rates=HostRates(
            host="test.com",
            url_rates={
                "test.com/api": rate_limit,
            },
        )
    )
    times_slept = await get_times_slept(rl, "http://www.test.com/api/some/path")
    # time between all requests after the first should be greater than min and less than max.
    assert all(
        t <= rate_limit._min_rate + 0.008 and t >= rate_limit._max_rate
        for t in times_slept
    )


async def test_host_pattern_rates_fixed():
    rate_limit = RateLimit(n_requests=randint(2, 10), seconds=randint(2, 3))
    rl = DistTargetRateLimiters(
        host_rates=HostRates(
            host="test.com", pattern_rates={r"\/api_v[1-2]\/": rate_limit}
        )
    )
    times_slept = await get_times_slept(rl, "http://www.test.com/api_v2/some/path")
    assert all((t - rate_limit.rate) < 0.008 for t in times_slept)


async def test_host_pattern_rates_variable():
    rate_limit = VariableRate(
        min_n_requests=randint(2, 10),
        max_n_requests=randint(11, 20),
        seconds=randint(2, 3),
    )
    rl = DistTargetRateLimiters(
        host_rates=HostRates(
            host="test.com", pattern_rates={r"\/api_v[1-2]\/": rate_limit}
        )
    )
    times_slept = await get_times_slept(rl, "http://www.test.com/api_v2/some/path")
    # time between all requests after the first should be greater than min and less than max.
    assert all(
        t <= rate_limit._min_rate + 0.008 and t >= rate_limit._max_rate
        for t in times_slept
    )


async def test_host_default_rate_fixed():
    rate_limit = RateLimit(n_requests=randint(2, 10), seconds=randint(2, 3))
    rl = DistTargetRateLimiters(
        host_rates=HostRates(host="test.com", default_rate=rate_limit)
    )
    times_slept = await get_times_slept(rl, "http://www.test.com/api_v2/some/path")
    assert all((t - rate_limit.rate) < 0.008 for t in times_slept)


async def test_host_default_rate_variable():
    rate_limit = VariableRate(
        min_n_requests=randint(2, 10),
        max_n_requests=randint(11, 20),
        seconds=randint(2, 3),
    )
    rl = DistTargetRateLimiters(
        host_rates=HostRates(host="test.com", default_rate=rate_limit)
    )
    times_slept = await get_times_slept(rl, "http://www.test.com/api_v2/some/path")
    # time between all requests after the first should be greater than min and less than max.
    assert all(
        t <= rate_limit._min_rate + 0.008 and t >= rate_limit._max_rate
        for t in times_slept
    )


async def test_rate_limiter_default_rate():
    rate_limit = RateLimit(n_requests=randint(2, 10), seconds=randint(2, 3))
    rl = DistTargetRateLimiters(default_rate_limit=rate_limit)
    times_slept = await get_times_slept(rl, "http://www.adomain.com/some/path")
    times_slept.extend(await get_times_slept(rl, "http://www.anotherone.com/some/path"))
    assert all((t - rate_limit.rate) < 0.008 for t in times_slept)


async def test_rate_limiter_rate_variable():
    rate_limit = VariableRate(
        min_n_requests=randint(2, 10),
        max_n_requests=randint(11, 20),
        seconds=randint(2, 3),
    )
    rl = DistTargetRateLimiters(default_rate_limit=rate_limit)
    times_slept = await get_times_slept(rl, "http://www.adomain.com/some/path")
    times_slept.extend(await get_times_slept(rl, "http://www.anotherone.com/some/path"))
    # time between all requests after the first should be greater than min and less than max.
    assert all(
        t <= rate_limit._min_rate + 0.008 and t >= rate_limit._max_rate
        for t in times_slept
    )
