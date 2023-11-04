## Rate limiting for asynchronous web scraping

### Install
`pip install rate_limiters`

### Usage
```python
from rate_limiters import TargetRateLimiters, HostRates, VariableRate, RateLimit

rate_limiter = TargetRateLimiters(
    # Use a default rate of 1 request/second for all hosts not in `host_rates`.
    default_rate_limit=RateLimit(n_requests=1, seconds=1),
    host_rates=[
        # send between 1 and 3 requests per second to amazon.com.
        HostRates(
            host='amazon.com',
            default_rate=VariableRate(min_n_requests=1, max_n_requests=3, seconds=1)
        ),
        # send 2 requests per second to URLs with the substring 'ebay.com/search'.
        # send between 3 and 4 requests per 5 seconds to all URLs with the substring 'ebay.com/cart'.
        HostRates(
            host='ebay.com',
            url_rates={
                'ebay.com/search': RateLimit(n_requests=2, seconds=3),
                'ebay.com/cart': VariableRate(min_n_requests=3, max_n_requests=4, seconds=5),
            }
        ),
        # send 1 requests per second to all URLs matching the regular expression r'somedomain\.com\/api_v[1-2]'
        # send 10 requests per second to all URLs matching the regular expression r'somedomain\.com\/api_v[3-5]'
        HostRates(
            host='somedomain.com',
            pattern_rates={
                r'somedomain\.com\/api_v[1-2]': RateLimit(n_requests=1, seconds=1),
                r'somedomain\.com\/api_v[3-5]': RateLimit(n_requests=10, seconds=1),
            }
        ),
    ]
)


async def request(url):
    await rate_limiter.maybe_sleep(url)
    # request would be dispatched now..
    # response = await http_client.get(url)

# asynchronously dispatch a batch of requests.
# urls: List[str]
await asyncio.gather(
    *[asyncio.create_task(request(url)) for url in urls])
```