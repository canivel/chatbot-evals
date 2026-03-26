"""Sampling strategies for selecting subsets of conversations.

When evaluation datasets are large, samplers allow you to select a
representative (or targeted) subset for faster iteration.

Every sampler implements the same interface::

    sampler = RandomSampler(n=100, seed=42)
    subset = sampler.sample(conversations)
"""

from __future__ import annotations

import hashlib
import random
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import structlog

from chatbot_evals.types import Conversation

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class BaseSampler(ABC):
    """Abstract base class for all sampling strategies."""

    @abstractmethod
    def sample(self, conversations: list[Conversation]) -> list[Conversation]:
        """Return a subset of *conversations*.

        If the requested sample size exceeds the available data, all
        conversations are returned (no error is raised).
        """
        ...


# ---------------------------------------------------------------------------
# Random
# ---------------------------------------------------------------------------


class RandomSampler(BaseSampler):
    """Uniformly random sample of *n* conversations.

    Args:
        n: Number of conversations to sample.
        seed: Random seed for reproducibility.
    """

    def __init__(self, n: int, seed: int = 42) -> None:
        self.n = n
        self.seed = seed

    def sample(self, conversations: list[Conversation]) -> list[Conversation]:
        if len(conversations) <= self.n:
            return list(conversations)

        rng = random.Random(self.seed)
        sampled = rng.sample(conversations, self.n)
        logger.info(
            "random_sampler.sampled",
            requested=self.n,
            total=len(conversations),
            returned=len(sampled),
        )
        return sampled


# ---------------------------------------------------------------------------
# Stratified
# ---------------------------------------------------------------------------


class StratifiedSampler(BaseSampler):
    """Stratified sample ensuring proportional representation by a metadata key.

    Args:
        n: Total number of conversations to sample.
        key: Metadata key to stratify on (looked up in
            ``conversation.metadata[key]``).
        seed: Random seed for reproducibility.
    """

    def __init__(self, n: int, key: str, seed: int = 42) -> None:
        self.n = n
        self.key = key
        self.seed = seed

    def sample(self, conversations: list[Conversation]) -> list[Conversation]:
        if len(conversations) <= self.n:
            return list(conversations)

        # Group by stratum value
        strata: dict[str, list[Conversation]] = defaultdict(list)
        for conv in conversations:
            stratum = str(conv.metadata.get(self.key, "__unknown__"))
            strata[stratum].append(conv)

        rng = random.Random(self.seed)
        sampled: list[Conversation] = []
        total = len(conversations)

        # Proportional allocation (round-robin for remainders)
        remaining = self.n
        stratum_items = sorted(strata.items(), key=lambda kv: len(kv[1]), reverse=True)

        for _stratum_key, members in stratum_items:
            proportion = len(members) / total
            alloc = max(1, round(proportion * self.n))
            alloc = min(alloc, len(members), remaining)
            sampled.extend(rng.sample(members, alloc))
            remaining -= alloc
            if remaining <= 0:
                break

        logger.info(
            "stratified_sampler.sampled",
            requested=self.n,
            strata_count=len(strata),
            returned=len(sampled),
        )
        return sampled


# ---------------------------------------------------------------------------
# Recent
# ---------------------------------------------------------------------------


def _conversation_timestamp(conv: Conversation) -> datetime:
    """Extract a representative timestamp from a conversation.

    Uses the latest message timestamp if available, otherwise falls back to
    ``metadata["created_at"]`` or epoch.
    """
    # Check message timestamps (most recent first)
    for msg in reversed(conv.messages):
        if msg.timestamp is not None:
            return msg.timestamp

    # Fallback to metadata
    created = conv.metadata.get("created_at")
    if isinstance(created, datetime):
        return created
    if isinstance(created, str):
        try:
            return datetime.fromisoformat(created)
        except (ValueError, TypeError):
            pass

    return datetime.min.replace(tzinfo=timezone.utc)


class RecentSampler(BaseSampler):
    """Select the *n* most recently created conversations.

    Ordering is determined by the latest message timestamp or
    ``metadata["created_at"]``.

    Args:
        n: Number of conversations to return.
    """

    def __init__(self, n: int) -> None:
        self.n = n

    def sample(self, conversations: list[Conversation]) -> list[Conversation]:
        if len(conversations) <= self.n:
            return list(conversations)

        sorted_convs = sorted(
            conversations,
            key=_conversation_timestamp,
            reverse=True,
        )
        sampled = sorted_convs[: self.n]
        logger.info(
            "recent_sampler.sampled",
            requested=self.n,
            total=len(conversations),
            returned=len(sampled),
        )
        return sampled


