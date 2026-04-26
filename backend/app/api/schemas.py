"""Pydantic request/response models for the API surface.

Days 7-8 ships the review and skip schemas. Session/experiment listing,
folder ingestion, and evaluator schemas come Days 9-10.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=500)


class ReviewResponse(BaseModel):
    experiment_id: str
    status: str
    decision: str
    queued_decide: bool


class SkipResponse(BaseModel):
    experiment_id: str
    status: str
    decision: str
    queued_decide: bool
