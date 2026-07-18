"""Child-process entry point for hard-timeout transcription.

Runs ONE file's transcription in its own process so the parent can KILL it on a
wall-clock timeout — the only way to abort a hang stuck INSIDE a single Whisper
segment, which the between-segment deadline in transcription_service cannot
interrupt (the GPU C call never returns to Python to be checked). Writes the
resulting chunks to a JSON file the parent reads back.

Invoked as:  python -m app.services._transcribe_worker <media_path> <out_json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: _transcribe_worker <media_path> <out_json>", file=sys.stderr)
        return 2
    media_path, out_json = sys.argv[1], sys.argv[2]
    from app.services.transcription_service import transcribe_to_chunks

    chunks = transcribe_to_chunks(Path(media_path))  # None | [] | [chunks]
    Path(out_json).write_text(json.dumps({"chunks": chunks}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
