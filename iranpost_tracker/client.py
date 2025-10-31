"""Utilities for interacting with Iran Post's parcel tracking service."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

import requests


class TrackingError(RuntimeError):
    """Raised when the tracking service cannot return a valid result."""


@dataclass
class TrackingEvent:
    """Represents a single tracking event."""

    description: str
    date: Optional[str] = None
    time: Optional[str] = None
    location: Optional[str] = None

    @classmethod
    def from_mapping(cls, payload: dict) -> "TrackingEvent":
        """Create an event from a JSON mapping returned by the API.

        The Iran Post tracking endpoint has gone through several revisions over
        the years.  Each revision exposes the same core information but uses
        slightly different field names.  To provide a resilient experience we
        attempt to look up multiple field names before falling back to a
        sensible default.
        """

        def first(*keys: str) -> Optional[str]:
            for key in keys:
                value = payload.get(key)
                if value:
                    return str(value)
            return None

        return cls(
            description=first(
                "status", "state", "eventDescription", "Description", "desc"
            )
            or "وضعیت نامشخص",
            date=first("date", "eventDate", "EventDate", "date_sh", "Date"),
            time=first("time", "eventTime", "EventTime", "time_sh", "Time"),
            location=first(
                "location", "office", "EventOffice", "EventPlace", "Place"
            ),
        )


@dataclass
class TrackingResult:
    """Structured result returned by the tracking client."""

    barcode: str
    events: List[TrackingEvent] = field(default_factory=list)
    sender: Optional[str] = None
    receiver: Optional[str] = None
    current_status: Optional[str] = None
    raw_response: Optional[dict] = None


class IranPostTracker:
    """Simple client for the Iran Post parcel tracking service."""

    DEFAULT_ENDPOINT = (
        "https://api.post.ir/postapi/v1/TrackAndTrace/TrackResultByBarcode"
    )

    def __init__(
        self,
        *,
        endpoint: Optional[str] = None,
        session: Optional[requests.Session] = None,
        timeout: int = 15,
    ) -> None:
        self.endpoint = endpoint or os.getenv("IRAN_POST_ENDPOINT", self.DEFAULT_ENDPOINT)
        self.session = session or requests.Session()
        self.timeout = timeout

    def track(self, barcode: str) -> TrackingResult:
        if not barcode:
            raise TrackingError("کد رهگیری نباید خالی باشد.")

        response = self._request(barcode.strip())
        data = self._parse_response(response, barcode)
        return data

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _request(self, barcode: str) -> dict:
        try:
            result = self.session.get(
                self.endpoint,
                params={"barcode": barcode},
                timeout=self.timeout,
            )
            result.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            raise TrackingError(f"خطا در دریافت اطلاعات: {exc}") from exc
        except requests.exceptions.Timeout as exc:
            raise TrackingError("مهلت ارتباط با سرویس رهگیری به پایان رسید.") from exc
        except requests.exceptions.RequestException as exc:
            raise TrackingError("امکان اتصال به سرویس رهگیری وجود ندارد.") from exc

        try:
            return result.json()
        except json.JSONDecodeError as exc:
            raise TrackingError("پاسخ نامعتبر از سرویس رهگیری دریافت شد.") from exc

    def _parse_response(self, payload: dict, barcode: str) -> TrackingResult:
        if not isinstance(payload, dict):
            raise TrackingError("ساختار پاسخ دریافتی پشتیبانی نمی‌شود.")

        # Some APIs wrap the actual payload in a "result" or "Result" key.
        data = payload.get("result") or payload.get("Result") or payload

        events = self._extract_events(data)
        sender = self._first_of(data, "sender", "SenderName", "senderName")
        receiver = self._first_of(
            data, "receiver", "ReceiverName", "reciverName", "receiverName"
        )
        current_status = self._first_of(
            data,
            "currentStatus",
            "CurrentStatus",
            "status",
            "State",
            "last_state",
        )

        return TrackingResult(
            barcode=barcode,
            events=list(events),
            sender=sender,
            receiver=receiver,
            current_status=current_status,
            raw_response=payload,
        )

    def _extract_events(self, data: dict) -> Iterable[TrackingEvent]:
        candidates = [
            data.get("events"),
            data.get("Events"),
            data.get("history"),
            data.get("History"),
            data.get("tracks"),
            data.get("Tracks"),
            data.get("barCodeDetails"),
            data.get("TraceDetails"),
        ]
        for candidate in candidates:
            if isinstance(candidate, list) and candidate:
                for raw_event in candidate:
                    if isinstance(raw_event, dict):
                        yield TrackingEvent.from_mapping(raw_event)
                return

        # If we reach here, we did not find any events in the expected keys.
        # Some API variants return a list directly at the root.
        if isinstance(data, list):
            for raw_event in data:
                if isinstance(raw_event, dict):
                    yield TrackingEvent.from_mapping(raw_event)

    @staticmethod
    def _first_of(data: dict, *keys: str) -> Optional[str]:
        for key in keys:
            value = data.get(key)
            if value:
                return str(value)
        return None


__all__ = [
    "IranPostTracker",
    "TrackingError",
    "TrackingEvent",
    "TrackingResult",
]
