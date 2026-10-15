"""Validation helpers for importing content-only JSON exports."""

import json


MAX_CONTENT_IMPORT_BYTES = 10 * 1024 * 1024


def read_content_upload(upload, expected_area: str) -> dict:
    if upload is None or not upload.filename:
        raise ValueError("Vyber soubor JSON k importu.")

    content = upload.stream.read(MAX_CONTENT_IMPORT_BYTES + 1)
    if len(content) > MAX_CONTENT_IMPORT_BYTES:
        raise ValueError("Soubor je příliš velký (maximum je 10 MB).")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Soubor není platný JSON v kódování UTF-8.") from error
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Soubor obsahuje neplatný JSON (řádek {error.lineno}, sloupec {error.colno})."
        ) from error

    if (
        not isinstance(payload, dict)
        or payload.get("format") != "zelva-content"
        or payload.get("version") != 1
        or payload.get("area") != expected_area
    ):
        raise ValueError("Soubor neodpovídá exportu této oblasti.")
    return payload
