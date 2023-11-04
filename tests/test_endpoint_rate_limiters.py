import asyncio
import re
from random import randint
from time import time
from uuid import uuid4

import pytest
from rate_limiters.rate_limiters import (EndpointRateLimiter, RateLimiter,
                                         RatesController)
from rate_limiters.rates import ConstantRate

pytestmark = pytest.mark.asyncio

ALLOWED_DEVIATION = 3e-3


async def get_sleep_times(
    rate_limiter, url, target_endpoint_id=None, n_sleeps: int = 4
):
    async def do_sleep() -> float:
        await rate_limiter.maybe_sleep(url, target_endpoint_id)
        return time()

    start = time()

    times = await asyncio.gather(
        *[asyncio.create_task(do_sleep()) for _ in range(n_sleeps)]
    )

    # on first loop there should be no sleep.
    assert times.pop(0) - start == pytest.approx(0, abs=ALLOWED_DEVIATION)

    sleep_times = [
        (times[next_idx] - t) for next_idx, t in enumerate(times[:-1], start=1)
    ]

    return sleep_times


async def test_endpoint_substring():
    rate = ConstantRate(n_requests=randint(10, 20), seconds=randint(1, 2))
    ep_rate_limiter = RatesController.from_endpoint_rate_limiter(
        rate=rate, match_pattern="www.google.com"
    )
    times_slept = await get_sleep_times(
        ep_rate_limiter, "https://www.google.com/some/crap"
    )
    assert all(
        t == pytest.approx(rate.sleep_seconds, abs=ALLOWED_DEVIATION)
        for t in times_slept
    )


async def test_regex_target():
    rate = ConstantRate(n_requests=randint(10, 20), seconds=randint(1, 2))
    ep_rate_limiter = RatesController.from_endpoint_rate_limiter(
        rate=rate, match_pattern=re.compile(r"www\.test\.com\/api_v[1-2]\/")
    )
    times_slept = await get_sleep_times(
        ep_rate_limiter, "https://www.test.com/api_v1/stuff"
    )
    assert all((t - rate.sleep_seconds) < 0.008 for t in times_slept)
    # should only sleep for api_v1 and api_v2
    times_slept = await get_sleep_times(
        ep_rate_limiter, "https://www.test.com/api_v3/stuff"
    )
    assert all(t == pytest.approx(0, abs=ALLOWED_DEVIATION) for t in times_slept)


async def test_target_endpoint_id():
    rate = ConstantRate(n_requests=randint(10, 20), seconds=randint(1, 2))
    ep_rate_limiter = RatesController.from_endpoint_rate_limiter(
        rate=rate,
        match_pattern="https://api.tdameritrade.com/v1/marketdata/chains",
        endpoint_id="TSLA",
    )
    # check that it only sleep for target_endpoint_id 'TSLA'
    times_slept = await get_sleep_times(
        ep_rate_limiter,
        "https://api.tdameritrade.com/v1/marketdata/chains",
        "TSLA",
    )
    assert pytest.approx(times_slept, rate.sleep_seconds, abs=1e-3)
    # assert all((t - rate.sleep_seconds) < 0.008 for t in times_slept)
    times_slept = await get_sleep_times(
        ep_rate_limiter,
        "https://api.tdameritrade.com/v1/marketdata/chains",
        "SPY",
    )
    assert all(t == pytest.approx(0, abs=ALLOWED_DEVIATION) for t in times_slept)


async def test_default_limit():
    rate = ConstantRate(n_requests=randint(10, 20), seconds=randint(1, 2))
    ep_rate_limiter = RatesController(default_limit=rate)
    all_times_slept = []
    for _ in range(2):
        times_slept = await get_sleep_times(ep_rate_limiter, str(uuid4()))
        all_times_slept += times_slept

    assert all(
        t == pytest.approx(rate.sleep_seconds, abs=ALLOWED_DEVIATION)
        for t in all_times_slept
    )


async def test_sleep_all_matched():
    endpoint_rate = ConstantRate(n_requests=10, seconds=1)
    endpoint_id_rate = ConstantRate(n_requests=5, seconds=1)
    ep_rate_limiter = RatesController(
        rate_limits=[
            EndpointRateLimiter(
                rate_limiter=RateLimiter(rate=endpoint_rate),
                match_pattern="https://api.tdameritrade.com/v1/marketdata/chains",
            ),
            EndpointRateLimiter(
                rate_limiter=RateLimiter(rate=endpoint_id_rate),
                match_pattern="https://api.tdameritrade.com/v1/marketdata/chains",
                endpoint_id="TSLA",
            ),
        ]
    )
    # should sleep longer of the two matched.
    all_times_slept = await get_sleep_times(
        ep_rate_limiter,
        "https://api.tdameritrade.com/v1/marketdata/chains",
        "TSLA",
    )
    assert all(
        t == pytest.approx(endpoint_id_rate.sleep_seconds, abs=ALLOWED_DEVIATION)
        for t in all_times_slept
    )


async def test_multi_endpoint_id():
    domain_rate = ConstantRate(n_requests=100, seconds=1)
    default_rate = ConstantRate(n_requests=10, seconds=1)
    rate_limiter = RatesController(
        rate_limits=EndpointRateLimiter(
            rate_limiter=RateLimiter(domain_rate),
            match_pattern="https://api.tdameritrade.com",
        ),
        default_limit=default_rate,
    )

    async def do_sleep(endpoint_id) -> float:
        await rate_limiter.maybe_sleep(
            "https://api.tdameritrade.com/v1/marketdata/chains", endpoint_id
        )
        return time()

    endpoint_ids = [str(uuid4()) for _ in range(5)]

    start1 = time()

    times1 = await asyncio.gather(
        *[asyncio.create_task(do_sleep(e)) for e in endpoint_ids]
    )

    start2 = time()
    await asyncio.gather(*[asyncio.create_task(do_sleep(e)) for e in endpoint_ids])
    finish2 = time()

    # on first loop there should be no sleep.
    assert times1.pop(0) - start1 == pytest.approx(0, abs=ALLOWED_DEVIATION)

    times_slept1 = [
        (times1[next_idx] - t) for next_idx, t in enumerate(times1[:-1], start=1)
    ]

    # on first loop default limits should be created for each endpoint ID, but the endpoint id-specific should not sleep because this is the first time seeing it.
    # only domain_limit limit should be applied on first loop.
    assert all(
        t == pytest.approx(domain_rate.sleep_seconds, abs=ALLOWED_DEVIATION)
        for t in times_slept1
    )

    # on second loop, both limits should be applied, but the faster limit should not ever add additional sleep time.
    # endpoint-specific rates should be applied simultaneously for unique endpoints.
    assert finish2 - start2 == pytest.approx(
        default_rate.sleep_seconds, abs=ALLOWED_DEVIATION
    )
