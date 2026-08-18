"""Shared Pydantic models used across the test suite (mirrors the plan's
registry.register() example in section 3.2)."""

from pydantic import BaseModel


class ChartData(BaseModel):
    labels: list[str]
    values: list[float]


class UserProfile(BaseModel):
    name: str | None = None
    bio: str | None = None


class LogLine(BaseModel):
    text: str
