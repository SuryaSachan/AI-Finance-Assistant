"""The structured query plan the LLM must produce.

The LLM never writes SQL and never does arithmetic. It only fills in this
schema; everything after this point is deterministic Python + DuckDB.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .schema_catalog import AGGREGATIONS, INTENTS, OPERATORS


class Filter(BaseModel):
    model_config = ConfigDict(extra="ignore")

    field: str
    op: Literal[OPERATORS] = "eq"  # type: ignore[valid-type]
    value: Any = None

    @field_validator("op", mode="before")
    @classmethod
    def _norm_op(cls, v):
        alias = {
            "=": "eq", "==": "eq", "!=": "neq", "<>": "neq", ">": "gt", ">=": "gte",
            "<": "lt", "<=": "lte", "like": "contains", "ilike": "contains",
            "isnull": "is_null", "notnull": "not_null", "not in": "not_in",
        }
        if isinstance(v, str):
            v = v.strip().lower()
            return alias.get(v, v)
        return v


class Metric(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agg: Literal[AGGREGATIONS] = "sum"  # type: ignore[valid-type]
    field: str = "amount"
    alias: str | None = None

    @field_validator("agg", mode="before")
    @classmethod
    def _norm_agg(cls, v):
        alias = {"total": "sum", "average": "avg", "mean": "avg", "distinct": "count_distinct",
                 "nunique": "count_distinct", "cnt": "count", "maximum": "max", "minimum": "min"}
        if isinstance(v, str):
            v = v.strip().lower()
            return alias.get(v, v)
        return v

    @property
    def name(self) -> str:
        if self.alias:
            return self.alias
        return "count" if self.agg == "count" else f"{self.agg}_{self.field}"


class Period(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: str = "all"
    n: int | None = None
    value: str | None = None
    start: str | None = None
    end: str | None = None
    exclude_weekends: bool = False


class Sort(BaseModel):
    model_config = ConfigDict(extra="ignore")

    field: str
    dir: Literal["asc", "desc"] = "desc"


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent: Literal[INTENTS] = "aggregate"  # type: ignore[valid-type]
    dataset: str = "transactions"
    metrics: list[Metric] = Field(default_factory=lambda: [Metric()])
    group_by: list[str] = Field(default_factory=list)
    filters: list[Filter] = Field(default_factory=list)
    period: Period | None = None
    compare_to_previous: bool = False
    sort: Sort | None = None
    limit: int = 20
    clarification: str | None = None

    @field_validator("group_by", mode="before")
    @classmethod
    def _listify(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        return v

    @field_validator("limit", mode="before")
    @classmethod
    def _clamp(cls, v):
        try:
            return max(1, min(int(v), 500))
        except (TypeError, ValueError):
            return 20
