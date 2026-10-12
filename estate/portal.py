"""Payout portal: a small stdlib web app on http://localhost:8085 (fictional data only).

Pages: ``/`` (cases + "Start payout run"), ``/runs/<run_id>`` (live status timeline).
API: ``GET /api/health``, ``GET|POST /api/runs``, ``GET /api/runs/<run_id>``,
``POST /api/admin/reset`` (local admin token required; used by ``python -m estate reset``).
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import socket
import time
import urllib.parse
from dataclasses import dataclass
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from estate import __version__
from estate.coordinator import Coordinator
from estate.db import ControlStore, PayoutStore, RunStatus
from estate.paths import EstateConfig, EstatePaths
from estate.runtime import ResetSummary
from payout.money import format_gbp, format_plain

logger = logging.getLogger("estate.portal")

RUN_PATH = re.compile(r"^/runs/(RUN-\d{4,})$")
API_RUN_PATH = re.compile(r"^/api/runs/(RUN-\d{4,})$")
CLOSED_CASES = (("NWM-2024-014", "Northwind Mutual (fictional)", "Closed"),)


@dataclass
class PortalContext:
    """Everything the request handler needs."""

    paths: EstatePaths
    coordinator: Coordinator
    admin_token: str
    started_at: float
    reset: Callable[[], ResetSummary]

    @property
    def config(self) -> EstateConfig:
        return EstateConfig.load(self.paths)


class EstateHTTPServer(ThreadingHTTPServer):
    """HTTP server bound to loopback only. On Windows, exclusive binding prevents two estates sharing a port."""

    daemon_threads = True
    allow_reuse_address = os.name != "nt"

    def server_bind(self) -> None:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if os.name == "nt" and exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


class EstateHTTPServerV6(EstateHTTPServer):
    address_family = socket.AF_INET6


def make_handler(context: PortalContext) -> type[BaseHTTPRequestHandler]:
    """Create a request handler class bound to ``context``."""

    class PortalHandler(BaseHTTPRequestHandler):
        server_version = f"ContosoPayoutPortal/{__version__}"

        # -- routing ----------------------------------------------------------------------------

        def do_GET(self) -> None:  # noqa: N802 - http.server naming
            path = urllib.parse.urlsplit(self.path).path
            try:
                if path == "/":
                    self._html(HTTPStatus.OK, render_cases(context))
                elif match := RUN_PATH.match(path):
                    page = render_run(context, match.group(1))
                    self._html(HTTPStatus.OK if page else HTTPStatus.NOT_FOUND, page or render_not_found(path))
                elif path == "/api/health":
                    self._json(HTTPStatus.OK, health_payload(context))
                elif path == "/api/runs":
                    query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                    limit = _int(query.get("limit", ["20"])[0], 20, 100)
                    runs = ControlStore(context.paths.control_db).list_runs(limit)
                    self._json(HTTPStatus.OK, {"runs": [run_summary(run) for run in runs]})
                elif match := API_RUN_PATH.match(path):
                    payload = run_payload(context, match.group(1))
                    if payload is None:
                        self._json(HTTPStatus.NOT_FOUND, {"error": f"Run {match.group(1)} not found"})
                    else:
                        self._json(HTTPStatus.OK, payload)
                elif path == "/favicon.ico":
                    self.send_response(HTTPStatus.NO_CONTENT)
                    self.end_headers()
                else:
                    self._html(HTTPStatus.NOT_FOUND, render_not_found(path))
            except Exception:  # noqa: BLE001 - always answer, and log the detail
                logger.exception("GET %s failed", path)
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Internal error - see runtime/logs/portal.log"})

        def do_POST(self) -> None:  # noqa: N802 - http.server naming
            path = urllib.parse.urlsplit(self.path).path
            try:
                if path == "/runs":
                    form = urllib.parse.parse_qs(self._body().decode("utf-8"))
                    case_ref = form.get("case_ref", [""])[0]
                    if case_ref != context.config.case_ref:
                        self._html(HTTPStatus.BAD_REQUEST, render_message("Unknown case", f"No payout case {case_ref!r}."))
                        return
                    run_id = ControlStore(context.paths.control_db).create_run(case_ref)
                    logger.info("Run %s requested from the portal for %s", run_id, case_ref)
                    self.send_response(HTTPStatus.SEE_OTHER)
                    self.send_header("Location", f"/runs/{run_id}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif path == "/api/runs":
                    body = self._json_body()
                    case_ref = str(body.get("case_ref", context.config.case_ref))
                    if case_ref != context.config.case_ref:
                        self._json(HTTPStatus.BAD_REQUEST, {"error": f"Unknown case {case_ref!r}"})
                        return
                    deliver_scv = bool(body.get("deliver_scv", True))
                    run_id = ControlStore(context.paths.control_db).create_run(case_ref, deliver_scv=deliver_scv)
                    logger.info("Run %s requested via the API for %s (deliver_scv=%s)", run_id, case_ref, deliver_scv)
                    self._json(HTTPStatus.CREATED, {"run_id": run_id, "status": RunStatus.QUEUED.value,
                                                    "url": f"/runs/{run_id}"})
                elif path == "/api/admin/reset":
                    if self.headers.get("X-Estate-Admin-Token", "") != context.admin_token:
                        self._json(HTTPStatus.FORBIDDEN, {"error": "Admin token missing or wrong"})
                        return
                    if not context.coordinator.run_lock.acquire(timeout=120):
                        self._json(HTTPStatus.CONFLICT, {"error": "A payout run is still in progress; try again"})
                        return
                    try:
                        summary = context.reset()
                    finally:
                        context.coordinator.run_lock.release()
                    self._json(HTTPStatus.OK, {"reset": summary.to_dict()})
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": f"No route for POST {path}"})
            except ValueError as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception:  # noqa: BLE001 - always answer, and log the detail
                logger.exception("POST %s failed", path)
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Internal error - see runtime/logs/portal.log"})

        # -- helpers ----------------------------------------------------------------------------

        def _body(self) -> bytes:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 1_000_000:
                raise ValueError("Request body too large")
            return self.rfile.read(length) if length else b""

        def _json_body(self) -> dict[str, Any]:
            raw = self._body()
            if not raw:
                return {}
            try:
                body = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"Invalid JSON body: {exc}") from exc
            if not isinstance(body, dict):
                raise ValueError("JSON body must be an object")
            return body

        def _html(self, status: HTTPStatus, page: str) -> None:
            self._send(status, page.encode("utf-8"), "text/html; charset=utf-8")

        def _json(self, status: HTTPStatus, payload: Any) -> None:
            self._send(status, json.dumps(payload, indent=2).encode("utf-8"), "application/json; charset=utf-8")

        def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - signature from base class
            polling = self.headers.get("X-Portal-Poll") == "1" if hasattr(self, "headers") and self.headers else False
            logger.log(logging.DEBUG if polling else logging.INFO, "%s %s", self.address_string(), format % args)

    return PortalHandler


# -- payloads ----------------------------------------------------------------------------------


def health_payload(context: PortalContext) -> dict[str, Any]:
    config = context.config
    coordinator = context.coordinator
    last_poll = coordinator.last_poll_at
    return {
        "status": "ok",
        "service": "contoso-payout-estate",
        "version": __version__,
        "pid": os.getpid(),
        "uptime_seconds": round(time.time() - context.started_at, 1),
        "coordinator": {
            "alive": coordinator.alive,
            "last_poll_seconds_ago": None if last_poll is None else round(time.time() - last_poll, 1),
            "current_run": coordinator.current_run,
        },
        "shell": coordinator.shell.label,
        "patch_drift": config.patch_drift,
        "case_ref": config.case_ref,
    }


def run_summary(run: dict[str, Any]) -> dict[str, Any]:
    status = RunStatus(run["status"])
    return {
        "run_id": run["run_id"],
        "case_ref": run["case_ref"],
        "status": status.value,
        "status_label": status.label,
        "requested_at": run["requested_at"],
        "finished_at": run["finished_at"],
    }


def run_payload(context: PortalContext, run_id: str) -> dict[str, Any] | None:
    store = ControlStore(context.paths.control_db)
    run = store.get_run(run_id)
    if run is None:
        return None
    status = RunStatus(run["status"])
    summary = None
    if status is RunStatus.COMPLETED:
        totals = PayoutStore(context.paths.payout_db).summary(run_id)
        if totals is not None:
            summary = {
                "depositors": totals.depositors,
                "eligible_depositors_paid": totals.payees,
                "total_compensation": format_plain(totals.total_compensation),
            }
    return {
        **run_summary(run),
        "started_at": run["started_at"],
        "failure_reason": run["failure_reason"],
        "payment_file": run["payment_file"],
        "summary": summary,
        "events": store.events(run_id),
    }


# -- HTML --------------------------------------------------------------------------------------

STYLE = """
:root { --ink:#1b1b1f; --muted:#5b5b66; --line:#d0d0d7; --brand:#1f3a68; --ok:#0b6b2f; --bad:#a1142b; --warn:#7a4b00; }
* { box-sizing: border-box; }
body { margin:0; font: 18px/1.5 "Segoe UI", system-ui, -apple-system, sans-serif; color:var(--ink); background:#f6f7fb; }
header { background:var(--brand); color:#fff; padding:14px 32px; display:flex; gap:24px; align-items:baseline; }
header a { color:#fff; font-weight:600; font-size:22px; text-decoration:none; }
header .env { opacity:.85; font-size:15px; }
main { max-width:1100px; margin:24px auto; padding:0 32px; }
h1 { font-size:30px; margin:8px 0 16px; }
h2 { font-size:22px; margin:28px 0 10px; }
table { border-collapse:collapse; width:100%; background:#fff; border:1px solid var(--line); }
caption { text-align:left; font-weight:600; padding:8px 0; color:var(--muted); }
th, td { text-align:left; padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:middle; }
th { background:#eef0f6; font-weight:600; }
td.num, th.num { text-align:right; font-variant-numeric: tabular-nums; }
button { font:inherit; background:var(--brand); color:#fff; border:0; border-radius:6px; padding:10px 18px; cursor:pointer; }
button:focus-visible, a:focus-visible { outline:3px solid #f2b705; outline-offset:2px; }
.badge { display:inline-block; padding:4px 12px; border-radius:999px; font-weight:600; background:#e6e9f2; }
.badge-completed { background:#dff3e6; color:var(--ok); }
.badge-failed { background:#fbe1e5; color:var(--bad); }
.badge-running { background:#fff2d6; color:var(--warn); }
.alert { background:#fbe1e5; color:var(--bad); border-left:6px solid var(--bad); padding:12px 16px; font-weight:600; }
dl.summary { display:grid; grid-template-columns: max-content 1fr; gap:6px 24px; background:#fff; border:1px solid var(--line); padding:16px 20px; }
dl.summary dt { color:var(--muted); }
dl.summary dd { margin:0; font-weight:600; }
ol.timeline { background:#fff; border:1px solid var(--line); padding:12px 20px 12px 44px; }
ol.timeline time { color:var(--muted); font-variant-numeric: tabular-nums; margin-right:12px; }
footer { max-width:1100px; margin:32px auto; padding:0 32px; color:var(--muted); font-size:14px; }
"""


def _page(title: str, body: str, script: str = "") -> str:
    return f"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} - Payout portal (demo)</title>
<style>{STYLE}</style>
</head>
<body>
<header role="banner"><a href="/">Payout portal</a><span class="env">Simulated estate &middot; synthetic data</span></header>
<main id="main">
{body}
</main>
<footer>Fictional data. Simplified rules for demonstration only &mdash; not FSCS policy.</footer>
{script}
</body>
</html>
"""


def render_cases(context: PortalContext) -> str:
    config = context.config
    store = ControlStore(context.paths.control_db)
    depositors = _depositor_count(config)
    rows = [
        f"""<tr data-testid="case-{html.escape(config.case_ref)}">
<th scope="row">{html.escape(config.case_ref)}</th><td>{html.escape(config.firm_name)}</td><td>Payout in progress</td>
<td class="num">{depositors}</td>
<td><form method="post" action="/runs"><input type="hidden" name="case_ref" value="{html.escape(config.case_ref)}">
<button type="submit" data-testid="start-run">Start payout run</button></form></td></tr>"""
    ]
    for case_ref, firm, status in CLOSED_CASES:
        rows.append(
            f"<tr><th scope=\"row\">{case_ref}</th><td>{firm}</td><td>{status}</td>"
            "<td class=\"num\">&mdash;</td><td>&mdash;</td></tr>"
        )
    runs = store.list_runs(10)
    run_rows = "".join(
        f"""<tr><td><a href="/runs/{html.escape(r['run_id'])}">{html.escape(r['run_id'])}</a></td>
<td>{html.escape(r['case_ref'])}</td><td>{_badge(RunStatus(r['status']))}</td>
<td>{html.escape(_time(r['requested_at']))}</td><td>{html.escape(_time(r['finished_at']))}</td></tr>"""
        for r in runs
    ) or '<tr><td colspan="5">No payout runs yet.</td></tr>'
    body = f"""<h1>Cases</h1>
<table data-testid="case-table">
<caption>Failed deposit-takers (fictional)</caption>
<thead><tr><th scope="col">Case reference</th><th scope="col">Firm</th><th scope="col">Status</th>
<th scope="col" class="num">Depositors (SCV)</th><th scope="col">Action</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
<h2 id="recent-runs-heading">Recent payout runs</h2>
<table data-testid="recent-runs" aria-labelledby="recent-runs-heading">
<thead><tr><th scope="col">Run</th><th scope="col">Case</th><th scope="col">Status</th>
<th scope="col">Requested</th><th scope="col">Finished</th></tr></thead>
<tbody>{run_rows}</tbody>
</table>"""
    return _page("Cases", body)


def render_run(context: PortalContext, run_id: str) -> str | None:
    store = ControlStore(context.paths.control_db)
    run = store.get_run(run_id)
    if run is None:
        return None
    config = context.config
    status = RunStatus(run["status"])
    events = store.events(run_id)
    parts = [
        '<p><a href="/">&larr; Back to cases</a></p>',
        f'<h1>Payout run <span data-testid="run-id">{html.escape(run_id)}</span></h1>',
        f"<p>Case <strong>{html.escape(run['case_ref'])}</strong> &middot; {html.escape(config.firm_name)}</p>",
        f'<p>Status: <span role="status" aria-live="polite" data-testid="run-status" class="{_badge_class(status)}">'
        f"{html.escape(status.label)}</span></p>",
    ]
    if status is RunStatus.FAILED:
        parts.append(
            f'<p role="alert" class="alert" data-testid="failure-reason">Failed: {html.escape(run["failure_reason"] or "unknown reason")}</p>'
        )
    payments_html = ""
    if status is RunStatus.COMPLETED:
        payout = PayoutStore(context.paths.payout_db)
        totals = payout.summary(run_id)
        paid = str(totals.payees) if totals else "0"
        total = format_gbp(totals.total_compensation if totals else Decimal("0.00"))
        parts.append(
            f"""<section aria-labelledby="summary-heading"><h2 id="summary-heading">Run summary</h2>
<dl class="summary" data-testid="run-summary">
<dt>Eligible depositors paid</dt><dd data-testid="eligible-depositors-paid">{paid}</dd>
<dt>Total compensation</dt><dd data-testid="total-compensation">{html.escape(total)}</dd>
<dt>Payment file</dt><dd data-testid="payment-file">{html.escape(run['payment_file'] or '')}</dd>
</dl></section>"""
        )
        rows = "".join(
            f"<tr><th scope=\"row\">{html.escape(p['depositor_id'])}</th><td>{html.escape(p['depositor_name'])}</td>"
            f"<td>{'Yes' if p['eligible'] else 'No'}</td>"
            f"<td class=\"num\" data-testid=\"payment-{html.escape(p['depositor_id'])}\">"
            f"{html.escape(format_gbp(Decimal(p['compensation_gbp'])))}</td></tr>"
            for p in payout.payments(run_id)
        )
        payments_html = f"""<section aria-labelledby="payments-heading"><h2 id="payments-heading">Payments</h2>
<table data-testid="payments-table"><caption>Compensation by depositor</caption>
<thead><tr><th scope="col">Depositor</th><th scope="col">Name</th><th scope="col">Eligible</th>
<th scope="col" class="num">Compensation</th></tr></thead><tbody>{rows}</tbody></table></section>"""
    timeline = "".join(
        f"<li><time datetime=\"{html.escape(e['ts'])}\">{html.escape(_time(e['ts']))}</time>{html.escape(_event_text(e))}</li>"
        for e in events
    )
    parts.append(
        f"""<section aria-labelledby="timeline-heading"><h2 id="timeline-heading">Timeline</h2>
<ol class="timeline" data-testid="run-timeline" aria-label="Run timeline">{timeline}</ol></section>"""
    )
    parts.append(payments_html)
    script = ""
    if not status.is_terminal:
        signature = json.dumps(f"{status.value}|{len(events)}")
        api_url = json.dumps(f"/api/runs/{run_id}")
        script = f"""<script>
(function () {{
  var signature = {signature};
  function poll() {{
    fetch({api_url}, {{ cache: "no-store", headers: {{ "X-Portal-Poll": "1" }} }})
      .then(function (r) {{ return r.json(); }})
      .then(function (run) {{
        if (run.status + "|" + run.events.length !== signature) {{ window.location.reload(); }}
        else {{ setTimeout(poll, 1000); }}
      }})
      .catch(function () {{ setTimeout(poll, 2000); }});
  }}
  setTimeout(poll, 1000);
}})();
</script>
<noscript><meta http-equiv="refresh" content="2"></noscript>"""
    return _page(f"Run {run_id}", "\n".join(parts), script)


def render_not_found(path: str) -> str:
    return render_message("Not found", f"There is nothing at {path}.")


def render_message(title: str, message: str) -> str:
    return _page(title, f'<h1>{html.escape(title)}</h1><p>{html.escape(message)}</p><p><a href="/">Back to cases</a></p>')


def _badge(status: RunStatus) -> str:
    return f'<span class="{_badge_class(status)}">{html.escape(status.label)}</span>'


def _badge_class(status: RunStatus) -> str:
    if status is RunStatus.COMPLETED:
        return "badge badge-completed"
    if status is RunStatus.FAILED:
        return "badge badge-failed"
    return "badge badge-running"


def _event_text(event: dict[str, Any]) -> str:
    if event["event"] == "STATUS" and event["status"]:
        label = RunStatus(event["status"]).label
        message = event["message"] or ""
        return label if message in ("", label) else f"{label} - {message}"
    return str(event["message"] or event["event"])


def _time(value: str | None) -> str:
    if not value:
        return ""
    return value[11:19] if len(value) >= 19 else value


def _int(raw: str, default: int, maximum: int) -> int:
    try:
        return max(1, min(int(raw), maximum))
    except ValueError:
        return default


def _depositor_count(config: EstateConfig) -> str:
    try:
        with config.scv_seed_file.open("r", encoding="utf-8") as handle:
            next(handle, None)
            return str(len({line.split(",")[3] for line in handle if line.strip()}))
    except (OSError, IndexError):
        return "-"
