"""OpenAI text-embedding-3-small wrapper with client-side rate limiting.

Yields (Chunk, embedding) pairs from an input iterable of chunks. Batches
API calls at BATCH_SIZE chunks per request.

Rate-limit posture: OpenAI's 429s carry a Retry-After header the SDK
honors, but once a caller is saturating the TPM (tokens-per-minute)
ceiling continuously, SDK-side retries can't dig out — every retry
arrives into a still-full bucket and exhausts max_retries before the
window slides. Solution: throttle client-side with a sliding 60s window
so we stay UNDER the cap by design. Token count per batch is computed
with tiktoken before the request, so the throttle is exact rather than
estimated. max_retries=10 stays as a safety net for the occasional
network blip; it's no longer the primary rate-control mechanism.

Tuning note on BATCH_SIZE (=50): halved from the original 100 in commit
13c606e. Smaller per-batch token footprint gives the TPM throttle tighter
control and avoids the pathological case of a single oversized batch
bursting past the window cap.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Iterable, Iterator

import tiktoken
from openai import OpenAI

from .chunker import Chunk

MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
BATCH_SIZE = 50
DEFAULT_MAX_RETRIES = 10

# OpenAI's text-embedding-3-small TPM limit on Tier 1 is 1,000,000. We
# target 800,000 to leave ~20% headroom for token-count estimation drift
# and concurrent SDK retries burning additional budget.
TPM_CAP = 800_000
WINDOW_SECONDS = 60.0

_encoder = tiktoken.get_encoding("cl100k_base")

log = logging.getLogger(__name__)


class _TpmThrottle:
    """Sliding-window rate limiter for tokens/minute."""

    def __init__(self, cap: int = TPM_CAP, window: float = WINDOW_SECONDS) -> None:
        self.cap = cap
        self.window = window
        self.events: deque[tuple[float, int]] = deque()

    def wait_and_reserve(self, tokens: int) -> None:
        while True:
            now = time.monotonic()
            while self.events and self.events[0][0] < now - self.window:
                self.events.popleft()
            used = sum(n for _, n in self.events)
            if used + tokens <= self.cap:
                self.events.append((now, tokens))
                return
            # wait for the oldest event to fall out of the window
            oldest_ts = self.events[0][0]
            sleep_for = (oldest_ts + self.window) - now + 0.05
            log.info(
                "TPM throttle: used=%d + requested=%d > cap=%d; sleeping %.1fs",
                used,
                tokens,
                self.cap,
                sleep_for,
            )
            time.sleep(max(0.1, sleep_for))


def embed(chunks: Iterable[Chunk], client: OpenAI | None = None) -> Iterator[tuple[Chunk, list[float]]]:
    """Yield (chunk, embedding) pairs. Client defaults to OPENAI_API_KEY from env."""
    client = client or OpenAI(max_retries=DEFAULT_MAX_RETRIES)
    throttle = _TpmThrottle()
    batch: list[Chunk] = []
    batch_num = 0
    total = 0
    for chunk in chunks:
        batch.append(chunk)
        if len(batch) >= BATCH_SIZE:
            batch_num += 1
            total += len(batch)
            yield from _embed_batch(batch, client, throttle, batch_num, total)
            batch = []
    if batch:
        batch_num += 1
        total += len(batch)
        yield from _embed_batch(batch, client, throttle, batch_num, total, final=True)


def _embed_batch(
    batch: list[Chunk],
    client: OpenAI,
    throttle: _TpmThrottle,
    batch_num: int,
    total: int,
    *,
    final: bool = False,
) -> Iterator[tuple[Chunk, list[float]]]:
    batch_tokens = sum(len(_encoder.encode(c.text)) for c in batch)
    throttle.wait_and_reserve(batch_tokens)
    log.info(
        "batch %d%s: %d chunks, %d tokens (total %d)",
        batch_num,
        " (final)" if final else "",
        len(batch),
        batch_tokens,
        total,
    )
    response = client.embeddings.create(model=MODEL, input=[c.text for c in batch])
    for chunk, datum in zip(batch, response.data, strict=True):
        yield chunk, datum.embedding
