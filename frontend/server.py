"""
Minimal frontend server for MemMachine: list/search memories and display local images.

Serves static UI, proxies list/search to MemMachine API, and serves local image files
by path (with path validation). Run from repo root:

    uv run python frontend/server.py

Then open http://127.0.0.1:7000 (or http://<server-ip>:7000 if running on a remote host).
Bind to 0.0.0.0 by default so the server is reachable from other machines; set
MEMMACHINE_FRONTEND_HOST=127.0.0.1 to listen only on localhost.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import uuid
from pathlib import Path

import requests
import yaml
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Default MemMachine API base URL (override with MEMMACHINE_BASE_URL env)
DEFAULT_BASE_URL = "http://127.0.0.1:8080"
# Allowed root for local image paths (paths must resolve under this directory)
LOCAL_IMAGE_ROOT = os.environ.get("MEMMACHINE_FRONTEND_IMAGE_ROOT", str(Path.home()))
# Subdir under LOCAL_IMAGE_ROOT where uploaded images are saved (relative path stored in memory)
UPLOADS_SUBDIR = "memmachine_uploads"
# LLM for article generation: from config (configuration.yml) or env
OPENAI_BASE = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
# Min score for write-article search (only include memories with score >= this)
WRITE_ARTICLE_SCORE_THRESHOLD = 0.5
# Max tokens for LLM article generation (longer = longer possible articles)
WRITE_ARTICLE_MAX_TOKENS = int(os.environ.get("MEMMACHINE_WRITE_ARTICLE_MAX_TOKENS", "16384"))

app = FastAPI(title="MemMachine Frontend", version="0.1.0")
# Allow cross-origin requests (e.g. when opening from another host/port or embedding)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
frontend_dir = Path(__file__).resolve().parent


@app.get("/", include_in_schema=False)
async def serve_index():
    """Serve index.html so GET / always returns the UI (avoids blank page). Registered early so it wins over StaticFiles mount."""
    index_path = frontend_dir / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(index_path, media_type="text/html; charset=utf-8")


def _find_config_path() -> Path | None:
    """Locate configuration.yml: MEMMACHINE_CONFIG_PATH, repo root, or cwd."""
    path_env = os.environ.get("MEMMACHINE_CONFIG_PATH")
    if path_env:
        p = Path(path_env)
        return p if p.is_file() else None
    repo_root = frontend_dir.parent
    for candidate in (repo_root / "configuration.yml", Path.cwd() / "configuration.yml"):
        if candidate.is_file():
            return candidate
    return None


def _llm_from_config() -> tuple[str, str, str] | None:
    """Read (base_url, api_key, model) from configuration.yml language_models. Returns None if not found."""
    path = _find_config_path()
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return None
    models = (data or {}).get("resources") or {}
    models = models.get("language_models") or {}
    model_id = os.environ.get("WRITE_ARTICLE_MODEL")
    if model_id and model_id in models:
        cfg = (models[model_id] or {}).get("config") or {}
        base = (cfg.get("base_url") or "").strip().rstrip("/")
        key = (cfg.get("api_key") or "").strip()
        model = (cfg.get("model") or model_id).strip()
        if base and key:
            return (base, key, model)
    for mid, raw in models.items():
        if (raw or {}).get("provider") != "openai-chat-completions":
            continue
        cfg = (raw or {}).get("config") or {}
        base = (cfg.get("base_url") or "").strip().rstrip("/")
        key = (cfg.get("api_key") or "").strip()
        model = (cfg.get("model") or mid).strip()
        if base and key:
            return (base, key, model)
    return None


def _get_llm_for_article() -> tuple[str, str, str]:
    """Return (base_url, api_key, model) for article generation: config first, then env."""
    from_config = _llm_from_config()
    if from_config:
        return from_config
    return (OPENAI_BASE, OPENAI_KEY, OPENAI_MODEL)


def _memmachine_url() -> str:
    return os.environ.get("MEMMACHINE_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _resolve_local_path(path_str: str) -> Path | None:
    """Resolve path_str to a real path under LOCAL_IMAGE_ROOT; return None if invalid."""
    if not path_str or not path_str.strip():
        return None
    path_str = path_str.strip()
    try:
        path = Path(path_str)
        if not path.is_absolute():
            path = Path(LOCAL_IMAGE_ROOT) / path
        resolved = path.resolve()
        root = Path(LOCAL_IMAGE_ROOT).resolve()
        if not str(resolved).startswith(str(root)):
            return None
        return resolved if resolved.is_file() else None
    except (OSError, RuntimeError):
        return None


@app.get("/local-image")
async def local_image(path: str = Query(..., description="URL-encoded local file path")):
    """Serve a local image file. Path must be under MEMMACHINE_FRONTEND_IMAGE_ROOT (default: $HOME)."""
    raw = urllib.parse.unquote(path)
    resolved = _resolve_local_path(raw)
    if resolved is None:
        raise HTTPException(status_code=404, detail="File not found or path not allowed")
    return FileResponse(resolved, media_type=None)


@app.post("/api/proxy/list")
async def proxy_list(request: Request):
    """Proxy POST to MemMachine /api/v2/memories/list."""
    body = await request.json()
    url = f"{_memmachine_url()}/api/v2/memories/list"
    try:
        r = requests.post(url, json=body, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        status = 502
        if hasattr(e, "response") and e.response is not None:
            status = e.response.status_code
        return JSONResponse(status_code=status, content={"detail": str(e)})


@app.post("/api/proxy/search")
async def proxy_search(request: Request):
    """Proxy POST to MemMachine /api/v2/memories/search."""
    body = await request.json()
    url = f"{_memmachine_url()}/api/v2/memories/search"
    try:
        r = requests.post(url, json=body, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        status = 502
        if hasattr(e, "response") and e.response is not None:
            status = e.response.status_code
        return JSONResponse(status_code=status, content={"detail": str(e)})


def _suffix_from_filename(filename: str) -> str:
    """Return extension including dot, or .bin if unknown."""
    p = Path(filename)
    ext = p.suffix
    return ext if ext else ".bin"


@app.post("/api/proxy/add-memory")
async def proxy_add_memory(
    spec: str = Form(..., description="JSON string of AddMemoriesSpec"),
    image: UploadFile | None = File(default=None),
    image_path: str | None = Form(default=None),
):
    """Proxy multipart POST to MemMachine /api/v2/memories. Saves uploaded image under
    LOCAL_IMAGE_ROOT/UPLOADS_SUBDIR and stores a relative path (UPLOADS_SUBDIR/...) in memory."""
    url = f"{_memmachine_url()}/api/v2/memories"
    try:
        spec_dict = json.loads(spec)
        data: dict[str, str]
        files = None

        if image and image.filename:
            content = await image.read()
            uploads_dir = Path(LOCAL_IMAGE_ROOT) / UPLOADS_SUBDIR
            uploads_dir.mkdir(parents=True, exist_ok=True)
            unique_name = f"{uuid.uuid4().hex}{_suffix_from_filename(image.filename)}"
            saved_path = uploads_dir / unique_name
            saved_path.write_bytes(content)
            # Store path relative to LOCAL_IMAGE_ROOT so /local-image can resolve it
            relative_path = f"{UPLOADS_SUBDIR}/{unique_name}"
            spec_dict.setdefault("messages", [{}])
            if spec_dict["messages"]:
                spec_dict["messages"][0]["image_path"] = relative_path
            data = {"spec": json.dumps(spec_dict), "image_path": relative_path}
            media_type = image.content_type or "application/octet-stream"
            files = [("image", (image.filename, content, media_type))]
        else:
            if image_path and image_path.strip():
                data = {"spec": spec, "image_path": image_path.strip()}
            else:
                data = {"spec": spec}

        r = requests.post(url, data=data, files=files, timeout=60)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        status = 502
        if hasattr(e, "response") and e.response is not None:
            status = e.response.status_code
        return JSONResponse(status_code=status, content={"detail": str(e)})
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        return JSONResponse(status_code=422, content={"detail": str(e)})


@app.post("/api/proxy/delete-episodic")
async def proxy_delete_episodic(request: Request):
    """Proxy POST to MemMachine /api/v2/memories/episodic/delete."""
    body = await request.json()
    url = f"{_memmachine_url()}/api/v2/memories/episodic/delete"
    try:
        r = requests.post(url, json=body, timeout=30)
        r.raise_for_status()
        return {}
    except requests.RequestException as e:
        status = 502
        if hasattr(e, "response") and e.response is not None:
            status = e.response.status_code
        return JSONResponse(status_code=status, content={"detail": str(e)})


def _collect_episodes_from_search_response(data: dict) -> list[dict]:
    """Extract episodes from MemMachine search result (episodic long/short term)."""
    out: list[dict] = []
    c = data.get("content")
    if not c or "episodic_memory" not in c:
        return out
    em = c["episodic_memory"]
    if isinstance(em, list):
        out.extend(em)
        return out
    lt = em.get("long_term_memory") or {}
    st = em.get("short_term_memory") or {}
    for ep in lt.get("episodes") or []:
        out.append(ep)
    for ep in st.get("episodes") or []:
        out.append(ep)
    return out


def _rewrite_local_image_urls(text: str) -> str:
    """Replace markdown image paths that are not full URLs with /local-image?path=..."""
    def repl(m: re.Match) -> str:
        alt, path = m.group(1), m.group(2).strip()
        if path.startswith("http://") or path.startswith("https://") or path.startswith("/local-image"):
            return m.group(0)
        return f"![{alt}](/local-image?path={urllib.parse.quote(path, safe='')})"
    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", repl, text)


@app.post("/api/proxy/write-article")
async def proxy_write_article(request: Request):
    """Search memories by theme, call LLM to write a Markdown article, insert image refs."""
    body = await request.json()
    org_id = body.get("org_id", "test")
    project_id = body.get("project_id", "test")
    theme = (body.get("theme") or "").strip()
    if not theme:
        return JSONResponse(status_code=422, content={"detail": "theme is required"})
    llm_base, llm_key, llm_model = _get_llm_for_article()
    if not llm_key:
        return JSONResponse(
            status_code=503,
            content={"detail": "LLM not configured: set OPENAI_API_KEY or use configuration.yml language_models"},
        )
    url_search = f"{_memmachine_url()}/api/v2/memories/search"
    try:
        r = requests.post(
            url_search,
            json={
                "org_id": org_id,
                "project_id": project_id,
                "query": theme,
                "top_k": 40,
                "filter": "",
                "expand_context": 0,
                "score_threshold": WRITE_ARTICLE_SCORE_THRESHOLD,
                "types": [],
            },
            timeout=30,
        )
        r.raise_for_status()
        search_data = r.json()
    except requests.RequestException as e:
        status = 502
        if hasattr(e, "response") and e.response is not None:
            status = e.response.status_code
        return JSONResponse(status_code=status, content={"detail": str(e)})
    episodes = _collect_episodes_from_search_response(search_data)
    # Use all memories (text and image); do not filter to image-only
    snippets = []
    for i, ep in enumerate(episodes):
        content = (ep.get("content") or "").strip()
        meta = ep.get("metadata") or {}
        image_path = meta.get("image_path")
        time_meta = meta.get("time")
        loc_meta = meta.get("location")
        parts = [f"[{i+1}] {content}"]
        if time_meta:
            parts.append(f" (Time: {time_meta})")
        if loc_meta:
            parts.append(f" (Location: {loc_meta})")
        if image_path:
            parts.append(f" [Image path for insertion: {image_path}]")
        snippets.append("".join(parts))
    memories_text = "\n\n".join(snippets) if snippets else "(No memories found for this theme.)"
    prompt = f"""You are writing a long, detailed article in Markdown about this theme: {theme}

