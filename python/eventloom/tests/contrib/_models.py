"""Shared Pydantic-v1-style test models for eventloom.contrib.pydantic_v1's
test suite (mirrors ../_models.py's pattern for the core suite)."""

from typing import Dict, List, Optional, Set, Tuple

from eventloom.contrib.pydantic_v1 import BaseModel


class Address(BaseModel):
    city: Optional[str] = None
    country: Optional[str] = None


class Tag(BaseModel):
    label: str


class Person(BaseModel):
    name: Optional[str] = None
    age: Optional[int] = None
    address: Optional[Address] = None  # SHAPE_SINGLETON
    tags: Optional[List[Tag]] = None  # SHAPE_LIST
    nicknames: Optional[List[str]] = None  # List[scalar] — passthrough
    offices: Optional[Dict[str, Address]] = None  # SHAPE_DICT
    labels: Optional[Set[Tag]] = None  # SHAPE_SET
    coordinates: Optional[Tuple[Tag, ...]] = None  # SHAPE_TUPLE_ELLIPSIS


class Criterion(BaseModel):
    title: Optional[str] = None
    applicable: Optional[bool] = None
    score: Optional[float] = None


class Section(BaseModel):
    criterias: List[Criterion] = []
