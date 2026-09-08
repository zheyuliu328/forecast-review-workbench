"""Loopback-only application and installed CLI; no external data services."""

import argparse
import base64
import hmac
import json
import re
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__
from .engine import review
from .example import example_request
from .experiments import experiment_example, experiment_result, reveal_experiment, transfer_experiment
from .exporter import build_bundle, bundle_zip, write_bundle
from .reconciliation import reconcile, reconciliation_example
from .tableio import inspect_table
from .workflow_exports import build_experiment_bundle, build_reconciliation_bundle

MAX_REQUEST = 40 * 1024 * 1024
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/styles.css": ("styles.css", "text/css; charset=utf-8"),
}
ASSETS.update(
    {
        "/experiments": ("experiments.html", "text/html; charset=utf-8"),
        "/reconcile": ("reconcile.html", "text/html; charset=utf-8"),
        **{
            f"/{name}": (name, "text/javascript; charset=utf-8")
            for name in ("experiments.js", "reconcile.js", "extension-common.js")
        },
        "/extensions.css": ("extensions.css", "text/css; charset=utf-8"),
    }
)
ASSETS.update(
    {f"/static/{name}": (name, mime) for name, mime in list(ASSETS.values()) if not name.endswith(".html")}
)


def _reject_constant(value):
    raise ValueError(f"JSON contains an unsupported number: {value}")


def _unique_object(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"JSON repeats a field: {key}")
        output[key] = value
    return output


def load_json(raw):
    try:
        value = json.loads(raw, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError("The request must be a valid UTF-8 JSON object.") from exc
    if not isinstance(value, dict):
        raise ValueError("The request must be a JSON object.")
    return value


class WorkbenchServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port=8765):
        self.csrf_token = secrets.token_hex(32)
        self.review_slots = threading.BoundedSemaphore(2)
        super().__init__(("127.0.0.1", port), WorkbenchHandler)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_port}"


