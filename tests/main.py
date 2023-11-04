import os

import pytest

default_args = ["-s", "-vvv", "--sw"]

files = [
    "test_rate_limiters.py",
    "test_endpoint_rate_limiters.py"
    # "test_distributed_rate_limiter.py",
]


def test_host_throttle():
    #os.chdir("/home/dan/host-throttle")
    for f in files:
        command = default_args + [f"tests/{f}"]
        pytest.main(command)


if __name__ == "__main__":
    test_host_throttle()
