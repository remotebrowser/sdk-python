from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from ._client import RemoteBrowser
from ._errors import RemoteBrowserError
from ._version import __version__

__all__ = ["main", "run"]

PROG = "remotebrowser"

DESCRIPTION = "Manage Remote Browser browsers from the command line."

EPILOG = """\
environment:
  REMOTEBROWSER_API_KEY  API key (required)
  REMOTEBROWSER_URL      base URL of the Remote Browser API (required)

The CDP endpoint printed by "connect" needs the API key in the header
"Authorization: Bearer $REMOTEBROWSER_API_KEY".
"""


def main() -> int:
    """Entry point of the `remotebrowser` executable."""
    try:
        return run(sys.argv[1:])
    except KeyboardInterrupt:
        return 130


def run(
    argv: Sequence[str],
    *,
    client_options: dict[str, Any] | None = None,
    poll_interval: float = 1.0,
) -> int:
    """Run the CLI with the given arguments and return the exit code.

    Output goes to sys.stdout and sys.stderr. `client_options` are passed to RemoteBrowser.
    """
    parser = _make_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit:
        return exit.code if isinstance(exit.code, int) else 2

    if args.command in (None, "help"):
        parser.print_help()
        return 0

    client: RemoteBrowser | None = None

    def get_client() -> RemoteBrowser:
        nonlocal client
        if client is None:
            client = RemoteBrowser(**(client_options or {}))
        return client

    cli = _Cli(get_client, json_output=args.json, poll_interval=poll_interval)
    try:
        args.handler(cli, args)
    except RemoteBrowserError as err:
        _error(str(err))
        return 1
    except ValueError as err:
        _error(str(err))
        return 2
    return 0


def _error(message: str) -> None:
    print(f"{PROG}: {message}", file=sys.stderr)


