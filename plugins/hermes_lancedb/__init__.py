from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

from agent.memory_provider import MemoryProvider

logger = logging.getLogger(__name__)


SEARCH_SCHEMA = {
    "name": "hermes_lancedb_search",
    "description": (
        "Search durable LanceDB memories for this Hermes profile. "
        "Use this when the answer may depend on long-term preferences, prior decisions, "
        "architecture notes, or profile-specific facts."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query."},
            "limit": {"type": "integer", "description": "Maximum results, default 8."},
        },
        "required": ["query"],
    },
}

PROFILE_SCHEMA = {
    "name": "hermes_lancedb_profile",
    "description": "List the most important durable memories for this Hermes profile.",
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Maximum results, default 20."},
        },
    },
}

REMEMBER_SCHEMA = {
    "name": "hermes_lancedb_remember",
    "description": "Append a durable memory to Hermes LanceDB storage after write-gate validation.",
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Memory content to store."},
            "category": {"type": "string", "description": "Memory category.", "default": "fact"},
            "importance": {"type": "number", "description": "Importance from 0.0 to 1.0.", "default": 0.7},
        },
        "required": ["content"],
    },
}


def _parse_metadata(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _memory_text(item: Dict[str, Any]) -> str:
    meta = _parse_metadata(item.get("metadata"))
    for key in ("l2_content", "l1_overview", "l0_abstract"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(item.get("text") or item.get("content") or "").strip()


_DURABLE_CATEGORIES = {
    "decision",
    "decisions",
    "preference",
    "preferences",
    "profile",
    "entity",
    "entities",
    "architecture",
    "debug",
    "fact",
    "user",
}

_DURABLE_SIGNALS = (
    "決定",
    "選擇",
    "採用",
    "保留",
    "改成",
    "不要",
    "decision",
    "decided",
    "adopt",
    "偏好",
    "喜歡",
    "不喜歡",
    "使用者",
    "長期",
    "stable",
    "durable",
    "preference",
    "prefers",
    "user fact",
    "profile",
    "架構",
    "結論",
    "原因",
    "修正",
    "debug",
    "root cause",
    "lancedb",
    "hermes",
)

_EPHEMERAL_PATTERNS = (
    r"^\s*(安安|嗨|hello|hi|ok|okay|好|收到|謝謝)\s*[!.。！]*\s*$",
    r"^\s*(今天|明天|剛剛|等一下|等等|現在)\b.{0,20}$",
)


def _memory_write_gate(content: str, category: str, source: str) -> tuple[bool, str]:
    text = content.strip()
    normalized_category = (category or "").strip().lower()
    if len(text) < 12:
        return False, "too-short"
    for pattern in _EPHEMERAL_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return False, "ephemeral-chat"
    if normalized_category in _DURABLE_CATEGORIES:
        if normalized_category == "fact" and not any(signal in text.lower() for signal in _DURABLE_SIGNALS):
            return False, "generic-fact-without-durable-signal"
        return True, "durable-category"
    if source == "tool" and any(signal in text.lower() for signal in _DURABLE_SIGNALS):
        return True, "tool-with-durable-signal"
    if any(signal in text.lower() for signal in _DURABLE_SIGNALS):
        return True, "durable-signal"
    return False, "no-durable-signal"


class HermesLanceDBProvider(MemoryProvider):
    def __init__(self) -> None:
        self._hermes_home = Path.home() / ".hermes"
        self._profile = ""
        self._session_id = ""
        self._overlay_path = Path()
        self._bridge_path = Path(__file__).with_name("lancedb_bridge.mjs")
        self._scopes: List[str] = []
        self._record_count = 0

    @property
    def name(self) -> str:
        return "hermes_lancedb"

    def is_available(self) -> bool:
        return True

    def get_config_schema(self) -> List[Dict[str, Any]]:
        return []

    def initialize(self, session_id: str, **kwargs) -> None:
        hermes_home = Path(str(kwargs.get("hermes_home") or Path.home() / ".hermes")).expanduser()
        profile = str(kwargs.get("agent_identity") or hermes_home.name or "default")
        self._hermes_home = hermes_home
        self._profile = profile
        self._session_id = session_id
        self._overlay_path = hermes_home / "hermes_lancedb_overlay.jsonl"
        self._scopes = self._profile_scopes(profile)
        stats = self._bridge_call("stats", {"scopes": self._scopes})
        self._record_count = int((stats or {}).get("totalCount") or 0)
        logger.info("Hermes LanceDB provider connected to %s records for profile %s", self._record_count, profile)

    def system_prompt_block(self) -> str:
        return (
            "# Hermes LanceDB Memory\n"
            f"Active for profile {self._profile}. {self._record_count} durable memories are available.\n"
            "Use hermes_lancedb_search before answering questions that may depend on prior durable memory."
        )

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if not query:
            return ""
        results = self._search(query, limit=6)
        if not results:
            return ""
        lines = []
        for item in results:
            text = _memory_text(item).replace("\n", " ").strip()
            if len(text) > 500:
                text = text[:497] + "..."
            score = item.get("_score", 0)
            category = item.get("category") or "memory"
            lines.append(f"- [{category}; score={score:.2f}] {text}")
        return "## Hermes LanceDB Recall\n" + "\n".join(lines)

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [SEARCH_SCHEMA, PROFILE_SCHEMA, REMEMBER_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        try:
            if tool_name == "hermes_lancedb_search":
                query = str(args.get("query") or "").strip()
                limit = int(args.get("limit") or 8)
                return json.dumps({"results": self._search(query, limit=limit)}, ensure_ascii=False)
            if tool_name == "hermes_lancedb_profile":
                limit = int(args.get("limit") or 20)
                records = self._bridge_call("list", {"scopes": self._scopes, "limit": max(1, min(limit, 50))}) or []
                return json.dumps({"results": [self._public_record(r) for r in records]}, ensure_ascii=False)
            if tool_name == "hermes_lancedb_remember":
                content = str(args.get("content") or "").strip()
                if not content:
                    return json.dumps({"error": "content is required"})
                category = str(args.get("category") or "fact")
                allowed, reason = _memory_write_gate(content, category, "tool")
                if not allowed:
                    return json.dumps({"stored": None, "skipped": True, "reason": reason}, ensure_ascii=False)
                record = self._append_memory(
                    content=content,
                    category=category,
                    importance=float(args.get("importance") or 0.7),
                    source="tool",
                )
                return json.dumps({"stored": self._public_record(record)}, ensure_ascii=False)
        except Exception as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps({"error": f"unknown tool: {tool_name}"})

    def on_memory_write(self, action: str, target: str, content: str) -> None:
        if action not in {"add", "replace"}:
            return
        text = str(content or "").strip()
        if not text:
            return
        category = target or "memory"
        allowed, reason = _memory_write_gate(text, category, "hermes-memory-tool")
        if not allowed:
            logger.info("Hermes LanceDB write skipped by governance gate: %s", reason)
            return
        self._append_memory(content=text, category=category, importance=0.75, source="hermes-memory-tool")

    def _profile_scopes(self, profile: str) -> List[str]:
        mapping_raw = os.getenv("HERMES_LANCEDB_SCOPE_MAP", "").strip()
        global_scope = os.getenv("HERMES_LANCEDB_GLOBAL_SCOPE", "global").strip() or "global"
        if mapping_raw:
            try:
                mapping = json.loads(mapping_raw)
                if isinstance(mapping, dict):
                    scope = str(mapping.get(profile) or mapping.get("default") or f"agent:{profile}")
                    return [global_scope, scope]
            except Exception:
                pass
        return [global_scope, f"agent:{profile}"]

    def _write_scope(self) -> str:
        return self._scopes[-1]

    def _bridge_call(self, command: str, args: Dict[str, Any]) -> Any | None:
        if not self._bridge_path.exists():
            return None
        node_bin = os.getenv("HERMES_LANCEDB_NODE_BIN", "/opt/homebrew/bin/node").strip() or "node"
        try:
            proc = subprocess.run(
                [node_bin, str(self._bridge_path), command, json.dumps(args, ensure_ascii=False)],
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
            payload = json.loads((proc.stdout or "").strip() or "{}")
            if proc.returncode != 0 or not payload.get("ok"):
                logger.debug("Hermes LanceDB bridge failed: %s", payload.get("error") or proc.stderr)
                return None
            return payload.get("result")
        except Exception as exc:
            logger.debug("Hermes LanceDB bridge unavailable: %s", exc)
            return None

    def _search(self, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        if not query.strip():
            return []
        rows = self._bridge_call("search", {"query": query, "scopes": self._scopes, "limit": limit}) or []
        return [self._public_record(r) for r in rows]

    def _append_memory(self, *, content: str, category: str, importance: float, source: str) -> Dict[str, Any]:
        record = self._bridge_call(
            "add",
            {
                "content": content,
                "category": category,
                "importance": importance,
                "scope": self._write_scope(),
                "source": source,
                "sessionId": self._session_id,
            },
        )
        if not isinstance(record, dict):
            record = {
                "id": str(uuid.uuid4()),
                "text": content,
                "category": category,
                "scope": self._write_scope(),
                "importance": importance,
                "timestamp": int(time.time() * 1000),
                "metadata": json.dumps({"source": source}, ensure_ascii=False),
            }
        with self._overlay_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def _public_record(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row.get("id"),
            "text": row.get("text", ""),
            "category": row.get("category", "other"),
            "scope": row.get("scope", "global"),
            "importance": float(row.get("importance") or 0),
            "timestamp": int(row.get("timestamp") or 0),
            "metadata": row.get("metadata", "{}"),
            "_score": float(row.get("_score") or 0),
        }

