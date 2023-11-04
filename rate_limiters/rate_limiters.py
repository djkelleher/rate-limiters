import asyncio
import re
from asyncio import Lock
from collections import defaultdict
from dataclasses import dataclass
from time import time
from typing import List, Optional, Tuple, Union
from urllib.parse import urlsplit

from ezloggers import get_logger

from .rates import ConstantRate, VariableRate


class RateLimiter:
    def __init__(self, rate: Union[ConstantRate, VariableRate], _manual_unlock=False):
        """A basic rate limiter that applies a constant or variable rate.

        Args:
            rate: Union[ConstantRate, VariableRate]: The rate limit that should be applied.
        """
        self.rate = rate
        self._time_last_request = 0
        self._pause_end = None
        self._lock = Lock()
        self._manual_unlock = _manual_unlock

    @classmethod
    def from_uniform_rate(cls, n_requests: int, seconds: float):
        """Create a rate limiter with a constant rate limit."""
        return cls(rate=ConstantRate(n_requests, seconds))

    @classmethod
    def from_variable_rate(
        cls, min_n_requests: float, max_n_requests: float, seconds: float
    ):
        """Create a rate limiter with a variable rate limit."""
        return cls(rate=VariableRate(min_n_requests, max_n_requests, seconds))

    async def maybe_sleep(self):
        """ "If we've exceeded the allowed rate limit, sleep until were back in the allowed rate."""
        if self._pause_end:
            await asyncio.sleep(self._pause_end - time())
            self._pause_end = None
        # lock so only one tasks can create a sleep time based on the current time_last_request.
        await self._lock.acquire()
        if (
            sleep_time := self.rate.sleep_seconds - (time() - self._time_last_request)
        ) > 0:
            # sleep_time = s/req - time since last request.
            await asyncio.sleep(sleep_time)
        if not self._manual_unlock:
            self._unlock()

    def pause(self, duration_s: int):
        """Force all `maybe_sleep` calls to sleep for the next `duration_s` seconds."""
        self._pause_end = time() + duration_s

    @property
    def is_paused(self) -> bool:
        """Check if there is an active pause."""
        return self._pause_end and time() < self._pause_end

    def _unlock(self):
        # record time that request is being dispatched.
        self._time_last_request = time()
        self._lock.release()


@dataclass
class EndpointRateLimiter:
    rate_limiter: RateLimiter
    # endpoint (Union[str, re.Pattern]): URL, URL substring, or URL regex search pattern that the rate should be applied to. THIS MUST CONTAIN THE DOMAIN IN THE SUBSTRING OR PATTERN.
    match_pattern: Optional[Union[str, re.Pattern]] = None
    # an identifier of the endpoint that is not part of the endpoint URL. e.g. something that will be sent in the body of a request.
    endpoint_id: Optional[str] = None

    def __post_init__(self):
        if self.match_pattern is None:
            # match everything.
            self.match = lambda _: True
        elif isinstance(self.match_pattern, re.Pattern):
            # check for regex match.
            self.match = self.match_pattern.search
        else:
            # check for substring.
            self.match = lambda ep: ep.__contains__(self.match_pattern)


