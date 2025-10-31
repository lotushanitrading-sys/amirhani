from __future__ import annotations

from flask import Flask, jsonify, render_template, request

from iranpost_tracker.client import IranPostTracker, TrackingError

app = Flask(__name__)
app.json.ensure_ascii = False
tracker = IranPostTracker()


def _validate_barcode(barcode: str) -> str:
    barcode = (barcode or "").strip()
    if not barcode:
        raise TrackingError("لطفاً کد رهگیری را وارد کنید.")
    if not barcode.isdigit():
        raise TrackingError("کد رهگیری باید فقط شامل اعداد باشد.")
    if len(barcode) < 5 or len(barcode) > 30:
        raise TrackingError("طول کد رهگیری باید بین ۵ تا ۳۰ رقم باشد.")
    return barcode


@app.route("/", methods=["GET", "POST"])
def index():
    context = {}
    if request.method == "POST":
        barcode = request.form.get("barcode", "")
        try:
            validated_barcode = _validate_barcode(barcode)
            result = tracker.track(validated_barcode)
            context.update({
                "result": result,
                "barcode": validated_barcode,
            })
        except TrackingError as exc:
            context.update({
                "error": str(exc),
                "barcode": barcode,
            })
    return render_template("index.html", **context)


@app.route("/api/track", methods=["POST"])
def api_track():
    payload = request.get_json(force=True, silent=True) or {}
    barcode = payload.get("barcode", "")
    try:
        validated_barcode = _validate_barcode(barcode)
        result = tracker.track(validated_barcode)
        return jsonify(
            {
                "barcode": result.barcode,
                "current_status": result.current_status,
                "sender": result.sender,
                "receiver": result.receiver,
                "events": [
                    {
                        "description": event.description,
                        "date": event.date,
                        "time": event.time,
                        "location": event.location,
                    }
                    for event in result.events
                ],
                "raw_response": result.raw_response,
            }
        )
    except TrackingError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/health")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8000)
