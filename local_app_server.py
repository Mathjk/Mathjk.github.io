#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import logging
import mimetypes
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT_DIR = Path(__file__).resolve().parent
SITE_ROOT = Path(
    os.environ.get("MYWEB_SITE_ROOT", ROOT_DIR if (ROOT_DIR / "src" / "data").exists() else ROOT_DIR / "devportfolio")
).resolve()
APP_ROOT = Path(os.environ.get("MYWEB_APP_ROOT", ROOT_DIR / "myapp")).resolve()
WEBSITE_ROOT = Path(os.environ.get("MYWEB_WEBSITE_ROOT", SITE_ROOT / "dist")).resolve()
METADATA_PATH = ROOT_DIR / "app_metadata.json"
TOOL_CONFIG_PATH = Path(os.environ.get("MYWEB_TOOL_CONFIG", ROOT_DIR / "local_tools.json")).resolve()
TOOL_PATHS_PATH = Path(os.environ.get("MYWEB_TOOL_PATHS", ROOT_DIR / ".local" / "tool_paths.json")).resolve()
RESOURCE_CONFIG_PATH = Path(
    os.environ.get("MYWEB_RESOURCE_CONFIG", SITE_ROOT / "src" / "data" / "resources.json")
).resolve()
NOTES_ROOT = Path(os.environ.get("MYWEB_NOTES_ROOT", SITE_ROOT / "src" / "content" / "notes")).resolve()
TOKEN_PATH = Path(os.environ.get("MYWEB_TOKEN_PATH", ROOT_DIR / ".local" / "editor-token")).resolve()
HOST = os.environ.get("MYWEB_HOST", "127.0.0.1")
PORT = int(os.environ.get("MYWEB_PORT", "3939"))
LOG_PATH = ROOT_DIR / "local_app_server.log"


logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8",
)
logger = logging.getLogger("myweb.local_app_server")


