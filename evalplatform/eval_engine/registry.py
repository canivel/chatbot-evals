"""Metric plugin registry with singleton pattern and decorator-based registration."""

from __future__ import annotations

import threading
from typing import Any

import structlog

from evalplatform.eval_engine.metrics.base import BaseMetric

logger = structlog.get_logger(__name__)


class MetricRegistry:
    """Singleton registry for evaluation metrics.

    Provides decorator-based registration, lookup by name, and filtering by
    category.  Thread-safe via a lock on mutation operations.

    Usage::

        from evalplatform.eval_engine.registry import metric_registry

        @metric_registry.register
        class MyMetric(BaseMetric):
            name = "my_metric"
            ...
    """

    _instance: MetricRegistry | None = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> MetricRegistry:
        if cls._instance is None:
            with cls._lock:
                # Double-checked locking
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._metrics: dict[str, type[BaseMetric]] = {}
                    instance._instances: dict[str, BaseMetric] = {}
                    cls._instance = instance
        return cls._instance

    # -- Registration --------------------------------------------------------

    def register(self, metric_class: type[BaseMetric]) -> type[BaseMetric]:
        """Register a metric class with the registry.

        Can be used as a decorator::

            @metric_registry.register
            class Faithfulness(BaseMetric):
                ...

        Args:
            metric_class: A concrete subclass of :class:`BaseMetric`.

        Returns:
            The same class, unmodified (so the decorator is transparent).

        Raises:
            TypeError: If *metric_class* is not a subclass of ``BaseMetric``.
            ValueError: If a metric with the same name is already registered.
        """
        if not (isinstance(metric_class, type) and issubclass(metric_class, BaseMetric)):
            raise TypeError(
                f"Expected a BaseMetric subclass, got {metric_class!r}"
            )

        name = metric_class.name
        with self._lock:
            if name in self._metrics:
                existing = self._metrics[name]
                if existing is not metric_class:
                    raise ValueError(
                        f"Metric {name!r} is already registered by {existing.__name__}. "
                        f"Cannot register {metric_class.__name__} with the same name."
                    )
                return metric_class

            self._metrics[name] = metric_class
            logger.info("metric_registered", name=name, cls=metric_class.__name__)

        return metric_class

    # -- Lookup --------------------------------------------------------------

    def get_metric(self, name: str) -> BaseMetric:
        """Return a singleton instance of the named metric.

        Args:
            name: The ``name`` attribute of the metric class.

        Returns:
            An instantiated metric.

        Raises:
            KeyError: If no metric with that name is registered.
        """
        if name not in self._metrics:
            raise KeyError(
                f"Metric {name!r} not found. "
                f"Available: {list(self._metrics.keys())}"
            )

        if name not in self._instances:
            self._instances[name] = self._metrics[name]()

        return self._instances[name]

    def list_metrics(self) -> list[dict[str, Any]]:
        """Return metadata for every registered metric.

        Returns:
            A list of dicts, each containing ``name``, ``description``,
            ``version``, and ``category``.
        """
        results: list[dict[str, Any]] = []
        for name, cls in self._metrics.items():
            results.append(
                {
                    "name": cls.name,
                    "description": cls.description,
                    "version": cls.version,
                    "category": cls.category.value if hasattr(cls.category, "value") else cls.category,
                    "class": cls.__name__,
                }
            )
        return results

    def get_metrics_by_category(self, category: str) -> list[BaseMetric]:
        """Return instantiated metrics that match *category*.

        Args:
            category: Category string (e.g. ``"faithfulness"``).

        Returns:
            List of metric instances whose category matches.
        """
        matches: list[BaseMetric] = []
        for name, cls in self._metrics.items():
            cat_value = cls.category.value if hasattr(cls.category, "value") else cls.category
            if cat_value == category:
                matches.append(self.get_metric(name))
        return matches

    # -- Utilities -----------------------------------------------------------

    def clear(self) -> None:
        """Remove all registered metrics.  Primarily for testing."""
        with self._lock:
            self._metrics.clear()
            self._instances.clear()
            logger.debug("metric_registry_cleared")

    def __contains__(self, name: str) -> bool:
        return name in self._metrics

    def __len__(self) -> int:
        return len(self._metrics)

    def __repr__(self) -> str:
        return f"<MetricRegistry metrics={list(self._metrics.keys())}>"


# Module-level singleton for convenient imports
metric_registry = MetricRegistry()
