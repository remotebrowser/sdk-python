from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass

import pytest
from conftest import FakeServer

from remotebrowser._cli import run


@dataclass
class Result:
    code: int
    out: str
    err: str


@pytest.fixture
def cli(server: FakeServer, capsys: pytest.CaptureFixture[str]):
    options = {"api_key": "sk", "base_url": server.url, "max_retries": 0}

    def invoke(*argv: str) -> Result:
        code = run(argv, client_options=options, poll_interval=0)
        captured = capsys.readouterr()
        return Result(code, captured.out, captured.err)

    return invoke


def calls(server: FakeServer) -> list[str]:
    return [f"{r.method} {r.path}" for r in server.requests]


base = "/api/v1/browsers"


def test_help_needs_no_credentials(capsys: pytest.CaptureFixture[str]) -> None:
    for argv in ([], ["help"], ["--help"]):
        assert run(argv, client_options={}) == 0
        assert "usage: remotebrowser" in capsys.readouterr().out


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "0.1.0"


def test_create_sends_the_options_and_prints_the_id(cli, server: FakeServer) -> None:
    server.respond(200, {"browser_id": "B1", "status": "starting"})
    result = cli("create", "--os", "ubuntu-26.04", "--screen-scale", "150", "--proxy", "http://p:1")
    assert result.code == 0
    assert result.out == "B1\n"
    assert json.loads(server.requests[0].body) == {
        "os": "ubuntu-26.04",
        "screen_scale": 150,
        "proxy": "http://p:1",
    }


def test_create_wait_polls_until_running(cli, server: FakeServer) -> None:
    server.respond(200, {"browser_id": "B1", "status": "starting"})
    server.respond(200, {"browser_id": "B1", "status": "starting"})
    server.respond(200, {"browser_id": "B1", "status": "running", "os": "debian-13"})
    result = cli("create", "--wait")
    assert result.code == 0
    assert calls(server) == [f"POST {base}", f"GET {base}/B1", f"GET {base}/B1"]
    assert result.out == "B1\n"


def test_create_wait_fails_when_the_browser_does_not_run(cli, server: FakeServer) -> None:
    server.respond(200, {"browser_id": "B1", "status": "starting"})
    server.respond(200, {"browser_id": "B1", "status": "error"})
    result = cli("create", "--wait")
    assert result.code == 1
    assert "B1 is error" in result.err


def test_list_prints_one_id_per_line_or_json(cli, server: FakeServer) -> None:
    server.respond(200, ["B1", "B2"])
    server.respond(200, ["B1"])
    server.respond(200, ["B1"])
    assert cli("list").out == "B1\nB2\n"
    assert cli("ls", "--json").out == '[\n  "B1"\n]\n'
    assert cli("--json", "list").out == '[\n  "B1"\n]\n'


def test_get_shows_the_browser_details(cli, server: FakeServer) -> None:
    server.respond(
        200, {"browser_id": "B1", "status": "running", "description": "", "os": "fedora-44", "creation_timestamp": 0}
    )
    out = cli("info", "B1").out
    assert out == (
        "id:          B1\n"
        "status:      running\n"
        "description: -\n"
        "os:          fedora-44\n"
        "created:     1970-01-01T00:00:00.000Z\n"
    )


def test_delete_suspend_and_resume_accept_several_ids(cli, server: FakeServer) -> None:
    server.respond(200, {"browser_id": "B1", "status": "terminated"})
    server.respond(200, {"browser_id": "B2", "status": "terminated"})
    server.respond(200, {"browser_id": "B3", "status": "suspended"})
    server.respond(200, {"browser_id": "B3", "status": "running"})
    out = cli("delete", "B1", "B2").out + cli("suspend", "B3").out + cli("resume", "B3").out
    assert calls(server) == [
        f"DELETE {base}/B1",
        f"DELETE {base}/B2",
        f"POST {base}/B3/suspend",
        f"POST {base}/B3/resume",
    ]
    assert out == "B1 terminated\nB2 terminated\nB3 suspended\nB3 running\n"


def test_several_ids_with_json_print_an_array(cli, server: FakeServer) -> None:
    server.respond(200, {"browser_id": "B1", "status": "running"})
    server.respond(200, {"browser_id": "B2", "status": "running"})
    result = cli("resume", "B1", "B2", "--json")
    assert json.loads(result.out) == [
        {"browser_id": "B1", "status": "running"},
        {"browser_id": "B2", "status": "running"},
    ]


def test_delete_keeps_going_when_one_browser_fails(cli, server: FakeServer) -> None:
    server.respond(404, {"error": "Browser not found."})
    server.respond(200, {"browser_id": "B2", "status": "terminated"})
    result = cli("rm", "B1", "B2")
    assert result.code == 1
    assert result.out == "B2 terminated\n"
    assert "B1: 404 Browser not found." in result.err
    assert "could not delete every browser" in result.err


def test_connect_prints_the_cdp_url_without_a_request(cli, server: FakeServer) -> None:
    result = cli("connect", "B1")
    assert result.out == f"ws://{server.url.removeprefix('http://')}/api/v1/browsers/B1/cdp\n"
    assert server.requests == []


def test_config_get_and_set(cli, server: FakeServer) -> None:
    server.respond(200, {"browser_id": "B1", "proxy": None})
    server.respond(200, {"browser_id": "B1", "proxy": "socks5://p:1080"})
    out = cli("config", "get", "B1").out + cli("config", "set", "B1", "--proxy", "socks5://p:1080").out
    assert server.requests[1].method == "PATCH"
    assert server.requests[1].body == b'{"proxy": "socks5://p:1080"}'
    assert out == "id:    B1\nproxy: -\nid:    B1\nproxy: socks5://p:1080\n"


def test_config_set_no_proxy_sends_null(cli, server: FakeServer) -> None:
    server.respond(200, {"browser_id": "B1", "proxy": None})
    cli("config", "set", "B1", "--no-proxy")
    assert server.requests[0].body == b'{"proxy": null}'


@pytest.mark.parametrize(
    "argv",
    [
        ["frobnicate"],
        ["get"],
        ["get", "a", "b"],
        ["list", "--os", "x"],
        ["create", "--bogus"],
        ["create", "--screen-scale", "abc"],
        ["config"],
        ["config", "del", "B1"],
        ["config", "set", "B1"],
        ["config", "set", "B1", "--proxy", "http://p:1", "--no-proxy"],
    ],
)
def test_usage_errors_exit_with_2(cli, server: FakeServer, argv: list[str]) -> None:
    result = cli(*argv)
    assert result.code == 2
    assert "usage:" in result.err
    assert server.requests == []


def test_api_errors_exit_with_1(cli, server: FakeServer) -> None:
    server.respond(409, {"error": "Only a suspended browser can be resumed."})
    result = cli("resume", "B1")
    assert result.code == 1
    assert result.err == "remotebrowser: 409 Only a suspended browser can be resumed.\n"


def test_missing_credentials_exit_with_1(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["list"], client_options={"api_key": ""}) == 1
    assert "REMOTEBROWSER_API_KEY" in capsys.readouterr().err


def test_runs_as_a_module(server: FakeServer) -> None:
    server.respond(200, ["B1"])
    env = {"REMOTEBROWSER_API_KEY": "sk", "REMOTEBROWSER_URL": server.url}
    result = subprocess.run(
        [sys.executable, "-m", "remotebrowser", "list"], capture_output=True, text=True, env=env, check=False
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "B1\n", "")
