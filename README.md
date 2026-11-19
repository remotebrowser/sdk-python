# Remote Browser Python SDK

Python client for the [Remote Browser REST API](https://remotebrowser.ai/api/), with a `remotebrowser` command-line tool.

Requires Python 3.11 or later. It has no dependencies and uses the standard library's `urllib`.

## Installation

```bash
pip install remotebrowser
```

## Usage

```python
import os

from remotebrowser import RemoteBrowser

client = RemoteBrowser(
    api_key=os.environ["REMOTEBROWSER_API_KEY"],  # default, can be omitted
    base_url=os.environ["REMOTEBROWSER_URL"],  # default, can be omitted
)

config = {"os": "ubuntu-26.04", "browser": "chrome"}
browser_id = client.browsers.create(**config)["browser_id"]
browser = client.browsers.retrieve(browser_id)
print(browser["status"])  # 'starting' | 'running' | ...
```

Responses are plain dicts, typed with `TypedDict`s such as `Browser` and `BrowserStatusResponse`.

### Connect with Playwright

```python
from playwright.sync_api import sync_playwright

cdp_url = client.browsers.connect_url(browser_id)

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(cdp_url, headers=client.auth_headers)
    context = browser.contexts[0]
    page = context.new_page()
    page.goto("https://example.com")
    page.screenshot(path="example.png")
    page.close()
```

## Command-line tool

The package installs a `remotebrowser` executable, which can also run as `python -m remotebrowser`. It reads the same `REMOTEBROWSER_API_KEY` and `REMOTEBROWSER_URL` environment variables.

```bash
pipx install remotebrowser   # or: uvx remotebrowser <command>

ID=$(remotebrowser create --os ubuntu-26.04 --browser chrome --wait)
remotebrowser list
remotebrowser get $ID
remotebrowser connect $ID      # prints the CDP WebSocket URL
remotebrowser suspend $ID
remotebrowser resume $ID
remotebrowser config set $ID --proxy socks5://proxy.example:1080
remotebrowser config get $ID
remotebrowser delete $ID
```

| Command                              | Description                                        |
| ------------------------------------ | -------------------------------------------------- |
| `create [options]`                   | Launch a browser and print its id                  |
| `list`                               | Print the ids of the starting and running browsers |
| `get <id>`                           | Show the details of a browser                      |
| `delete <id>...`                     | Terminate browsers                                 |
| `suspend <id>...` / `resume <id>...` | Suspend or resume browsers                         |
| `connect <id>`                       | Print the CDP WebSocket URL                        |
| `config get <id>`                    | Show the configuration                             |
| `config set <id> --proxy <url>`      | Change the proxy                                   |
| `config set <id> --no-proxy`         | Remove the proxy                                   |

`create` takes `--name`, `--description`, `--os`, `--browser`, `--screen-resolution`, `--screen-scale`, `--proxy`, and `--wait` (wait until the browser is running). Every command takes `--json` to print the raw API response. Run `remotebrowser --help`, or `remotebrowser <command> --help`, for details.

The CDP endpoint needs the API key in the `Authorization: Bearer` header.

The exit code is 0 on success, 1 when the API call fails, and 2 for a usage error.

## API

| Method                                         | Endpoint                                                                     |
| ---------------------------------------------- | ---------------------------------------------------------------------------- |
| `client.browsers.create(**params)`             | `POST /api/v1/browsers`                                                      |
| `client.browsers.list()`                       | `GET /api/v1/browsers`                                                       |
| `client.browsers.retrieve(id)`                 | `GET /api/v1/browsers/{id}`                                                  |
| `client.browsers.delete(id)`                   | `DELETE /api/v1/browsers/{id}`                                               |
| `client.browsers.suspend(id)`                  | `POST /api/v1/browsers/{id}/suspend`                                         |
| `client.browsers.resume(id)`                   | `POST /api/v1/browsers/{id}/resume`                                          |
| `client.browsers.config.retrieve(id)`          | `GET /api/v1/browsers/{id}/config`                                           |
| `client.browsers.config.update(id, proxy=...)` | `PATCH /api/v1/browsers/{id}/config`                                         |
| `client.browsers.connect_url(id)`              | WebSocket URL for [CDP](https://chromedevtools.github.io/devtools-protocol/) |

`create` takes the keyword arguments `name`, `description`, `os`, `browser`, `screen_resolution`, `screen_scale`, and `proxy`. Each one left out takes the server's default. `config.update` takes `proxy=None` to connect directly again.

Every method also takes the request options `timeout` (seconds), `max_retries`, and `extra_headers` as keyword arguments.

```python
client.browsers.list(timeout=5)
```

## Handling errors

Failed requests raise a subclass of `APIError`, which has `status`, `body` (the parsed response body), and `headers`.

```python
import remotebrowser

try:
    client.browsers.resume(browser_id)
except remotebrowser.ConflictError as err:
    print("Browser is", err.body["status"])
```

| Status code | Error type                 |
| ----------- | -------------------------- |
| 400         | `BadRequestError`          |
| 401         | `AuthenticationError`      |
| 403         | `PermissionDeniedError`    |
| 404         | `NotFoundError`            |
| 409         | `ConflictError`            |
| 422         | `UnprocessableEntityError` |
| 429         | `RateLimitError`           |
| >=500       | `InternalServerError`      |
| N/A         | `APIConnectionError`       |

A timeout raises `APIConnectionTimeoutError`. A missing API key or base URL raises `RemoteBrowserError`, the base class of all of them.

## Retries and timeouts

Connection errors, 408, 429, and 5xx responses are retried 2 times by default, with exponential backoff. The `Retry-After` header is respected. 409 is not retried because it means the browser is in the wrong state.

Each request times out after 60 seconds without a response by default.

```python
client = RemoteBrowser(max_retries=0, timeout=20)
```
