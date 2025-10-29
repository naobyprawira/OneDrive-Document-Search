"""
File state tracking to prevent duplicate ingestion.

Tracks file ingestion state (downloading, enqueued, processing, completed, failed)
to prevent duplicate processing when cron schedule fires before previous run completes.
"""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Literal

logger = logging.getLogger("ingestion.state_tracker")

StateValue = Literal["downloading", "enqueued", "processing", "completed", "failed"]

_STATE_FILE = Path(tempfile.gettempdir()) / "ingestion_state.json"
_STATE_LOCK = Lock()


def _load_state() -> dict[str, dict]:
    """Load state from file, or return empty dict if file doesn't exist."""
    if not _STATE_FILE.exists():
        return {}
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load state file: %s", exc)
        return {}


def _save_state(state: dict[str, dict]) -> None:
    """Save state to file."""
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to save state file: %s", exc)


def get_file_state(file_id: str) -> StateValue | None:
    """Get current state of a file, or None if not tracked."""
    with _STATE_LOCK:
        state = _load_state()
        entry = state.get(file_id, {})
        return entry.get("state")


def is_file_busy(file_id: str) -> bool:
    """Check if file is currently being processed (downloading, enqueued, or processing)."""
    current_state = get_file_state(file_id)
    return current_state in ("downloading", "enqueued", "processing")


def set_file_state(file_id: str, state: StateValue, file_name: str = "") -> None:
    """
    Set state of a file and update timestamp.
    
    Args:
        file_id: Microsoft Graph file ID
        state: One of 'downloading', 'enqueued', 'processing', 'completed', 'failed'
        file_name: (optional) File name for logging
    """
    with _STATE_LOCK:
        data = _load_state()
        data[file_id] = {
            "state": state,
            "timestamp": datetime.utcnow().isoformat(),
            "file_name": file_name or data.get(file_id, {}).get("file_name", ""),
        }
        _save_state(data)
        logger.debug("File %s state -> %s", file_id, state)


def cleanup_completed() -> int:
    """
    Remove entries for completed/failed files older than 24 hours.
    Returns count of removed entries.
    """
    with _STATE_LOCK:
        state = _load_state()
        original_count = len(state)
        now = datetime.utcnow()
        
        to_remove = []
        for file_id, entry in state.items():
            file_state = entry.get("state")
            if file_state not in ("completed", "failed"):
                continue
            
            try:
                timestamp = datetime.fromisoformat(entry.get("timestamp", ""))
                age_seconds = (now - timestamp).total_seconds()
                if age_seconds > 86400:  # 24 hours
                    to_remove.append(file_id)
            except Exception:  # noqa: BLE001
                pass
        
        for file_id in to_remove:
            del state[file_id]
        
        if to_remove:
            _save_state(state)
            logger.info("Cleaned up %d completed/failed entries", len(to_remove))
        
        return len(to_remove)