class RatesController:
    logger = get_logger("rates-controller")
    _domain_id_re = re.compile(r"^www\.")

    def __init__(
        self,
        rate_limits: Optional[List[EndpointRateLimiter]] = None,
        default_limit: Optional[Union[ConstantRate, VariableRate]] = None,
    ):
        """Manage and apply a set of rate limiters.

        Args:
            rate_limits (Optional[List[RateLimiter]]): Rate limits for specific endpoints. Matches are checked left to right, so limits with more specific endpoint substrings/patterns should be to the left or more the general ones.
            default_limit (Optional[Union[ConstantRate, VariableRate]], optional): Rate limit to use for all URLs that don't match anything in `rate_limits`. Defaults to None.
        """
        if isinstance(rate_limits, EndpointRateLimiter):
            rate_limits = [rate_limits]

        self.default_limit = default_limit

        def get_domain_id(l):
            if not (
                domain_id := self._get_domain_id(
                    l.match_pattern.pattern
                    if isinstance(l.match_pattern, re.Pattern)
                    else l.match_pattern,
                )
            ):
                raise ValueError(
                    f"Endpoint does not contain a domain: {l.match_pattern}"
                )
            return domain_id

        # map the domain to all of the domains's endpoints so we can do fast lookup by domain and check only the applicable endpoint rate limits.
        # domains can have multiple patterns/rates, so use a list.
        self._endpoint_rate_limits = defaultdict(list)
        if rate_limits is not None:
            for l in rate_limits:
                l.rate_limiter._manual_unlock = True

            domain_rate_limits = [l for l in rate_limits if not l.endpoint_id]
            for l in domain_rate_limits:
                key = get_domain_id(l)
                self._endpoint_rate_limits[key].append(l)

            endpoint_rate_limits = [l for l in rate_limits if l.endpoint_id]
            for l in endpoint_rate_limits:
                domain_id = get_domain_id(l)
                key = (domain_id, l.endpoint_id)
                self._endpoint_rate_limits[key].append(l)
                if domain_id in self._endpoint_rate_limits:
                    self._endpoint_rate_limits[key].extend(
                        self._endpoint_rate_limits[domain_id]
                    )

            for limits in self._endpoint_rate_limits.values():
                # need to sort by rate (longest to shortest) for scheduling.
                limits.sort(
                    key=lambda x: x.rate_limiter.rate.max_sleep_seconds, reverse=True
                )

        elif default_limit is None:
            raise ValueError(
                "Either `rate_limits` or `default_limit` must be provided!"
            )

    @classmethod
    def from_endpoint_rate_limiter(
        cls,
        rate: Union[ConstantRate, VariableRate],
        match_pattern: Optional[Union[str, re.Pattern]],
        endpoint_id: Optional[str] = None,
    ):
        """Create a rate controller for a single endpoint."""
        return cls(
            rate_limits=EndpointRateLimiter(
                rate_limiter=RateLimiter(rate, _manual_unlock=True),
                match_pattern=match_pattern,
                endpoint_id=endpoint_id,
            )
        )

    @classmethod
    def from_rate(cls, rate: Union[ConstantRate, VariableRate]):
        """Apply the same rate limit to all endpoints."""
        return cls(default_limit=rate)

    async def maybe_sleep(self, url: str, endpoint_id: Optional[str] = None):
        """Find and apply all rate limiters applicable to this endpoint."""
        if not (domain_id := self._get_domain_id(url)):
            self.logger.warning(
                "Could not create domain ID key for %s. Will not sleep.", url
            )
            return

        key = (domain_id, endpoint_id) if endpoint_id else domain_id

        if not (rate_limits := self._endpoint_rate_limits[key]) and self.default_limit:
            # add default rate limiter.
            rate_limits.append(
                EndpointRateLimiter(
                    rate_limiter=RateLimiter(self.default_limit, _manual_unlock=True)
                )
            )
            # domain rate limits should be applied to domain/endpoint.
            if key != domain_id and domain_id in self._endpoint_rate_limits:
                rate_limits.extend(self._endpoint_rate_limits[domain_id])
                rate_limits.sort(
                    key=lambda x: x.rate_limiter.rate.max_sleep_seconds, reverse=True
                )

        rate_limits = [l.rate_limiter for l in rate_limits if l.match(url)]

        for l in rate_limits:
            await l.maybe_sleep()

        # unlock all rate limiters
        for l in rate_limits:
            l._unlock()

    def _get_domain_id(self, endpoint: str) -> Union[str, Tuple[str, str]]:
        split_endpoint = urlsplit(endpoint)
        if _domain_id := self._domain_id_re.sub(
            "", split_endpoint.netloc or split_endpoint.path
        ):
            return _domain_id
