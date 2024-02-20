import abc
import threading
from collections import OrderedDict
from typing import Dict, Optional

from .core import Domain, Parser, PartialParseResult

__all__ = [
    "CachingParser",
    "Cache",
    "Clearing",
    "Locking",
    "LRU",
]


class Cache(abc.ABC):
    """Cache abstract protocol. The :class:`CachingParser` will look
    values up, merge what was returned (possibly nothing) with what it
    got from its actual parser, and *re-set the result*.

    A :class:`Cache` is responsible for its own replacement policy.
    """

    @abc.abstractmethod
    def __setitem__(self, key: str, value: PartialParseResult) -> None:
        """Adds or replace ``value`` to the cache at key ``key``."""
        ...

    @abc.abstractmethod
    def __getitem__(self, key: str) -> Optional[PartialParseResult]:
        """Returns a partial result for ``key`` if there is any."""
        ...


class Clearing(Cache):
    """A clearing cache, if the cache is full, just remove all the entries
    and re-fill from scratch.

    This can also be used as a cheap permanent cache by setting the
    ``maxsize`` to infinity (or at least some very large value),
    however this is probably a bad idea as it *will* lead to an
    ever-growing memory allocation, until every possible user agent
    string has been seen.

    Thread-safety: thread-safe, although concurrent insertion may
    cause over-clearing of the cache.

    """

    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self.cache: Dict[str, PartialParseResult] = {}

    def __getitem__(self, key: str) -> Optional[PartialParseResult]:
        return self.cache.get(key)

    def __setitem__(self, key: str, value: PartialParseResult) -> None:
        if key not in self.cache and len(self.cache) >= self.maxsize:
            self.cache.clear()

        self.cache[key] = value


class LRU(Cache):
    """Cache following a least-recently used replacement policy: when
    there is no more room in the cache, whichever entry was last seen
    the least recently is removed.

    Note that the cache size is adjusted after inserting the new
    entry, so the cache will temporarily contain ``maxsize + 1``
    items.

    Thread-safety: non-thread-safe, the upgrade of a key on hit fails
    if the key has already been removed, might also be possible for
    the capacity checking to become inconsistent or incorrect or
    incorrect on concurrent use e.g. if ``n`` threads try to set the
    same value (because they all got a cache miss and had to process
    the request) on a full cache of ``maxsize < n - 1``, they all set the
    value in the cache, check the cache size, and get a ``len() >
    maxsize``.

    This will lead to ``n`` calls to ``popitem``, which is more than
    the number of entries in the cache (``maxsize + 1``), and any
    excess call will trigger a ``KeyError``.

    """

    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self.cache: OrderedDict[str, PartialParseResult] = OrderedDict()

    def __getitem__(self, key: str) -> Optional[PartialParseResult]:
        e = self.cache.get(key)
        if e:
            self.cache.move_to_end(key)
        return e

    def __setitem__(self, key: str, value: PartialParseResult) -> None:
        self.cache[key] = value
        self.cache.move_to_end(key)
        while len(self.cache) > self.maxsize:
            self.cache.popitem(last=False)


class Locking(Cache):
    """Locking cache decorator. Takes a non-thread-safe cache and
    ensures retrieving and setting entries is protected by a mutex.

    """

    def __init__(self, cache: Cache):
        self.cache: Cache = cache
        self.lock = threading.Lock()

    def __getitem__(self, key: str) -> Optional[PartialParseResult]:
        with self.lock:
            return self.cache[key]

    def __setitem__(self, key: str, value: PartialParseResult) -> None:
        with self.lock:
            self.cache[key] = value


class CachingParser(Parser):
    """A wrapping parser which takes an underlying concrete :class:`Cache`
    for the actual caching and cache strategy.

    The :class:`CachingParser` only interacts with the :class:`Cache`
    and delegates to the wrapped parser in case of lookup failure.

    :class:`CachingParser` will set entries back in the cache when
    filling them up, it does not update results in place (and can't
    really, they're immutable).
    """

    def __init__(self, parser: Parser, cache: Cache):
        self.parser: Parser = parser
        self.cache: Cache = cache

    def __call__(self, ua: str, domains: Domain, /) -> PartialParseResult:
        entry = self.cache[ua]
        if entry:
            if domains in entry.domains:
                return entry

            domains &= ~entry.domains

        r = self.parser(ua, domains)
        if entry:
            r = PartialParseResult(
                string=ua,
                domains=entry.domains | r.domains,
                user_agent=entry.user_agent or r.user_agent,
                os=entry.os or r.os,
                device=entry.device or r.device,
            )
        self.cache[ua] = r
        return r
