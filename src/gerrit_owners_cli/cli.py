from __future__ import annotations

import argparse
import base64
import configparser
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class OwnersError(RuntimeError):
    """A user-facing configuration or API error."""


def _git_config(name: str, cwd: Path) -> str | None:
    result = subprocess.run(
        ["git", "config", "--get", name],
        cwd=cwd,
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _git_root(path: Path) -> Path:
    start = path if path.is_dir() else path.parent
    while not start.exists() and start != start.parent:
        start = start.parent

    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise OwnersError("path must be inside a Git repository") from exc
    return Path(result.stdout.strip()).resolve()


def _repository_path(file_path: str) -> tuple[Path, str]:
    candidate = Path(file_path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = candidate.resolve()
    root = _git_root(candidate)

    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise OwnersError("file path must be inside the Git repository") from exc
    if not relative.parts:
        raise OwnersError("a file path is required")
    return root, relative.as_posix()


def _project(root: Path) -> str:
    gitreview = root / ".gitreview"
    if not gitreview.is_file():
        raise OwnersError(f"{gitreview} was not found")

    config = configparser.ConfigParser()
    config.read(gitreview)
    project = config.get("gerrit", "project", fallback="").strip()
    if not project:
        raise OwnersError(f"project is missing in {gitreview}")
    return project.removesuffix(".git").lstrip("/")


def _credentials(root: Path, host: str) -> tuple[str, str]:
    prompt = f"protocol=https\nhost={host}\n\n"
    try:
        result = subprocess.run(
            ["git", "credential", "fill"],
            cwd=root,
            capture_output=True,
            check=True,
            input=prompt,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise OwnersError("Git credential helper could not provide credentials") from exc

    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value

    username = values.get("username") or _git_config("gitreview.username", root)
    password = values.get("password")
    if not username or not password:
        raise OwnersError(
            "credentials are missing; configure gitreview.username and a Git credential helper"
        )
    return username, password


def build_api_url(host: str, project: str, branch: str, file_path: str) -> str:
    return (
        f"https://{host}/a/projects/{quote(project, safe='')}"
        f"/branches/{quote(branch, safe='')}/code_owners/{quote(file_path, safe='')}"
    )


def build_account_url(host: str, account_id: int) -> str:
    return f"https://{host}/a/accounts/{quote(str(account_id), safe='')}"


def _parse_response(raw: str) -> dict[str, Any]:
    if raw.startswith(")]}'"):
        _, separator, raw = raw.partition("\n")
        if not separator:
            raise OwnersError("Gerrit returned an invalid response prefix")
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OwnersError("Gerrit returned invalid JSON") from exc
    if not isinstance(response, dict):
        raise OwnersError("Gerrit returned an unexpected response")
    return response


def extract_owner_groups(response: dict[str, Any]) -> list[str]:
    groups: list[str] = []
    seen: set[str] = set()

    def visit(imports: list[dict[str, Any]]) -> None:
        for imported in imports:
            project = imported.get("project")
            path = imported.get("path")
            if project and path:
                group = f"{project}:{path}"
                if group not in seen:
                    seen.add(group)
                    groups.append(group)
            visit(imported.get("imports", []))

    for config in response.get("code_owner_configs", []):
        visit(config.get("imports", []))
    return groups


def _fetch_json(
    url: str,
    username: str,
    password: str,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Basic {token}",
        },
    )
    try:
        with opener(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raise OwnersError(f"Gerrit API returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise OwnersError(f"Gerrit API request failed: {exc.reason}") from exc
    return _parse_response(raw)


def fetch_owner_response(
    url: str,
    username: str,
    password: str,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    return _fetch_json(url, username, password, opener)


def fetch_account_response(
    host: str,
    account_id: int,
    username: str,
    password: str,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    return _fetch_json(build_account_url(host, account_id), username, password, opener)


def _owner_request_details(file_path: str, branch: str) -> tuple[str, str, str, str]:
    root, repository_path = _repository_path(file_path)
    host = _git_config("gitreview.hostname", root)
    if not host:
        raise OwnersError("gitreview.hostname is not configured")
    project = _project(root)
    username, password = _credentials(root, host)
    url = build_api_url(host, project, branch, repository_path)
    return host, url, username, password


def lookup_owner_response(file_path: str, branch: str) -> dict[str, Any]:
    _, url, username, password = _owner_request_details(file_path, branch)
    return fetch_owner_response(url, username, password)


def extract_account_ids(response: dict[str, Any]) -> list[int]:
    account_ids: list[int] = []
    seen: set[int] = set()
    for owner in response.get("code_owners", []):
        account_id = owner.get("account", {}).get("_account_id")
        if isinstance(account_id, int) and account_id not in seen:
            seen.add(account_id)
            account_ids.append(account_id)
    return account_ids


def resolve_accounts(
    response: dict[str, Any],
    host: str,
    username: str,
    password: str,
    opener: Callable[..., Any] = urlopen,
) -> list[dict[str, Any]]:
    accounts = []
    for account_id in extract_account_ids(response):
        try:
            account = fetch_account_response(host, account_id, username, password, opener)
        except OwnersError:
            account = {"_account_id": account_id}
        accounts.append(account)
    return accounts


def format_owner_summary(response: dict[str, Any], accounts: list[dict[str, Any]]) -> str:
    lines = ["Owner groups:"]
    groups = extract_owner_groups(response)
    lines.extend(f"- {group}" for group in groups or ["none"])
    lines.append("")
    lines.append("Code owners:")
    for account in accounts or [{"_account_id": "none"}]:
        account_id = account.get("_account_id")
        name = account.get("name") or account.get("display_name")
        email = account.get("email")
        if name and email:
            identity = f"{name} <{email}>"
        elif name:
            identity = str(name)
        else:
            identity = f"account {account_id}"
        lines.append(f"- {identity}")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print Gerrit Code Owners groups for a repository file"
    )
    parser.add_argument("path", help="repository-relative path to the file")
    parser.add_argument(
        "--branch",
        default="master",
        help="Gerrit branch to query (default: master)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the complete JSON response from Gerrit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        host, url, username, password = _owner_request_details(args.path, args.branch)
        response = fetch_owner_response(url, username, password)
    except OwnersError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return 0

    accounts = resolve_accounts(response, host, username, password)
    print(format_owner_summary(response, accounts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
