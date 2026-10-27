"""
Global rate limiter for Discord message edits to prevent HTTP 429 rate limits.
"""

import asyncio
import time
import logging
from config import RATE_LIMIT_MIN_INTERVAL, RATE_LIMIT_MAX_BURST

logger = logging.getLogger("crypto_tool.rate_limiter")


class RateLimiter:
    """Manages burst and per-message intervals for Discord message updates."""

    def __init__(self, min_interval: float = RATE_LIMIT_MIN_INTERVAL, max_burst: int = RATE_LIMIT_MAX_BURST):
        self.last_edit_times = {}  # message_id -> last_edit_timestamp
        self.min_interval = min_interval
        self.max_burst = max_burst
        self._lock = asyncio.Lock()

    async def acquire(self, message_id: int) -> None:
        """Acquire permission to edit a message, awaiting delays if necessary."""
        async with self._lock:
            current_time = time.time()

            # Global burst limit check (max edits per 5 seconds)
            recent_edits = [t for t in self.last_edit_times.values() if current_time - t < 5.0]
            if len(recent_edits) >= self.max_burst:
                oldest_edit = min(recent_edits)
                wait_time = 5.0 - (current_time - oldest_edit)
                if wait_time > 0:
                    logger.debug(f"Rate limiter burst wait: {wait_time:.1f}s")
                    await asyncio.sleep(wait_time)
                    current_time = time.time()

            # Per-message minimum interval check
            if message_id in self.last_edit_times:
                time_since_last = current_time - self.last_edit_times[message_id]
                if time_since_last < self.min_interval:
                    wait_time = self.min_interval - time_since_last
                    logger.debug(f"Rate limiter message interval wait: {wait_time:.1f}s")
                    await asyncio.sleep(wait_time)

            # Record edit timestamp
            self.last_edit_times[message_id] = time.time()

            # Prune records older than 10 minutes
            cutoff = time.time() - 600
            self.last_edit_times = {mid: t for mid, t in self.last_edit_times.items() if t > cutoff}


# Global shared instance
rate_limiter = RateLimiter()