def _make_parser() -> argparse.ArgumentParser:
    # --json works before or after the command. On a subcommand it is SUPPRESS by default, so it
    # does not overwrite a --json given before the command.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print the raw JSON response")

    parser = argparse.ArgumentParser(
        prog=PROG,
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", default=False, help="print the raw JSON response")
    parser.add_argument("-v", "--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", title="commands", metavar="<command>")

    create = commands.add_parser("create", parents=[common], help="launch a browser and print its id")
    create.add_argument("--name", help="1-80 characters, random if omitted")
    create.add_argument("--description", help="up to 140 characters")
    create.add_argument("--os", help="debian-13, ubuntu-26.04, fedora-44, windows-11, ...")
    create.add_argument("--browser", help="chromium or chrome")
    create.add_argument("--screen-resolution", metavar="RES", help="full-hd, wuxga, qhd or 4k")
    create.add_argument("--screen-scale", type=int, metavar="PERCENT", help="100, 125, 150, 175 or 200")
    create.add_argument("--proxy", metavar="URL", help="http://, socks4:// or socks5:// URL")
    create.add_argument("--wait", action="store_true", help="wait until the browser is running")
    create.set_defaults(handler=_create)

    list_ = commands.add_parser(
        "list", aliases=["ls"], parents=[common], help="print the ids of the starting and running browsers"
    )
    list_.set_defaults(handler=_list)

    get = commands.add_parser("get", aliases=["info"], parents=[common], help="show the details of a browser")
    get.add_argument("id")
    get.set_defaults(handler=_get)

    for name, aliases, help in (
        ("delete", ["rm"], "terminate browsers (cannot be undone)"),
        ("suspend", [], "suspend browsers"),
        ("resume", [], "resume browsers"),
    ):
        sub = commands.add_parser(name, aliases=aliases, parents=[common], help=help)
        sub.add_argument("ids", nargs="+", metavar="id")
        sub.set_defaults(handler=_change_status, method=name)

    connect = commands.add_parser("connect", parents=[common], help="print the CDP WebSocket URL of a browser")
    connect.add_argument("id")
    connect.set_defaults(handler=_connect)

    config = commands.add_parser("config", help="show or change the configuration of a browser")
    config_commands = config.add_subparsers(dest="config_command", title="commands", metavar="<command>", required=True)
    config_get = config_commands.add_parser("get", parents=[common], help="show the configuration of a browser")
    config_get.add_argument("id")
    config_get.set_defaults(handler=_config_get)
    config_set = config_commands.add_parser("set", parents=[common], help="change the configuration of a browser")
    config_set.add_argument("id")
    proxy = config_set.add_mutually_exclusive_group(required=True)
    proxy.add_argument("--proxy", metavar="URL", help="set the proxy (closes all open connections)")
    proxy.add_argument("--no-proxy", action="store_true", help="remove the proxy")
    config_set.set_defaults(handler=_config_set)

    commands.add_parser("help", help="show this help")
    return parser


class _Cli:
    def __init__(self, client: Callable[[], RemoteBrowser], *, json_output: bool, poll_interval: float) -> None:
        self.client = client
        self.json = json_output
        self.poll_interval = poll_interval

    def out(self, text: str) -> None:
        print(text, flush=True)

    def print_json(self, data: Any) -> None:
        self.out(json.dumps(data, indent=2))

    def print_fields(self, fields: dict[str, Any]) -> None:
        width = max(len(key) for key in fields)
        for key, value in fields.items():
            text = "-" if value is None else value if isinstance(value, str) else json.dumps(value)
            self.out(f"{(key + ':').ljust(width + 1)} {text}")


def _create(cli: _Cli, args: argparse.Namespace) -> None:
    client = cli.client()
    result: Any = client.browsers.create(
        name=args.name,
        description=args.description,
        os=args.os,
        browser=args.browser,
        screen_resolution=args.screen_resolution,
        screen_scale=args.screen_scale,
        proxy=args.proxy,
    )
    if args.wait:
        while result["status"] == "starting":
            time.sleep(cli.poll_interval)
            result = client.browsers.retrieve(result["browser_id"])
        if result["status"] != "running":
            if cli.json:
                cli.print_json(result)
            raise RemoteBrowserError(f"browser {result['browser_id']} is {result['status']}")
    if cli.json:
        cli.print_json(result)
    else:
        cli.out(result["browser_id"])


def _list(cli: _Cli, args: argparse.Namespace) -> None:
    ids = cli.client().browsers.list()
    if cli.json:
        cli.print_json(ids)
    else:
        for browser_id in ids:
            cli.out(browser_id)


def _get(cli: _Cli, args: argparse.Namespace) -> None:
    browser: dict[str, Any] = dict(cli.client().browsers.retrieve(args.id))
    if cli.json:
        cli.print_json(browser)
        return
    created = browser.pop("creation_timestamp", None)
    fields = {
        "id": browser.pop("browser_id", None),
        "status": browser.pop("status", None),
        "description": browser.pop("description", None) or None,
        "os": browser.pop("os", None),
        "created": None if created is None else _iso_time(created),
        **browser,
    }
    cli.print_fields(fields)


def _iso_time(milliseconds: int) -> str:
    moment = datetime.fromtimestamp(milliseconds / 1000, tz=UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _change_status(cli: _Cli, args: argparse.Namespace) -> None:
    method: Literal["delete", "suspend", "resume"] = args.method
    action = getattr(cli.client().browsers, method)
    results: list[Any] = []
    failed = False
    for browser_id in args.ids:
        try:
            result = action(browser_id)
        except RemoteBrowserError as err:
            if len(args.ids) == 1:
                raise
            failed = True
            _error(f"{browser_id}: {err}")
            continue
        results.append(result)
        if not cli.json:
            cli.out(f"{result['browser_id']} {result['status']}")
    if cli.json:
        cli.print_json(results[0] if len(args.ids) == 1 else results)
    if failed:
        raise RemoteBrowserError(f"could not {method} every browser")


def _connect(cli: _Cli, args: argparse.Namespace) -> None:
    url = cli.client().browsers.connect_url(args.id)
    if cli.json:
        cli.print_json({"browser_id": args.id, "url": url})
    else:
        cli.out(url)


def _config_get(cli: _Cli, args: argparse.Namespace) -> None:
    _print_config(cli, cli.client().browsers.config.retrieve(args.id))


def _config_set(cli: _Cli, args: argparse.Namespace) -> None:
    proxy = None if args.no_proxy else args.proxy
    _print_config(cli, cli.client().browsers.config.update(args.id, proxy=proxy))


def _print_config(cli: _Cli, config: Any) -> None:
    if cli.json:
        cli.print_json(config)
    else:
        cli.print_fields({"id": config["browser_id"], "proxy": config["proxy"]})