def read_json_file(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to read JSON from %s", path)
        return fallback


def write_json_file(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def ensure_within_root(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT_DIR.resolve())
    except ValueError as exc:
        raise ValueError(f"path is outside project root: {path}") from exc


def get_editor_token() -> str:
    env_token = os.environ.get("MYWEB_EDITOR_TOKEN", "").strip()
    if env_token:
        return env_token

    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not TOKEN_PATH.exists():
        TOKEN_PATH.write_text(secrets.token_urlsafe(32) + "\n", encoding="utf-8")
        try:
            TOKEN_PATH.chmod(0o600)
        except Exception:
            logger.exception("Failed to chmod token file")
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def is_local_host() -> bool:
    return HOST in {"127.0.0.1", "localhost", "::1"}


def extract_auth_token(handler: BaseHTTPRequestHandler) -> str:
    direct = handler.headers.get("X-MyWeb-Token", "").strip()
    if direct:
        return direct
    authorization = handler.headers.get("Authorization", "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def is_authenticated(handler: BaseHTTPRequestHandler) -> bool:
    return bool(is_local_host() and secrets.compare_digest(extract_auth_token(handler), get_editor_token()))


def require_auth(handler: BaseHTTPRequestHandler) -> None:
    if not is_authenticated(handler):
        raise PermissionError("local editor token required")


def parse_request_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    payload = json.loads(handler.rfile.read(length) or b"{}")
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    return payload


def choose_local_path(kind: str, title: str = "", initial_dir: str = "") -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise RuntimeError("Python tkinter is required for the local path picker") from exc

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        options = {"title": title or "Choose local path"}
        if initial_dir:
            options["initialdir"] = initial_dir
        if kind == "file":
            selected = filedialog.askopenfilename(**options)
        else:
            selected = filedialog.askdirectory(**options)
    finally:
        root.destroy()

    if not selected:
        raise ValueError("path selection cancelled")
    return selected


def load_metadata() -> dict:
    if not METADATA_PATH.exists():
        return {}
    try:
        return json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load metadata from %s", METADATA_PATH)
        return {}


def load_tool_config() -> dict:
    if not TOOL_CONFIG_PATH.exists():
        return {"tools": []}
    try:
        payload = json.loads(TOOL_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load tool config from %s", TOOL_CONFIG_PATH)
        return {"tools": []}

    if isinstance(payload, list):
        return {"tools": payload}
    if isinstance(payload, dict):
        payload.setdefault("tools", [])
        return payload
    return {"tools": []}


def load_tool_path_overrides() -> dict:
    payload = read_json_file(TOOL_PATHS_PATH, {})
    return payload if isinstance(payload, dict) else {}


def current_platform_key() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def split_tags(value: str | list | None) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not value:
        return []
    return [item.strip() for item in re.split(r"[&,/，、]+", str(value)) if item.strip()]


def infer_group_name(file_name: str) -> str:
    stem = Path(file_name).stem
    stem = re.sub(r"([_-]?v\d+)$", "", stem, flags=re.IGNORECASE)
    return stem or Path(file_name).stem


def extract_version_score(file_name: str) -> tuple:
    match = re.search(r"v(\d+)", file_name, flags=re.IGNORECASE)
    if match:
      return (0, -int(match.group(1)), file_name.lower())
    return (1, 0, file_name.lower())


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip())
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "app"


def is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_local_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def normalize_local_url(value: str) -> str:
    clean_value = str(value or "").strip()
    if clean_value and not is_local_url(clean_value):
        raise ValueError("tool URLs must be local http(s) URLs")
    return clean_value


def normalize_port(value) -> int | None:
    if value in (None, ""):
        return None
    port = int(str(value).strip())
    if port < 1 or port > 65535:
        raise ValueError("port must be between 1 and 65535")
    return port


def parse_command(value, platform: str) -> list[str]:
    if isinstance(value, list):
        command = [str(part) for part in value if str(part).strip()]
    else:
        raw = str(value or "").strip()
        if not raw:
            return []
        command = shlex.split(raw, posix=platform != "windows")
    if not command:
        return []
    return command


def action_environment(action: dict) -> dict | None:
    raw_env = action.get("env")
    if not isinstance(raw_env, dict):
        return None
    env = os.environ.copy()
    for key, value in raw_env.items():
        clean_key = str(key).strip()
        clean_value = str(value).strip()
        if clean_key and clean_value:
            env[clean_key] = clean_value
    return env


def load_resources() -> list[dict]:
    payload = read_json_file(RESOURCE_CONFIG_PATH, [])
    return payload if isinstance(payload, list) else []


def normalize_resource(payload: dict) -> dict:
    name = str(payload.get("name", "")).strip()
    if not name:
        raise ValueError("resource name is required")

    resource_id = slugify(str(payload.get("id") or name))
    links = []
    for link in payload.get("links", []):
        if not isinstance(link, dict):
            continue
        label = str(link.get("label", "")).strip()
        href = str(link.get("href", "")).strip()
        if not label or not href:
            continue
        if not is_http_url(href):
            raise ValueError("resource links must be http(s) URLs")
        links.append({"label": label, "href": href})

    skills = split_tags(payload.get("skills"))
    return {
        "id": resource_id,
        "name": name,
        "description": str(payload.get("description", "")).strip(),
        "links": links,
        "skills": skills,
    }


def upsert_resource(payload: dict) -> dict:
    ensure_within_root(RESOURCE_CONFIG_PATH)
    resource = normalize_resource(payload)
    resources = load_resources()
    next_resources = [item for item in resources if item.get("id") != resource["id"]]
    next_resources.append(resource)
    write_json_file(RESOURCE_CONFIG_PATH, next_resources)
    return resource


def delete_resource(resource_id: str) -> None:
    clean_id = slugify(resource_id)
    resources = load_resources()
    next_resources = [item for item in resources if item.get("id") != clean_id]
    write_json_file(RESOURCE_CONFIG_PATH, next_resources)


def normalize_tool(payload: dict) -> dict:
    title = str(payload.get("title", "")).strip()
    if not title:
        raise ValueError("tool title is required")

    tool_id = slugify(str(payload.get("id") or title)).lower()
    kind = str(payload.get("kind") or "app").strip()
    if kind not in {"app", "web", "service"}:
        raise ValueError("tool kind must be app, web, or service")

    tool = {
        "id": tool_id,
        "title": title,
        "description": str(payload.get("description", "")).strip(),
        "kind": kind,
        "tags": split_tags(payload.get("tags")),
    }

    port = normalize_port(payload.get("port"))
    urls = {}
    raw_urls = payload.get("urls")
    if isinstance(raw_urls, dict):
        for platform in ("windows", "linux", "mac", "default"):
            platform_url = normalize_local_url(raw_urls.get(platform, ""))
            if platform_url:
                urls[platform] = platform_url
    for platform in ("windows", "linux", "mac", "default"):
        platform_url = normalize_local_url(payload.get(f"{platform}Url", ""))
        if platform_url:
            urls[platform] = platform_url

    url = normalize_local_url(payload.get("url", ""))
    if not url and port:
        url = f"http://127.0.0.1:{port}/"
    if url:
        tool["url"] = url
    if urls:
        tool["urls"] = urls
    if port:
        tool["port"] = port

    launch = {}
    for platform in ("windows", "linux", "mac"):
        action = {}
        cwd_value = str(payload.get(f"{platform}Cwd", "")).strip()
        if cwd_value:
            action["cwd"] = cwd_value
        path_value = str(payload.get(f"{platform}Path", "")).strip()
        if path_value:
            action["path"] = path_value
        command = parse_command(payload.get(f"{platform}Command"), platform)
        if command:
            action["command"] = command
        if action.get("path") or action.get("command"):
            launch[platform] = action
    if launch:
        tool["launch"] = launch

    backend = {}
    for platform in ("windows", "linux", "mac"):
        action = {}
        cwd_value = str(payload.get(f"{platform}Cwd", "")).strip()
        if cwd_value:
            action["cwd"] = cwd_value
        python_value = str(payload.get(f"{platform}Python", "")).strip()
        if python_value:
            action["python"] = python_value
        if action.get("python"):
            backend[platform] = action
    if backend:
        tool["backend"] = backend

    delay = payload.get("openDelaySeconds")
    if delay not in (None, ""):
        tool["openDelaySeconds"] = float(delay)

    if not tool.get("url") and not tool.get("launch") and not tool.get("backend"):
        raise ValueError("tool needs a local URL, port, launch path, command, or backend script")

    return tool


def upsert_tool(payload: dict) -> dict:
    ensure_within_root(TOOL_CONFIG_PATH)
    tool = normalize_tool(payload)
    config = load_tool_config()
    config["tools"] = [item for item in config.get("tools", []) if item.get("id") != tool["id"]]
    config["tools"].append(tool)
    write_json_file(TOOL_CONFIG_PATH, config)
    return tool


def read_target_value(tool: dict, target: str) -> str:
    cursor = tool
    for part in target.split("."):
        if not isinstance(cursor, dict):
            return ""
        cursor = cursor.get(part)
    return str(cursor or "")


def validate_path_option_target(target: str) -> tuple[str, str, str]:
    parts = target.split(".")
    if len(parts) != 4 or parts[0] not in {"backend", "launch"} or parts[2] != "env":
        raise ValueError("unsupported path option target")
    block, platform, _, env_key = parts
    if platform not in {"windows", "linux", "mac", "default"}:
        raise ValueError("unsupported path option platform")
    if not re.fullmatch(r"[A-Z0-9_]+", env_key):
        raise ValueError("unsupported environment variable name")
    return block, platform, env_key


def write_target_value(tool: dict, target: str, value: str) -> None:
    block, platform, env_key = validate_path_option_target(target)

    action = tool.setdefault(block, {}).setdefault(platform, {})
    action.setdefault("env", {})[env_key] = value


def declared_path_option_targets(tool: dict) -> set[str]:
    options = tool.get("pathOptions") if isinstance(tool.get("pathOptions"), list) else []
    return {
        str(option.get("target", "")).strip()
        for option in options
        if isinstance(option, dict) and str(option.get("target", "")).strip()
    }


def apply_tool_path_overrides(tool: dict) -> dict:
    hydrated_tool = copy.deepcopy(tool)
    tool_id = str(hydrated_tool.get("id", "")).strip()
    overrides = load_tool_path_overrides().get(tool_id, {})
    if not isinstance(overrides, dict):
        return hydrated_tool

    declared_targets = declared_path_option_targets(hydrated_tool)
    for target, value in overrides.items():
        target = str(target).strip()
        value = str(value).strip()
        if not target or target not in declared_targets or not value:
            continue
        try:
            write_target_value(hydrated_tool, target, value)
        except ValueError:
            logger.warning("Ignoring invalid local tool path target: %s", target)
    return hydrated_tool


def write_tool_path_override(tool_id: str, target: str, value: str) -> None:
    validate_path_option_target(target)
    overrides = load_tool_path_overrides()
    tool_overrides = overrides.setdefault(tool_id, {})
    if not isinstance(tool_overrides, dict):
        tool_overrides = {}
        overrides[tool_id] = tool_overrides
    tool_overrides[target] = value
    write_json_file(TOOL_PATHS_PATH, overrides)


def update_tool_path_option(payload: dict) -> dict:
    tool_id = str(payload.get("id", "")).removeprefix("config:")
    target = str(payload.get("target", "")).strip()
    value = str(payload.get("value", "")).strip()
    if not tool_id or not target or not value:
        raise ValueError("tool id, target, and value are required")

    config = load_tool_config()
    for tool in config.get("tools", []):
        if not isinstance(tool, dict) or tool.get("id") != tool_id:
            continue
        options = tool.get("pathOptions") if isinstance(tool.get("pathOptions"), list) else []
        if not any(isinstance(option, dict) and option.get("target") == target for option in options):
            raise ValueError("path option is not declared for this tool")
        write_tool_path_override(tool_id, target, value)
        return apply_tool_path_overrides(tool)

    raise FileNotFoundError(tool_id)


def delete_configured_tool(tool_id: str) -> None:
    clean_id = tool_id.removeprefix("config:")
    config = load_tool_config()
    config["tools"] = [item for item in config.get("tools", []) if item.get("id") != clean_id]
    write_json_file(TOOL_CONFIG_PATH, config)


def yaml_string(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def create_note(payload: dict) -> dict:
    ensure_within_root(NOTES_ROOT)
    title = str(payload.get("title", "")).strip()
    if not title:
        raise ValueError("note title is required")

    slug = slugify(str(payload.get("slug") or title)).lower()
    summary = str(payload.get("summary", "")).strip()
    body = str(payload.get("body", "")).strip() or "待补充。"
    tags = split_tags(payload.get("tags"))
    date = str(payload.get("date", "")).strip() or time.strftime("%Y-%m-%d")
    target = (NOTES_ROOT / f"{slug}.md").resolve()
    try:
        target.relative_to(NOTES_ROOT)
    except ValueError as exc:
        raise ValueError("note path escapes notes root") from exc
    if target.exists() and not payload.get("overwrite"):
        raise FileExistsError(slug)

    frontmatter = [
        "---",
        f"title: {yaml_string(title)}",
        f"date: {yaml_string(date)}",
        f"summary: {yaml_string(summary)}",
        f"tags: {json.dumps(tags, ensure_ascii=False)}",
        "---",
        "",
        body,
        "",
    ]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(frontmatter), encoding="utf-8")
    return {"slug": slug, "path": str(target)}


def scan_apps() -> list[dict]:
    metadata = load_metadata()
    grouped: dict[tuple[str, str], list[Path]] = {}

    if APP_ROOT.exists():
        for file_path in APP_ROOT.rglob("*.exe"):
            if not file_path.is_file():
                continue
            relative_parent = file_path.parent.relative_to(APP_ROOT).as_posix()
            group_name = infer_group_name(file_path.name)
            grouped.setdefault((relative_parent, group_name.lower()), []).append(file_path)

    apps = []
    for (relative_parent, group_key), files in sorted(grouped.items()):
        files = sorted(files, key=lambda item: extract_version_score(item.name))
        group_name = infer_group_name(files[0].name)
        meta_key = f"{relative_parent}/{group_name}".strip("/") if relative_parent else group_name
        meta = metadata.get(meta_key, {}) or metadata.get(group_name, {})

        versions = [file.name for file in files]
        title = meta.get("title") or group_name
        slogan = meta.get("slogan") or f"{title} 本地工具"
        kind_name = meta.get("kind_name") or "本地应用"
        app_id = meta.get("id") or slugify(meta_key)
        base_dir = f"myapp/{relative_parent}".strip("/") if relative_parent else "myapp"

        apps.append(
            {
                "id": app_id,
                "title": title,
                "slogan": slogan,
                "kind_name": kind_name,
                "entryType": "localApp",
                "pathMode": "service",
                "baseDir": base_dir,
                "versions": versions,
                "defaultVersion": versions[0],
            }
        )

    logger.info("Scanned apps: count=%s root=%s", len(apps), APP_ROOT)
    return apps


def scanned_apps_as_tools() -> list[dict]:
    tools = []
    for app in scan_apps():
        tools.append(
            {
                "id": f"scan:{app['id']}",
                "source": "scan",
                "kind": "app",
                "title": app["title"],
                "description": app["slogan"],
                "tags": split_tags(app.get("kind_name")),
                "platforms": ["windows", "linux"],
                "canLaunch": True,
                "versions": app["versions"],
                "defaultVersion": app["defaultVersion"],
                "pathMode": app["pathMode"],
                "baseDir": app["baseDir"],
            }
        )
    return tools


def select_platform_action(block: dict | None) -> dict:
    if not isinstance(block, dict):
        return {}

    platform = current_platform_key()
    actions = block.get("actions")
    if isinstance(actions, dict):
        action = actions.get(platform) or actions.get("default")
        return action if isinstance(action, dict) else {}

    launch = block.get("launch")
    if isinstance(launch, dict):
        action = launch.get(platform) or launch.get("default")
        return action if isinstance(action, dict) else {}

    action = block.get(platform) or block.get("default")
    if isinstance(action, dict):
        return action

    if any(key in block for key in ("path", "command", "python")):
        return block

    return {}


def select_backend_action(tool: dict) -> dict:
    backend = tool.get("backend")
    if isinstance(backend, dict):
        action = backend.get(current_platform_key()) or backend.get("default")
        return action if isinstance(action, dict) else {}
    return {}


def select_tool_url(tool: dict) -> str | None:
    urls = tool.get("urls")
    if isinstance(urls, dict):
        url = urls.get(current_platform_key()) or urls.get("default")
        if url:
            return str(url)
    url = tool.get("url")
    return str(url) if url else None


def configured_tools_as_public() -> list[dict]:
    config = load_tool_config()
    tools = []
    for raw_tool in config.get("tools", []):
        if not isinstance(raw_tool, dict) or not raw_tool.get("id"):
            continue

        tool = apply_tool_path_overrides(raw_tool)
        launch_action = select_platform_action(tool)
        backend_action = select_backend_action(tool)
        platforms = []
        for key in ("windows", "linux", "mac", "default"):
            if key in raw_tool or key in (raw_tool.get("launch") or {}) or key in (raw_tool.get("backend") or {}):
                platforms.append(key)

        tools.append(
            {
                "id": f"config:{raw_tool['id']}",
                "source": "config",
                "kind": tool.get("kind", "app"),
                "title": tool.get("title") or tool["id"],
                "description": tool.get("description", ""),
                "tags": split_tags(tool.get("tags")),
                "url": select_tool_url(tool),
                "port": tool.get("port"),
                "platforms": platforms,
                "canLaunch": bool(launch_action or backend_action),
                "hasBackend": bool(backend_action),
                "openDelaySeconds": tool.get("openDelaySeconds", 1),
                "pathOptions": [
                    {
                        "label": option.get("label", "选择路径"),
                        "kind": option.get("kind", "directory"),
                        "target": option.get("target", ""),
                        "configured": bool(read_target_value(tool, option.get("target", ""))),
                    }
                    for option in (tool.get("pathOptions") or [])
                    if isinstance(option, dict) and option.get("target")
                ],
            }
        )
    return tools


def get_public_tools() -> list[dict]:
    return scanned_apps_as_tools() + configured_tools_as_public()


def resolve_launch_path(payload: dict) -> Path:
    relative_path = payload.get("relative_path")
    absolute_path = payload.get("absolute_path")

    if relative_path:
        candidate = (APP_ROOT.parent / relative_path).resolve()
        try:
            candidate.relative_to(APP_ROOT.parent.resolve())
        except ValueError as exc:
            raise ValueError("relative path escapes project root") from exc
        return candidate

    if absolute_path:
        return Path(absolute_path).expanduser().resolve()

    raise ValueError("missing launch path")


def resolve_tool_path(value: str, cwd: Path | None = None) -> Path:
    raw = Path(value).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    base = cwd or ROOT_DIR
    return (base / raw).resolve()


def launch_file(target: Path, args: list[str] | None = None, env: dict | None = None) -> None:
    if not target.exists():
        raise FileNotFoundError(str(target))
    logger.info("Launching file: %s", target)
    args = args or []

    if sys.platform.startswith("win"):
        if args or env:
            if target.suffix.lower() in {".bat", ".cmd"}:
                subprocess.Popen(["cmd.exe", "/c", "start", "", str(target), *args], cwd=str(target.parent), env=env)
            else:
                subprocess.Popen([str(target), *args], cwd=str(target.parent), env=env)
            return
        os.startfile(str(target))  # type: ignore[attr-defined]
        return

    if target.suffix.lower() == ".exe":
        wine = shutil.which("wine64") or shutil.which("wine")
        if not wine:
            raise RuntimeError(
                "当前是 Linux，不能直接启动 Windows .exe；请安装 Wine，或在 Windows 上运行 start_local_app_server.bat。"
            )
        subprocess.Popen([wine, str(target)], cwd=str(target.parent))
        return

    subprocess.Popen([str(target), *args], cwd=str(target.parent), env=env)


def run_action(action: dict, title: str) -> str:
    cwd_value = action.get("cwd")
    cwd = resolve_tool_path(cwd_value) if cwd_value else ROOT_DIR
    env = action_environment(action)

    if action.get("python"):
        script = resolve_tool_path(action["python"], cwd)
        args = [str(item) for item in action.get("args", [])]
        logger.info("Starting python backend for %s: %s", title, script)
        subprocess.Popen([sys.executable, str(script), *args], cwd=str(script.parent), env=env)
        return str(script)

    if action.get("command"):
        command = action["command"]
        if not isinstance(command, list):
            raise ValueError("command must be a list, not a shell string")
        logger.info("Starting command for %s: %s", title, command)
        subprocess.Popen([str(part) for part in command], cwd=str(cwd), env=env)
        return " ".join(str(part) for part in command)

    if action.get("path"):
        target = resolve_tool_path(action["path"], cwd)
        args = [str(item) for item in action.get("args", [])]
        launch_file(target, args=args, env=env)
        return str(target)

    raise ValueError("tool has no runnable action for this platform")


def find_configured_tool(tool_id: str) -> dict | None:
    clean_id = tool_id.removeprefix("config:")
    config = load_tool_config()
    for tool in config.get("tools", []):
        if isinstance(tool, dict) and tool.get("id") == clean_id:
            return apply_tool_path_overrides(tool)
    return None


def find_scanned_tool(tool_id: str) -> dict | None:
    clean_id = tool_id.removeprefix("scan:")
    for app in scan_apps():
        if app.get("id") == clean_id:
            return app
    return None


def run_tool(payload: dict) -> dict:
    tool_id = str(payload.get("id", ""))
    if not tool_id:
        raise ValueError("missing tool id")

    if tool_id.startswith("scan:"):
        app = find_scanned_tool(tool_id)
        if not app:
            raise FileNotFoundError(tool_id)
        version = payload.get("version") or app["defaultVersion"]
        if version not in app["versions"]:
            raise ValueError("unknown app version")
        target = (APP_ROOT.parent / app["baseDir"] / version).resolve()
        launch_file(target)
        return {"path": str(target)}

    tool = find_configured_tool(tool_id)
    if not tool:
        raise FileNotFoundError(tool_id)

    launched = []
    backend_action = select_backend_action(tool)
    if backend_action:
        launched.append({"type": "backend", "target": run_action(backend_action, tool.get("title", tool_id))})
        time.sleep(float(tool.get("openDelaySeconds", 1)))

    launch_action = select_platform_action(tool)
    if launch_action:
        launched.append({"type": "launch", "target": run_action(launch_action, tool.get("title", tool_id))})

    url = select_tool_url(tool)
    if url and payload.get("open_url", True):
        logger.info("Opening URL for %s: %s", tool.get("title", tool_id), url)
        webbrowser.open(url)

    return {"launched": launched, "url": url}


def read_recent_logs(limit: int = 80) -> list[str]:
    if not LOG_PATH.exists():
        return []
    lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-limit:]


def resolve_static_path(route: str) -> Path | None:
    if route == "/":
        route = "/index.html"

    relative = unquote(route).lstrip("/")
    candidate = (WEBSITE_ROOT / relative).resolve()
    try:
        candidate.relative_to(WEBSITE_ROOT)
    except ValueError:
        return None

    if candidate.is_dir():
        candidate = candidate / "index.html"
    if candidate.is_file():
        return candidate
    return None


class AppHandler(BaseHTTPRequestHandler):
    server_version = "MyWebLocalAppServer/1.0"

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-MyWeb-Token, Authorization")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/api/health":
            self.respond_json(
                {
                    "ok": True,
                    "app_root": str(APP_ROOT),
                    "exists": APP_ROOT.exists(),
                    "count": len(scan_apps()),
                    "log_path": str(LOG_PATH),
                }
            )
            return

        if route == "/api/apps":
            self.respond_json({"ok": True, "apps": scan_apps()})
            return

        if route == "/api/logs":
            self.respond_json({"ok": True, "lines": read_recent_logs()})
            return

        if route == "/api/tools":
            self.respond_json(
                {
                    "ok": True,
                    "platform": current_platform_key(),
                    "tools": get_public_tools(),
                    "config_path": str(TOOL_CONFIG_PATH),
                }
            )
            return

        if route == "/api/editor/state":
            self.respond_json(
                {
                    "ok": True,
                    "local": is_local_host(),
                    "authRequired": True,
                    "authenticated": is_authenticated(self),
                    "resourcesPath": str(RESOURCE_CONFIG_PATH),
                    "toolsPath": str(TOOL_CONFIG_PATH),
                    "toolPathsPath": str(TOOL_PATHS_PATH),
                    "notesPath": str(NOTES_ROOT),
                }
            )
            return

        if route == "/api/editor/resources":
            self.respond_json({"ok": True, "resources": load_resources(), "path": str(RESOURCE_CONFIG_PATH)})
            return

        static_path = resolve_static_path(route)
        if static_path:
            self.respond_file(static_path)
            return

        self.respond_json({"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        if route == "/api/editor/resources":
            try:
                require_auth(self)
                resource = upsert_resource(parse_request_body(self))
                self.respond_json({"ok": True, "resource": resource, "resources": load_resources()})
            except PermissionError as exc:
                self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
            except Exception as exc:
                logger.exception("Resource save failed")
                self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/editor/tools":
            try:
                require_auth(self)
                tool = upsert_tool(parse_request_body(self))
                self.respond_json({"ok": True, "tool": tool, "tools": get_public_tools()})
            except PermissionError as exc:
                self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
            except Exception as exc:
                logger.exception("Tool save failed")
                self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/editor/browse":
            try:
                require_auth(self)
                payload = parse_request_body(self)
                path = choose_local_path(
                    str(payload.get("kind") or "directory"),
                    str(payload.get("title") or "Choose local path"),
                    str(payload.get("initialDir") or ""),
                )
                self.respond_json({"ok": True, "path": path})
            except PermissionError as exc:
                self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
            except Exception as exc:
                logger.exception("Path browse failed")
                self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/editor/tool-path":
            try:
                require_auth(self)
                tool = update_tool_path_option(parse_request_body(self))
                self.respond_json({"ok": True, "tool": tool, "tools": get_public_tools()})
            except PermissionError as exc:
                self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
            except Exception as exc:
                logger.exception("Tool path update failed")
                self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/editor/notes":
            try:
                require_auth(self)
                note = create_note(parse_request_body(self))
                self.respond_json({"ok": True, "note": note})
            except PermissionError as exc:
                self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
            except Exception as exc:
                logger.exception("Note save failed")
                self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/tools/run":
            try:
                require_auth(self)
                payload = parse_request_body(self)
                result = run_tool(payload)
                self.respond_json({"ok": True, **result})
            except PermissionError as exc:
                self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
            except FileNotFoundError as exc:
                logger.exception("Tool run failed: not found")
                self.respond_json({"ok": False, "error": "tool not found", "path": str(exc)}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                logger.exception("Tool run failed")
                self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if route != "/api/launch":
            self.respond_json({"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return

        try:
            require_auth(self)
            payload = parse_request_body(self)
            target = resolve_launch_path(payload)
            launch_file(target)
            self.respond_json({"ok": True, "path": str(target)})
        except PermissionError as exc:
            self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except FileNotFoundError as exc:
            logger.exception("Launch failed: file not found")
            self.respond_json({"ok": False, "error": "file not found", "path": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            logger.exception("Launch failed")
            self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)
        item_id = (query.get("id") or [""])[0]

        try:
            require_auth(self)
            if route == "/api/editor/resources":
                if not item_id:
                    raise ValueError("missing resource id")
                delete_resource(item_id)
                self.respond_json({"ok": True, "resources": load_resources()})
                return

            if route == "/api/editor/tools":
                if not item_id:
                    raise ValueError("missing tool id")
                delete_configured_tool(item_id)
                self.respond_json({"ok": True, "tools": get_public_tools()})
                return

            self.respond_json({"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)
        except PermissionError as exc:
            self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.UNAUTHORIZED)
        except Exception as exc:
            logger.exception("Delete failed")
            self.respond_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args) -> None:
        return

    def respond_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def respond_file(self, path: Path) -> None:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    logger.info("Server starting on http://%s:%s with app_root=%s", HOST, PORT, APP_ROOT)
    print(f"MyWeb local app server listening on http://{HOST}:{PORT}")
    print(f"App root: {APP_ROOT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
