"""Test helpers for code built on eventloom. Not imported by `eventloom.core`
or any adapter — safe to depend on only from test code."""

from .mock_emitter import MockEmitter

__all__ = ["MockEmitter"]
