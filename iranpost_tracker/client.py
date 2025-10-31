"""Utilities for interacting with Iran Post's parcel tracking service.

This module intentionally sticks to Python's standard library so that the
project works even in restricted environments where installing third-party
packages (such as :mod:`requests`) is not feasible.  The public Iran Post
tracking API has historically exposed a couple of different shapes; to stay
resilient the :class:`IranPostTracker` tries a handful of well known endpoints
and automatically normalises their responses.
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence


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
                "status",
                "state",
                "eventDescription",
                "Description",
                "desc",
                "StatusDescription",
            )
            or "وضعیت نامشخص",
            date=first("date", "eventDate", "EventDate", "date_sh", "Date"),
            time=first("time", "eventTime", "EventTime", "time_sh", "Time"),
            location=first(
                "location",
                "office",
                "EventOffice",
                "EventPlace",
                "Place",
                "Location",
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


@dataclass(frozen=True)
class EndpointConfig:
    """Configuration descriptor for a single endpoint variant."""

    url: str
    method: str = "GET"
    payload: str = "query"  # accepted values: ``query``, ``json``, ``form``
    barcode_field: str = "barcode"
    extra_payload: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


class IranPostTracker:
    """Simple client for the Iran Post parcel tracking service."""

    DEFAULT_ENDPOINTS: Sequence[EndpointConfig] = (
        EndpointConfig(
            "https://api.post.ir/postapi/v1/TrackAndTrace/TrackResultByBarcode",
            method="GET",
            payload="query",
        ),
        EndpointConfig(
            "https://tracking.post.ir/api/tracking/GetTrackByBarcode",
            method="POST",
            payload="json",
        ),
        EndpointConfig(
            "https://tracking.post.ir/api/tracking/GetTrack",
            method="POST",
            payload="form",
        ),
    )

    def __init__(
        self,
        *,
        endpoint: Optional[str] = None,
        endpoints: Optional[Sequence[EndpointConfig]] = None,
        timeout: int = 15,
        user_agent: Optional[str] = None,
    ) -> None:
        if endpoint and endpoints:
            raise ValueError("Provide either 'endpoint' or 'endpoints', not both.")

        if endpoint:
            endpoints = (EndpointConfig(endpoint),)
        elif not endpoints:
            custom_endpoint = os.getenv("IRAN_POST_ENDPOINT")
            if custom_endpoint:
                endpoints = (EndpointConfig(custom_endpoint),)
            else:
                endpoints = self.DEFAULT_ENDPOINTS

        self.endpoints: Sequence[EndpointConfig] = endpoints
        self.timeout = timeout
        self.user_agent = user_agent or "IranPostTracker/2.0 (+https://github.com/)"
        self._ssl_context = ssl.create_default_context()

    def track(self, barcode: str) -> TrackingResult:
        if not barcode:
            raise TrackingError("کد رهگیری نباید خالی باشد.")

        barcode = barcode.strip()
        errors: List[str] = []
        for endpoint in self.endpoints:
            try:
                response = self._request(endpoint, barcode)
                return self._parse_response(response, barcode)
            except TrackingError as exc:  # pragma: no cover - defensive
                errors.append(str(exc))
            except Exception as exc:  # pragma: no cover - network layer guard
                errors.append(str(exc))

        if errors:
            # Remove duplicate messages while preserving order for readability.
            unique_errors = list(dict.fromkeys(errors))
            raise TrackingError("؛ ".join(unique_errors))

        raise TrackingError("پاسخی از سرویس رهگیری دریافت نشد.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _request(self, endpoint: EndpointConfig, barcode: str) -> dict:
        payload = self._build_payload(endpoint, barcode)
        headers = {"User-Agent": self.user_agent, **endpoint.headers}

        method = endpoint.method.upper()
        if method == "GET" and payload:
            query_string = urllib.parse.urlencode(payload)
            url = f"{endpoint.url}?{query_string}"
            data = None
        else:
            url = endpoint.url
            data = self._encode_body(endpoint, payload)
            if data is not None and "Content-Type" not in headers:
                headers["Content-Type"] = (
                    "application/json"
                    if endpoint.payload == "json"
                    else "application/x-www-form-urlencoded"
                )

        request = urllib.request.Request(url=url, method=method, headers=headers, data=data)

        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout, context=self._ssl_context
            ) as response:
                raw_body = response.read()
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            raise TrackingError(f"کد وضعیت {exc.code} از سرویس رهگیری دریافت شد.") from exc
        except urllib.error.URLError as exc:
            raise TrackingError("امکان اتصال به سرویس رهگیری وجود ندارد.") from exc

        text = raw_body.decode("utf-8", errors="ignore").strip()
        if not text:
            raise TrackingError("پاسخ خالی از سرویس رهگیری دریافت شد.")

        try:
            if "json" in content_type.lower() or text.startswith("{") or text.startswith("["):
                return json.loads(text)
        except json.JSONDecodeError as exc:
            raise TrackingError("پاسخ نامعتبر از سرویس رهگیری دریافت شد.") from exc

        raise TrackingError("ساختار پاسخ دریافتی پشتیبانی نمی‌شود.")

    def _build_payload(self, endpoint: EndpointConfig, barcode: str) -> dict:
        data = dict(endpoint.extra_payload)
        data[endpoint.barcode_field] = barcode
        return data

    @staticmethod
    def _encode_body(endpoint: EndpointConfig, payload: dict) -> Optional[bytes]:
        method = endpoint.method.upper()
        if method == "GET":
            return None

        if endpoint.payload == "json":
            return json.dumps(payload).encode("utf-8")
        if endpoint.payload == "form":
            return urllib.parse.urlencode(payload).encode("utf-8")
        if endpoint.payload == "query":
            return urllib.parse.urlencode(payload).encode("utf-8")

        raise TrackingError("نوع ارسال ناشناخته برای سرویس رهگیری پیکربندی شده است.")

    def _parse_response(self, payload: dict, barcode: str) -> TrackingResult:
        if isinstance(payload, list):
            payload = {"events": payload}

        if not isinstance(payload, dict):
            raise TrackingError("ساختار پاسخ دریافتی پشتیبانی نمی‌شود.")

        # Some APIs wrap the actual payload in nested keys.
        data = (
            payload.get("result")
            or payload.get("Result")
            or payload.get("data")
            or payload.get("Data")
            or payload
        )

        events = self._extract_events(data)
        sender = self._first_of(data, "sender", "SenderName", "senderName", "Sender")
        receiver = self._first_of(
            data,
            "receiver",
            "ReceiverName",
            "reciverName",
            "receiverName",
            "Receiver",
        )
        current_status = self._first_of(
            data,
            "currentStatus",
            "CurrentStatus",
            "status",
            "State",
            "last_state",
            "Status",
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
            data.get("details"),
            data.get("Details"),
        ]
        for candidate in candidates:
            if isinstance(candidate, list) and candidate:
                for raw_event in candidate:
                    if isinstance(raw_event, dict):
                        yield TrackingEvent.from_mapping(raw_event)
                return

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
    "EndpointConfig",
    "IranPostTracker",
    "TrackingError",
    "TrackingEvent",
    "TrackingResult",
]
