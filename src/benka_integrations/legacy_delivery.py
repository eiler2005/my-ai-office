"""Formatting adapter shared by the preserved deterministic renderers."""
from __future__ import annotations

import asyncio
import os
import re

from .config import load_manifest
from .delivery import send
from .queue import connection


async def post_text(text, *, chat_id, topic_id=None, html=True):
    config = load_manifest()
    target = f"telegram:{chat_id}" + (f":{topic_id}" if topic_id else "")
    if html:
        from markdownify import markdownify
        text = markdownify(text, heading_style="ATX")
    # Hermes recognizes MEDIA directives even in plain text. External mail and
    # Telegram content must never be interpreted as local attachment commands.
    text = re.sub(r"MEDIA:", "MEDIA\u200b:", text, flags=re.IGNORECASE)
    text = re.sub(r"\[\[(as_document|audio_as_voice)\]\]", r"[\1]", text, flags=re.IGNORECASE)
    # Stable content key handles a process restart after a confirmed first chunk.
    import hashlib
    identity = os.environ["BENKA_RUN_ID"] + ":" + target + ":" + hashlib.sha256(text.encode()).hexdigest()
    await asyncio.to_thread(send, connection(config), config, delivery_id=identity, target=target, text=text)
    return True


async def post_media(data, *, filename, caption, chat_id, topic_id=None, document=True):
    import hashlib
    from pathlib import Path
    from .config import confined, require_active
    config = load_manifest()
    require_active(config, "send")
    if len(data) > 20 * 1024 * 1024:
        raise ValueError("Source attachment exceeds the reviewed 20 MiB limit")
    sha = hashlib.sha256(data).hexdigest()
    extension = Path(filename).suffix.lower()
    if extension not in {".jpg", ".jpeg", ".png", ".pdf", ".txt", ".docx", ".xlsx", ".zip"}:
        extension = ".bin"
    path = confined(config["media_root"], sha + extension)
    if not path.exists():
        with path.open("xb") as stream:
            os.chmod(path, 0o600)
            stream.write(data)
    elif hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise ValueError("Attachment content changed")
    target = f"telegram:{chat_id}" + (f":{topic_id}" if topic_id else "")
    if caption:
        await post_text(caption, chat_id=chat_id, topic_id=topic_id, html=False)
    directive = ("[[as_document]] " if document else "") + f"MEDIA:{path}"
    identity = os.environ["BENKA_RUN_ID"] + ":media:" + target + ":" + sha
    await asyncio.to_thread(send, connection(config), config, delivery_id=identity, target=target, text=directive)
    return True
