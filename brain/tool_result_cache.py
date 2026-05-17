"""
Tool Result Cache: In-memory caching for read-only tool results.

Caches results of idempotent, read-only operations within a session to:
- Reduce redundant tool calls (e.g., reading the same file twice)
- Save LLM tokens by avoiding repeated context
- Improve response latency

Cache entries expire after TTL seconds or when write operations occur.
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """A cached tool result with metadata."""
    tool_name: str
    args: dict
    result: dict
    timestamp: float = field(default_factory=time.time)
    ttl_seconds: int = 300  # 5 minutes default
    hit_count: int = 0

    def is_expired(self) -> bool:
        return time.time() - self.timestamp > self.ttl_seconds

    def to_key(self) -> str:
        """Generate cache key from tool name and args."""
        normalized_args = json.dumps(self.args, sort_keys=True, default=str)
        key_string = f"{self.tool_name}:{normalized_args}"
        return hashlib.sha256(key_string.encode()).hexdigest()[:32]


class ToolResultCache:
    """
    Thread-safe in-memory cache for tool results.

    Usage::

        cache = ToolResultCache()
        
        # Before executing a read-only tool, check cache
        cached = cache.get("read_file", {"path": "/tmp/test.txt"})
        if cached:
            return cached  # Skip tool execution
        
        # After successful execution, store result
        cache.set("read_file", {"path": "/tmp/test.txt"}, result)

        # Invalidate cache when write operations occur
        cache.invalidate_pattern("read_file")  # Clear all read_file caches
        cache.invalidate_pattern("*", path="/tmp/test.txt")  # Clear caches for specific path
    """

    # Read-only tools that are safe to cache
    READ_ONLY_TOOLS = frozenset({
        "time_calendar",
    })

    # Tools that should invalidate related cache entries
    WRITE_TOOLS = frozenset({
        "execute_code",
    })

    def __init__(self, max_entries: int = 1000, default_ttl: int = 300):
        """
        Args:
            max_entries: Maximum number of cache entries before eviction
            default_ttl: Default time-to-live in seconds for cache entries
        """
        self._cache: dict[str, CacheEntry] = {}
        self._max_entries = max_entries
        self._default_ttl = default_ttl
        import threading as _threading
        self._lock = _threading.RLock()  # Eager init — lazy was a TOCTOU race

    def _get_lock(self):
        return self._lock  # Always initialized in __init__ — no lazy init needed

    def _make_key(self, tool_name: str, args: dict) -> str:
        """
        Generate a deterministic cache key from tool name and arguments.

        Args are sorted by key to ensure consistent hashing regardless of order.
        """
        normalized_args = json.dumps(args, sort_keys=True, default=str)
        key_string = f"{tool_name}:{normalized_args}"
        return hashlib.sha256(key_string.encode()).hexdigest()[:32]

    def get(self, tool_name: str, args: dict) -> Optional[dict]:
        """
        Retrieve cached result for a tool call.

        Args:
            tool_name: Name of the tool
            args: Tool arguments as dict

        Returns:
            Cached result dict if found and not expired, None otherwise
        """
        if tool_name not in self.READ_ONLY_TOOLS:
            return None

        key = self._make_key(tool_name, args)
        lock = self._get_lock()

        with lock:
            entry = self._cache.get(key)
            if entry is None:
                self._track_miss()
                return None

            if entry.is_expired():
                del self._cache[key]
                self._track_miss()
                logger.debug(f"cache: expired entry for {tool_name}")
                return None

            entry.hit_count += 1
            logger.debug(
                f"cache: HIT for {tool_name} (key={key[:8]}, hits={entry.hit_count})"
            )
            return dict(entry.result)

    def set(
        self,
        tool_name: str,
        args: dict,
        result: dict,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """
        Cache a tool result.

        Args:
            tool_name: Name of the tool
            args: Tool arguments
            result: Tool result dict (must be JSON-serializable)
            ttl_seconds: Override default TTL for this entry

        Returns:
            True if cached successfully, False if tool is not cacheable
        """
        if tool_name not in self.READ_ONLY_TOOLS:
            return False

        if not result.get("success"):
            # Don't cache failed results
            logger.debug(f"cache: skipping failed result for {tool_name}")
            return False

        key = self._make_key(tool_name, args)
        lock = self._get_lock()

        with lock:
            # Evict oldest entries if at capacity
            if len(self._cache) >= self._max_entries:
                self._evict_oldest()

            entry = CacheEntry(
                tool_name=tool_name,
                args=args,
                result=result,
                ttl_seconds=ttl_seconds or self._default_ttl,
            )
            self._cache[key] = entry
            logger.debug(f"cache: SET for {tool_name} (key={key[:8]}, ttl={entry.ttl_seconds}s)")
            return True

    def invalidate_tool(self, tool_name: str) -> int:
        """
        Invalidate all cache entries for a specific tool.

        Args:
            tool_name: Name of the tool to invalidate

        Returns:
            Number of entries invalidated
        """
        lock = self._get_lock()
        count = 0

        with lock:
            keys_to_delete = [
                k for k, v in self._cache.items()
                if v.tool_name == tool_name
            ]
            for key in keys_to_delete:
                del self._cache[key]
                count += 1

        if count > 0:
            logger.info(f"cache: invalidated {count} entries for {tool_name}")
        return count

    def invalidate_pattern(self, tool_name: Optional[str] = None, **arg_filters) -> int:
        """
        Invalidate cache entries matching criteria.

        Args:
            tool_name: Filter by tool name (or "*" for all tools)
            **arg_filters: Filter by specific argument values

        Returns:
            Number of entries invalidated
        """
        lock = self._get_lock()
        count = 0

        with lock:
            keys_to_delete = []
            for key, entry in self._cache.items():
                # Check tool name filter
                if tool_name and tool_name != "*":
                    if entry.tool_name != tool_name:
                        continue

                # Check argument filters (if any)
                if arg_filters:
                    match = all(
                        entry.args.get(k) == v
                        for k, v in arg_filters.items()
                    )
                    if not match:
                        continue

                keys_to_delete.append(key)

            for key in keys_to_delete:
                del self._cache[key]
                count += 1

        if count > 0:
            logger.info(
                f"cache: invalidated {count} entries "
                f"(tool={tool_name or '*'}, filters={arg_filters})"
            )
        return count

    def clear(self) -> int:
        """Clear all cache entries."""
        lock = self._get_lock()
        with lock:
            count = len(self._cache)
            self._cache.clear()
        logger.info(f"cache: cleared {count} entries")
        return count

    def stats(self) -> dict:
        """Return cache statistics."""
        total_misses = getattr(self, "_total_misses", 0)
        lock = self._get_lock()
        with lock:
            total_hits = sum(e.hit_count for e in self._cache.values())
            total_entries = len(self._cache)
            
            # Count expired entries
            expired = sum(1 for e in self._cache.values() if e.is_expired())

        total_requests = total_hits + total_misses
        return {
            "entries": total_entries,
            "total_hits": total_hits,
            "total_misses": total_misses,
            "expired_entries": expired,
            "max_entries": self._max_entries,
            "hit_rate": total_hits / total_requests if total_requests > 0 else 0.0,
        }

    def _track_miss(self):
        """Increment the miss counter (thread-safe)."""
        self._total_misses = getattr(self, "_total_misses", 0) + 1

    def _evict_oldest(self, count: int = 1) -> None:
        """Evict the oldest cache entries."""
        # Sort by timestamp and remove oldest
        sorted_entries = sorted(
            self._cache.items(),
            key=lambda x: x[1].timestamp
        )
        for key, _ in sorted_entries[:count]:
            del self._cache[key]
        logger.debug(f"cache: evicted {count} oldest entries")


# Global cache instance for use across modules
_global_cache: Optional[ToolResultCache] = None
_cache_lock = __import__("threading").Lock()


def get_cache() -> ToolResultCache:
    """Get or create the global tool result cache (thread-safe singleton)."""
    global _global_cache
    if _global_cache is None:
        with _cache_lock:
            if _global_cache is None:  # double-checked locking
                _global_cache = ToolResultCache()
    return _global_cache


def init_cache(max_entries: int = 1000, default_ttl: int = 300) -> ToolResultCache:
    """Initialize the global cache with custom settings."""
    global _global_cache
    _global_cache = ToolResultCache(max_entries=max_entries, default_ttl=default_ttl)
    logger.info(f"Tool result cache initialized (max={max_entries}, ttl={default_ttl}s)")
    return _global_cache
