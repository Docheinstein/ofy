import asyncio

from ofy.ratelimit import RateLimiter


class FakeClock:
    def __init__(self):
        self.t = 100.0
        self.sleeps = []

    def __call__(self):
        return self.t

    async def sleep(self, d):
        self.sleeps.append(d)
        self.t += d


async def test_first_call_does_not_wait():
    c = FakeClock()
    rl = RateLimiter(1.0, clock=c, sleep=c.sleep)
    await rl.acquire()
    assert c.sleeps == []


async def test_spacing_between_calls():
    c = FakeClock()
    rl = RateLimiter(1.0, clock=c, sleep=c.sleep)
    starts = []
    for _ in range(5):
        await rl.acquire()
        starts.append(c.t)
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert all(abs(g - 1.0) < 1e-9 for g in gaps)


async def test_no_wait_if_interval_already_elapsed():
    c = FakeClock()
    rl = RateLimiter(1.0, clock=c, sleep=c.sleep)
    await rl.acquire()
    c.t += 5
    await rl.acquire()
    assert c.sleeps == []


async def test_concurrent_callers_are_serialized():
    c = FakeClock()
    rl = RateLimiter(1.0, clock=c, sleep=c.sleep)
    starts = []

    async def call():
        async with rl:
            starts.append(c.t)

    await asyncio.gather(*(call() for _ in range(4)))
    starts.sort()
    assert [round(b - a, 6) for a, b in zip(starts, starts[1:])] == [1.0, 1.0, 1.0]


async def test_pause_holds_back_the_next_call():
    c = FakeClock()
    rl = RateLimiter(1.0, clock=c, sleep=c.sleep)
    await rl.acquire()
    rl.pause(5.0)
    await rl.acquire()
    assert c.sleeps == [5.0]


async def test_real_clock_never_exceeds_rate():
    import time

    rl = RateLimiter(0.05)
    times = []
    for _ in range(4):
        await rl.acquire()
        times.append(time.monotonic())
    assert min(b - a for a, b in zip(times, times[1:])) >= 0.049