# ---------------------------------------------------------------------------
# Worst (re-evaluate worst-scoring from a previous run)
# ---------------------------------------------------------------------------


class WorstSampler(BaseSampler):
    """Re-evaluate the *n* worst-scoring conversations from a previous report.

    Args:
        n: Number of conversations to select.
        previous_report: A dict (or Pydantic-serialised report) containing a
            ``conversations`` key (from the pipeline report format) or a
            ``results`` key (from :class:`~chatbot_evals.types.EvalReport`).
            Each entry should have ``conversation_id`` and either
            ``aggregate_score`` or ``overall_score``.
    """

    def __init__(self, n: int, previous_report: dict[str, Any]) -> None:
        self.n = n
        self.previous_report = previous_report

    def sample(self, conversations: list[Conversation]) -> list[Conversation]:
        # Build a mapping of conversation IDs to their previous scores.
        # Support both pipeline-style ("conversations") and SDK-style ("results") keys.
        summaries: list[dict[str, Any]] = (
            self.previous_report.get("conversations")
            or self.previous_report.get("results")
            or []
        )
        score_by_id: dict[str, float] = {}
        for summary in summaries:
            cid = str(summary.get("conversation_id", ""))
            score = summary.get("aggregate_score") or summary.get("overall_score")
            if cid and score is not None:
                score_by_id[cid] = float(score)

        # Sort current conversations by their previous score (ascending = worst first)
        scored = [c for c in conversations if c.id in score_by_id]
        unscored = [c for c in conversations if c.id not in score_by_id]

        scored.sort(key=lambda c: score_by_id.get(c.id, 1.0))

        sampled = scored[: self.n]
        # If we don't have enough scored conversations, pad with unscored
        if len(sampled) < self.n:
            sampled.extend(unscored[: self.n - len(sampled)])

        logger.info(
            "worst_sampler.sampled",
            requested=self.n,
            scored_available=len(scored),
            returned=len(sampled),
        )
        return sampled


# ---------------------------------------------------------------------------
# Diversity
# ---------------------------------------------------------------------------


class DiversitySampler(BaseSampler):
    """Maximise diversity in the sample by selecting conversations that vary
    in length and content.

    The strategy hashes each conversation's content to distribute it into
    buckets, then samples evenly across buckets to maximise coverage.

    Args:
        n: Number of conversations to sample.
        seed: Random seed for reproducibility.
    """

    def __init__(self, n: int, seed: int = 42) -> None:
        self.n = n
        self.seed = seed

    def sample(self, conversations: list[Conversation]) -> list[Conversation]:
        if len(conversations) <= self.n:
            return list(conversations)

        rng = random.Random(self.seed)
        num_buckets = min(self.n, max(10, self.n // 2))

        # Assign each conversation to a bucket based on content hash + length
        buckets: dict[int, list[Conversation]] = defaultdict(list)
        for conv in conversations:
            fingerprint = self._fingerprint(conv)
            bucket_id = int(fingerprint, 16) % num_buckets
            buckets[bucket_id].append(conv)

        # Sort conversations within each bucket by message count for variety
        for members in buckets.values():
            members.sort(key=lambda c: len(c.messages))

        # Round-robin across buckets
        sampled: list[Conversation] = []
        bucket_iters: dict[int, int] = {bid: 0 for bid in buckets}

        while len(sampled) < self.n:
            added_this_round = False
            for bid in sorted(buckets.keys()):
                if len(sampled) >= self.n:
                    break
                idx = bucket_iters[bid]
                members = buckets[bid]
                if idx < len(members):
                    sampled.append(members[idx])
                    bucket_iters[bid] += 1
                    added_this_round = True
            if not added_this_round:
                break

        # If we still need more (unlikely), fill randomly
        if len(sampled) < self.n:
            remaining_set = set(id(c) for c in sampled)
            remaining = [c for c in conversations if id(c) not in remaining_set]
            sampled.extend(
                rng.sample(remaining, min(self.n - len(sampled), len(remaining)))
            )

        logger.info(
            "diversity_sampler.sampled",
            requested=self.n,
            buckets_used=num_buckets,
            returned=len(sampled),
        )
        return sampled

    @staticmethod
    def _fingerprint(conv: Conversation) -> str:
        """Create a deterministic fingerprint for bucket assignment."""
        content_parts = [msg.content for msg in conv.messages]
        raw = "|".join(content_parts) + f"|len={len(conv.messages)}"
        return hashlib.sha256(raw.encode()).hexdigest()
