"""Baseline 1: default A2A SDK behaviour. Retry on failure, no dedup, no evidence."""

from bench.engine import DEFAULT_SDK as CONFIG

__all__ = ["CONFIG"]
