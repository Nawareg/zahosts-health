from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class Status(str, Enum):
    OK = "ok"
    WARN = "warn"
    CRITICAL = "critical"


@dataclass
class CollectorResult:
    name: str
    status: Status
    metrics: dict[str, Any] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def legacy_payload(self) -> dict[str, Any]:
        return {"status": self.status.value, **self.metrics}


class Collector(ABC):
    name: str

    @abstractmethod
    def collect(self, cfg: Mapping[str, Any]) -> CollectorResult:
        raise NotImplementedError
