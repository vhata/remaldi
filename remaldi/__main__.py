import argparse
import asyncio
import json
import os
import sys
import urllib.parse

from .client import call
from .errors import ControlError
from .protocol import JsonObject
from .service import serve


def json_object(value: str) -> JsonObject:
    try:
        result = json.loads(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if not isinstance(result, dict):
        raise argparse.ArgumentTypeError("Expected a JSON object")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Local Vivaldi control client and on-demand daemon"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "stop", "serve"):
        commands.add_parser(name)
    state = commands.add_parser("state")
    state.add_argument("--refresh", action="store_true")
    raw = commands.add_parser("raw")
    raw.add_argument("method")
    raw.add_argument("--params", type=json_object, default={})
    raw.add_argument("--target")
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("expression")
    evaluate.add_argument("--target")
    evaluate.add_argument("--await-promise", action="store_true")
    evaluate.add_argument("--return-by-value", action="store_true")
    workspace = commands.add_parser("workspace")
    workspace_commands = workspace.add_subparsers(dest="action", required=True)
    switch = workspace_commands.add_parser("switch")
    switch.add_argument("workspace_id")
    switch.add_argument("--window-id", type=int)
    args = parser.parse_args()
    try:
        if args.command == "serve":
            endpoint = os.environ.get("REMALDI_ENDPOINT", "http://127.0.0.1:9222")
            url = urllib.parse.urlsplit(endpoint)
            if (
                url.scheme != "http"
                or url.hostname not in {"127.0.0.1", "localhost", "::1"}
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ControlError(
                    "invalid_endpoint", "REMALDI_ENDPOINT must be a loopback HTTP URL."
                )
            asyncio.run(serve(endpoint))
            return 0
        operation = args.command
        params: JsonObject = {}
        if operation == "state":
            params = {"refresh": args.refresh}
        elif operation == "raw":
            params = {
                "method": args.method,
                "params": args.params,
                "target": args.target,
            }
        elif operation == "evaluate":
            operation = "raw"
            params = {
                "method": "Runtime.evaluate",
                "params": {
                    "expression": args.expression,
                    "awaitPromise": args.await_promise,
                    "returnByValue": args.return_by_value,
                },
                "target": args.target,
            }
        elif operation == "workspace":
            operation = "workspace.switch"
            params = {"workspace_id": args.workspace_id, "window_id": args.window_id}
        result = call(operation, params)
        print(json.dumps(result))
        return 0
    except ControlError as exc:
        print(json.dumps({"error": exc.as_dict()}), file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(
            json.dumps({"error": {"code": "client_error", "message": str(exc)}}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