Use the following memories (text and optional image paths) to write a coherent, engaging, and thorough article. You may use only the memory content below; do not invent facts. Aim for a long read: use multiple sections (## and ###), expand on each memory where relevant, add context and narrative so the article feels complete and rich. Do not summarize briefly—write at length.

When you want to insert an image, use Markdown image syntax with the EXACT path given in the memory, e.g. ![description](memmachine_uploads/abc123.jpg). Use the path exactly as shown in "[Image path for insertion: ...]". Insert images where they fit the narrative.

Write in Markdown: use ## and ### for sections, **bold** where appropriate, and ![alt](path) for images. Output only the article, no preamble. Write as long an article as the memories support.

Memories:
{memories_text}
"""
    try:
        chat_url = f"{llm_base}/chat/completions"
        resp = requests.post(
            chat_url,
            headers={
                "Authorization": f"Bearer {llm_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": WRITE_ARTICLE_MAX_TOKENS,
            },
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return JSONResponse(status_code=502, content={"detail": "LLM returned no content"})
        text = (choices[0].get("message") or {}).get("content") or ""
        text = _rewrite_local_image_urls(text)
        return {"article": text}
    except requests.RequestException as e:
        status = 502
        if hasattr(e, "response") and e.response is not None:
            status = e.response.status_code
        return JSONResponse(status_code=status, content={"detail": str(e)})


app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="static")


def main() -> None:
    import uvicorn
    host = os.environ.get("MEMMACHINE_FRONTEND_HOST", "0.0.0.0")
    port = int(os.environ.get("MEMMACHINE_FRONTEND_PORT", "7000"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
