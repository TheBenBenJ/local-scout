"""Comptage des sources. raw_chars du dossier n'est pas le brut."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..budget import tokens_from_chars


@dataclass
class SourceLedger:
    jira_chars: int = 0
    confluence_chars: int = 0
    image_bytes: int = 0
    ocr_chars: int = 0
    code_chars: int = 0
    phases_s: dict[str, float] = field(default_factory=dict)

    def add_text(self, bucket: str, text: str) -> None:
        n = len(text or "")
        if bucket == "jira":
            self.jira_chars += n
        elif bucket == "confluence":
            self.confluence_chars += n
        elif bucket == "ocr":
            self.ocr_chars += n
        elif bucket == "code":
            self.code_chars += n

    def add_image_file(self, path) -> None:
        try:
            self.image_bytes += path.stat().st_size
        except OSError:
            return

    def text_chars(self) -> int:
        return self.jira_chars + self.confluence_chars + self.ocr_chars + self.code_chars

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload["text_chars"] = self.text_chars()
        payload["text_tokens_est"] = tokens_from_chars(self.text_chars())
        payload["image_tokens_if_chars"] = tokens_from_chars(self.image_bytes)
        return payload
