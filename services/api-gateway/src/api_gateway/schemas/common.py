"""Shared schema primitives used across multiple domain schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Meta(BaseModel):
    """Bundle metadata for composition endpoints."""

    model_config = ConfigDict(extra="allow")

    partial: bool = False
    """True when one or more bundle legs failed; data may be incomplete."""