class WorkbenchHandler(BaseHTTPRequestHandler):
    server_version = f"ForecastReview/{__version__}"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, format, *args):
        # Never log input payloads, filenames, notes, query strings or CSRF tokens.
        return

    def _send(self, status, content, content_type="application/json; charset=utf-8", *, download=None):
        if not isinstance(content, bytes):
            content = json.dumps(content, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data: blob:; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _local_request(self):
        authorities = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        hosts = self.headers.get_all("Host", [])
        origins = self.headers.get_all("Origin", [])
        if len(hosts) != 1 or hosts[0] not in authorities:
            self._send(403, {"error": "Open the tool using its local 127.0.0.1 or localhost address."})
            return False
        if len(origins) > 1 or (origins and origins[0] not in {f"http://{a}" for a in authorities}):
            self._send(403, {"error": "Cross-origin requests are not accepted by this local tool."})
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self._send(403, {"error": "Open the local tool directly instead of from another website."})
            return False
        return True

    def do_GET(self):
        if not self._local_request():
            return
        path = urlsplit(self.path).path
        if path == "/api/example":
            self._send(200, example_request())
        elif path == "/api/experiments/example":
            self._send(200, experiment_example())
        elif path == "/api/reconcile/example":
            self._send(200, reconciliation_example())
        elif path in ASSETS:
            name, mime = ASSETS[path]
            content = Path(__file__).with_name("static").joinpath(name).read_bytes()
            if name.endswith(".html"):
                content, count = re.subn(
                    rb'(<meta name="csrf-token" content=")[^"]*(">)',
                    lambda match: match[1] + self.server.csrf_token.encode() + match[2],
                    content,
                )
                if count != 1:
                    self._send(
                        500, {"error": "The installed application page is incomplete. Reinstall the tool."}
                    )
                    return
            self._send(200, content, mime)
        elif path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        else:
            self._send(404, {"error": "This local tool does not serve that path."})

    def do_OPTIONS(self):
        self._send(403, {"error": "Cross-origin access is not enabled."})

    def do_POST(self):
        if not self._local_request():
            return
        tokens = self.headers.get_all("X-Workbench-Token", [])
        if len(tokens) != 1 or not hmac.compare_digest(tokens[0], self.server.csrf_token):
            self._send(403, {"error": "Refresh the local application before making this request."})
            return
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
            self._send(400, {"error": "A single bounded Content-Length is required."})
            return
        try:
            length = int(lengths[0])
        except ValueError:
            length = -1
        if length < 1 or length > MAX_REQUEST:
            self._send(413, {"error": "The combined request must be under 40 MiB. Use smaller extracts."})
            return
        if self.headers.get_content_type() != "application/json":
            self._send(415, {"error": "Send application/json from the local workbench."})
            return
        if not self.server.review_slots.acquire(blocking=False):
            self._send(429, {"error": "Two reviews are already running. Wait for one to finish."})
            return
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("The request was interrupted. Select the files and try again.")
            payload = load_json(raw)
            path = urlsplit(self.path).path
            if path == "/api/inspect":
                file = payload.get("file")
                if (
                    not isinstance(file, dict)
                    or "path" in file
                    or not isinstance(file.get("content_base64"), str)
                ):
                    raise ValueError("Select a file in the browser. Server file paths are not accepted.")
                self._send(
                    200,
                    inspect_table(payload.get("file"), payload.get("sheet"), payload.get("header_row", 1)),
                )
            elif path == "/api/review":
                self._send(200, review(payload))
            elif path == "/api/experiments/prepare":
                self._send(200, experiment_result(payload))
            elif path == "/api/experiments/reveal":
                self._send(200, reveal_experiment(payload.get("request"), payload.get("fingerprint")))
            elif path == "/api/experiments/transfer":
                self._send(
                    200,
                    {
                        "request": transfer_experiment(
                            payload.get("request"),
                            payload.get("fingerprint"),
                            payload.get("model_ids"),
                            payload.get("baseline_id"),
                        )
                    },
                )
            elif path == "/api/experiments/export":
                files, result = build_experiment_bundle(
                    payload.get("request"), payload.get("fingerprint"), payload.get("stage")
                )
                self._send(
                    200,
                    bundle_zip(files),
                    "application/zip",
                    download=f"forecast-experiment-{result['stage']}-{result['fingerprint'][:12]}.zip",
                )
            elif path == "/api/reconcile":
                self._send(200, reconcile(payload))
            elif path == "/api/reconcile/export":
                files, result = build_reconciliation_bundle(
                    payload.get("request"), payload.get("fingerprint"), payload.get("notes", [])
                )
                self._send(
                    200,
                    bundle_zip(files),
                    "application/zip",
                    download=f"result-reconciliation-{result['fingerprint'][:12]}.zip",
                )
            elif path == "/api/export":
                files, result = build_bundle(
                    payload.get("request"), payload.get("fingerprint"), payload.get("notes", [])
                )
                self._send(
                    200,
                    bundle_zip(files),
                    "application/zip",
                    download=f"forecast-review-{result['fingerprint'][:12]}.zip",
                )
            else:
                self._send(404, {"error": "Unknown application action."})
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
            self._send(400, {"error": str(exc) or "Check the input fields and try again."})
        except (TimeoutError, OSError):
            self._send(
                400, {"error": "The input could not be read completely. Select a stable file and try again."}
            )
        finally:
            self.server.review_slots.release()


def _resolve_files(request, base, workflow="review"):
    """CLI convenience: explicit paths become immutable byte snapshots before evaluation."""
    if workflow == "experiment":
        sources = [request]
    elif workflow == "reconcile":
        sources = [request.get("left"), request.get("right")]
        sources.extend(request[key] for key in ("left_totals", "right_totals") if request.get(key))
    else:
        sources = [request.get("actual"), *request.get("candidates", [])]
        if request.get("baseline"):
            sources.append(request["baseline"])
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("file"), dict):
            raise ValueError("Each source must declare a file object.")
        spec = source["file"]
        if "path" in spec:
            if "content_base64" in spec:
                raise ValueError("Choose a file path or embedded file content, not both.")
            path = (base / spec["path"]).resolve()
            before = path.stat()
            if not path.is_file() or before.st_size > 10 * 1024 * 1024:
                raise ValueError("Each source path must be a regular file of at most 10 MiB.")
            with path.open("rb") as stream:
                data = stream.read(10 * 1024 * 1024 + 1)
            after = path.stat()
            fields = ("st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            if len(data) > 10 * 1024 * 1024 or any(getattr(before, f) != getattr(after, f) for f in fields):
                raise ValueError("A source changed during reading. Use a stable copy.")
            source["file"] = {"name": path.name, "content_base64": base64.b64encode(data).decode()}
    return request


def main(argv=None):
    parser = argparse.ArgumentParser(description="Review your forecast files locally in a browser.")
    parser.add_argument(
        "--port", type=int, default=8765, help="Loopback port (default 8765; 0 selects a free port)"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Print the local address without opening a browser"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--review", type=Path, help="Run an explicit JSON request instead of starting the GUI")
    group.add_argument("--example", action="store_true", help="Export the invented common-sample example")
    group.add_argument("--experiment", type=Path, help="Run a monthly candidate request JSON")
    group.add_argument("--reconcile", type=Path, help="Run an additive reconciliation request JSON")
    parser.add_argument(
        "--reveal-holdout", action="store_true", help="Explicitly score the experiment holdout"
    )
    parser.add_argument(
        "--output", type=Path, help="New directory for a CLI review; existing paths are refused"
    )
    args = parser.parse_args(argv)
    try:
        if args.reveal_holdout and not args.experiment:
            raise ValueError("--reveal-holdout applies only to --experiment.")
        if args.experiment or args.reconcile:
            if not args.output:
                raise ValueError("CLI evidence requires --output with a new directory.")
            if args.output.exists() or args.output.is_symlink():
                raise FileExistsError("Choose a new output directory; existing paths are never replaced.")
            path = args.experiment or args.reconcile
            if path.stat().st_size > MAX_REQUEST:
                raise ValueError("The settings file must be under 40 MiB.")
            workflow = "experiment" if args.experiment else "reconcile"
            request = _resolve_files(load_json(path.read_bytes()), path.parent, workflow)
            if args.experiment:
                result = experiment_result(request, reveal=args.reveal_holdout)
                files, result = build_experiment_bundle(request, result["fingerprint"], result["stage"])
                selected = next(
                    (row for row in result["candidates"] if row["id"] == result["selected_on_development"]),
                    None,
                )
                attention = selected is None or (args.reveal_holdout and not selected["holdout"])
                summary = {
                    "stage": result["stage"],
                    "selected_on_development": result["selected_on_development"],
                    "coverage": result["coverage"],
                }
            else:
                result = reconcile(request)
                files, result = build_reconciliation_bundle(request, result["fingerprint"])
                summary = result["summary"]
                attention = (
                    summary["pass"] != summary["expected"]
                    or summary["group_attention"]
                    or summary["reported_totals_attention"]
                )
            write_bundle(files, args.output)
            print(
                json.dumps(
                    {
                        "output": str(args.output.absolute()),
                        "fingerprint": result["fingerprint"],
                        "attention": bool(attention),
                        **summary,
                    },
                    indent=2,
                )
            )
            return 1 if attention else 0
        if args.example or args.review:
            if not args.output:
                raise ValueError("CLI review requires --output with a new directory.")
            if args.output.exists() or args.output.is_symlink():
                raise FileExistsError("Choose a new output directory; existing paths are never replaced.")
            if args.example:
                request = example_request()
                request["accept_common_sample"] = True
            else:
                if args.review.stat().st_size > MAX_REQUEST:
                    raise ValueError("The review settings file must be under 40 MiB.")
                request = _resolve_files(load_json(args.review.read_bytes()), args.review.parent)
            result = review(request)
            files, _result = build_bundle(request, result["fingerprint"])
            write_bundle(files, args.output)
            print(
                json.dumps(
                    {
                        "output": str(args.output.absolute()),
                        "fingerprint": result["fingerprint"],
                        "comparison_ready": result["comparison_ready"],
                        **result["summary"],
                    },
                    indent=2,
                )
            )
            return 0 if result["comparison_ready"] else 1
        if args.output:
            raise ValueError("--output applies to a CLI workflow, not the browser application.")
        if not 0 <= args.port <= 65535:
            raise ValueError("Port must be between 0 and 65535.")
        try:
            server = WorkbenchServer(args.port)
        except OSError:
            if args.port == 0:
                raise
            server = WorkbenchServer(0)
        with server:
            print(f"Forecast Review is ready: {server.url}", flush=True)
            print("Selected files stay on this computer. Press Ctrl+C to close the local tool.", flush=True)
            if not args.no_browser:
                webbrowser.open(server.url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Could not complete the request: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
