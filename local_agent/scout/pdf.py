"""Annots PDF : Highlight / Text / FreeText / StrikeOut / Caret / Stamp. Pas d'OCR."""

from __future__ import annotations

import re
import subprocess
import zlib
from pathlib import Path
from xml.etree import ElementTree

ANNOT_SUBTYPES = ("Highlight", "Text", "FreeText", "StrikeOut", "Caret", "Stamp")
_SUBTYPE_RE = re.compile(
    rb"/Subtype\s*/(Highlight|Text|FreeText|StrikeOut|Caret|Stamp)\b"
)
_OBJ_RE = re.compile(rb"(?m)^(\d+)\s+(\d+)\s+obj\b")
_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_KIDS_RE = re.compile(rb"/Kids\s*\[(.*?)\]", re.S)
_REF_RE = re.compile(rb"(\d+)\s+\d+\s+R")
_FLATE = (b"/FlateDecode", b"/Fl")


def extract_annots(path: Path, *, want_page_text: bool = False) -> dict:
    """Parse les objets Annot. Jamais un raster du PDF."""
    try:
        raw = path.read_bytes()
    except OSError as error:
        return {"error": f"PDF illisible : {error}", "annots": [], "pages": 0}
    if not raw.startswith(b"%PDF"):
        return {"error": "pas un PDF (%PDF manquant)", "annots": [], "pages": 0}

    blobs = [raw, *_inflate_streams(raw)]
    objects = _index_objects(blobs)
    page_ids = _page_object_ids(objects)
    page_of_obj = {obj_id: index for index, obj_id in enumerate(page_ids, start=1)}
    annot_pages = _annots_on_pages(objects, page_of_obj)

    found: list[dict] = []
    seen: set[tuple] = set()
    for obj_id, blob in objects.items():
        for annot in _annots_in(blob, obj_id=obj_id):
            page = annot_pages.get(obj_id) or page_of_obj.get(annot.get("page_ref") or 0) or annot.get("page")
            annot["page"] = page
            key = (annot.get("subtype"), annot.get("contents"), annot.get("author"))
            if key in seen:
                continue
            seen.add(key)
            found.append(annot)

    for blob in blobs:
        for annot in _annots_in(blob, obj_id=None):
            key = (annot.get("subtype"), annot.get("contents"), annot.get("author"))
            if key in seen:
                continue
            seen.add(key)
            found.append(annot)

    for annot in found:
        if annot.get("contents"):
            continue
        popup_ref = annot.get("popup_ref")
        if popup_ref in objects:
            extra = _pdf_string(objects[popup_ref], b"Contents")
            if extra:
                annot["contents"] = extra

    heights = _page_heights(objects, page_ids)
    if want_page_text or any(item.get("quads") for item in found):
        for annot in found:
            page = annot.get("page")
            if not page or not annot.get("quads"):
                continue
            passage = _passage_under_quads(path, int(page), annot["quads"], heights.get(int(page)))
            if passage:
                annot["passage"] = passage

    if want_page_text:
        for annot in found:
            page = annot.get("page")
            if page and not annot.get("passage"):
                text = _pdftotext(path, int(page))
                if text:
                    annot["passage"] = text[:240].strip()

    return {
        "error": None,
        "annots": found,
        "pages": len(page_ids) or 1,
        "pdftotext": _have_pdftotext(),
    }


def _inflate_streams(raw: bytes) -> list[bytes]:
    out: list[bytes] = []
    for match in _STREAM_RE.finditer(raw):
        head = raw[max(0, match.start() - 800) : match.start()]
        if not any(token in head for token in _FLATE):
            continue
        payload = match.group(1)
        try:
            data = zlib.decompress(payload)
        except zlib.error:
            try:
                data = zlib.decompress(payload, -15)
            except zlib.error:
                continue
        if len(data) > 8_000_000:
            data = data[:8_000_000]
        out.append(data)
    return out


def _index_objects(blobs: list[bytes]) -> dict[int, bytes]:
    objects: dict[int, bytes] = {}
    for blob in blobs:
        for match in _OBJ_RE.finditer(blob):
            obj_id = int(match.group(1))
            start = match.end()
            end = blob.find(b"endobj", start)
            body = blob[start : end if end != -1 else start + 8000]
            objects[obj_id] = body
    return objects


def _page_object_ids(objects: dict[int, bytes]) -> list[int]:
    pages: list[int] = []
    for obj_id, body in objects.items():
        if b"/Type" in body and re.search(rb"/Type\s*/Pages\b", body) and b"/Kids" in body:
            kids = _KIDS_RE.search(body)
            if kids:
                for ref in _REF_RE.findall(kids.group(1)):
                    kid = int(ref)
                    if kid in objects and re.search(rb"/Type\s*/Page\b", objects[kid]):
                        if kid not in pages:
                            pages.append(kid)
                    elif kid in objects and re.search(rb"/Type\s*/Pages\b", objects[kid]):
                        continue
    if pages:
        return pages
    for obj_id, body in sorted(objects.items()):
        if re.search(rb"/Type\s*/Page\b", body) and not re.search(rb"/Type\s*/Pages\b", body):
            pages.append(obj_id)
    return pages


def _annots_on_pages(objects: dict[int, bytes], page_of_obj: dict[int, int]) -> dict[int, int]:
    mapping: dict[int, int] = {}
    for obj_id, body in objects.items():
        page_no = page_of_obj.get(obj_id)
        if not page_no:
            continue
        annots = re.search(rb"/Annots\s*\[(.*?)\]", body, re.S)
        if not annots:
            continue
        for ref in _REF_RE.findall(annots.group(1)):
            mapping[int(ref)] = page_no
    return mapping


def _page_heights(objects: dict[int, bytes], page_ids: list[int]) -> dict[int, float]:
    heights: dict[int, float] = {}
    for index, obj_id in enumerate(page_ids, start=1):
        body = objects.get(obj_id) or b""
        box = re.search(
            rb"/MediaBox\s*\[\s*([0-9.-]+)\s+([0-9.-]+)\s+([0-9.-]+)\s+([0-9.-]+)\s*\]",
            body,
        )
        if box:
            heights[index] = abs(float(box.group(4)) - float(box.group(2)))
    return heights


def _annots_in(blob: bytes, *, obj_id: int | None) -> list[dict]:
    found: list[dict] = []
    for match in _SUBTYPE_RE.finditer(blob):
        block = _enclosing_dict(blob, match.start())
        if not block:
            continue
        subtype = match.group(1).decode("ascii")
        contents = _pdf_string(block, b"Contents")
        popup_ref = _pdf_ref(block, b"Popup")
        author = _pdf_string(block, b"T") or _pdf_string(block, b"Subj") or ""
        date = _pdf_string(block, b"M") or _pdf_string(block, b"CreationDate") or ""
        quads = _pdf_numbers(block, b"QuadPoints")
        rect = _pdf_numbers(block, b"Rect")
        page_ref = _pdf_ref(block, b"P")
        found.append(
            {
                "id": obj_id,
                "subtype": subtype,
                "author": author,
                "title": author,
                "date": _pdf_date(date),
                "contents": contents,
                "passage": "",
                "quads": quads,
                "rect": rect,
                "page_ref": page_ref,
                "popup_ref": popup_ref,
                "page": None,
            }
        )
    return found


def _enclosing_dict(blob: bytes, pos: int) -> bytes:
    start = blob.rfind(b"<<", 0, pos + 1)
    if start < 0:
        return b""
    depth = 0
    i = start
    in_str = False
    escape = False
    hexmode = False
    while i < len(blob):
        ch = blob[i]
        if in_str:
            if escape:
                escape = False
            elif ch == 0x5C:
                escape = True
            elif ch == 0x29:
                in_str = False
            i += 1
            continue
        if hexmode:
            if ch == 0x3E:
                hexmode = False
            i += 1
            continue
        if ch == 0x28:
            in_str = True
            i += 1
            continue
        if ch == 0x3C and i + 1 < len(blob) and blob[i + 1] != 0x3C:
            hexmode = True
            i += 1
            continue
        if blob.startswith(b"<<", i):
            depth += 1
            i += 2
            continue
        if blob.startswith(b">>", i):
            depth -= 1
            i += 2
            if depth <= 0:
                return blob[start:i]
            continue
        i += 1
    return blob[start : start + 4000]


def _pdf_string(block: bytes, key: bytes) -> str:
    literal = re.search(key + rb"\s*\(", block)
    if literal:
        return _decode_literal(block, literal.end() - 1)
    hexa = re.search(key + rb"\s*<([0-9A-Fa-f \r\n]+)>", block)
    if hexa:
        return _decode_hex(hexa.group(1))
    named = re.search(key + rb"\s*/([A-Za-z0-9._+-]+)", block)
    if named:
        return named.group(1).decode("ascii", errors="replace")
    return ""


def _pdf_ref(block: bytes, key: bytes) -> int | None:
    match = re.search(key + rb"\s+(\d+)\s+\d+\s+R", block)
    return int(match.group(1)) if match else None


def _pdf_numbers(block: bytes, key: bytes) -> list[float]:
    match = re.search(key + rb"\s*\[([^\]]*)\]", block)
    if not match:
        return []
    return [float(item) for item in re.findall(rb"[+-]?(?:\d+\.\d*|\.\d+|\d+)", match.group(1))]


def _decode_literal(block: bytes, open_paren: int) -> str:
    depth = 0
    escape = False
    out = bytearray()
    i = open_paren
    while i < len(block):
        ch = block[i]
        if escape:
            if ch in b"nrtbf()\\":
                out.append({ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}.get(ch, ch))
            elif 0x30 <= ch <= 0x37:
                octal = bytes([ch])
                for _ in range(2):
                    if i + 1 < len(block) and 0x30 <= block[i + 1] <= 0x37:
                        i += 1
                        octal += bytes([block[i]])
                    else:
                        break
                out.append(int(octal, 8) & 0xFF)
            else:
                out.append(ch)
            escape = False
            i += 1
            continue
        if ch == 0x5C:
            escape = True
            i += 1
            continue
        if ch == 0x28:
            depth += 1
            if depth > 1:
                out.append(ch)
            i += 1
            continue
        if ch == 0x29:
            depth -= 1
            if depth <= 0:
                break
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    data = bytes(out)
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be", errors="replace")
    if data.startswith(b"\xff\xfe"):
        return data[2:].decode("utf-16-le", errors="replace")
    return data.decode("latin-1", errors="replace")


def _decode_hex(payload: bytes) -> str:
    hexed = re.sub(rb"\s+", b"", payload)
    if len(hexed) % 2:
        hexed += b"0"
    try:
        data = bytes.fromhex(hexed.decode("ascii"))
    except ValueError:
        return ""
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be", errors="replace")
    if data.startswith(b"\xff\xfe"):
        return data[2:].decode("utf-16-le", errors="replace")
    return data.decode("latin-1", errors="replace")


def _pdf_date(raw: str) -> str:
    text = (raw or "").strip()
    match = re.match(r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?", text)
    if not match:
        return text[:24]
    year, month, day, hour, minute = match.groups()
    parts = [year]
    if month:
        parts.append(month)
    if day:
        parts.append(day)
    date = "-".join(parts[:3]) if len(parts) >= 3 else year
    if hour and minute:
        return f"{date} {hour}:{minute}"
    return date


def _have_pdftotext() -> bool:
    try:
        subprocess.run(
            ["pdftotext", "-v"],
            check=False,
            capture_output=True,
            timeout=5,
            stdin=subprocess.DEVNULL,
        )
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def _pdftotext(path: Path, page: int) -> str:
    try:
        proc = subprocess.run(
            ["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(path), "-"],
            check=False,
            capture_output=True,
            timeout=20,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode not in (0, 1):
        return ""
    return (proc.stdout or b"").decode("utf-8", errors="replace")


def _passage_under_quads(
    path: Path,
    page: int,
    quads: list[float],
    height: float | None,
) -> str:
    if len(quads) < 8:
        return ""
    try:
        proc = subprocess.run(
            ["pdftotext", "-bbox", "-f", str(page), "-l", str(page), str(path), "-"],
            check=False,
            capture_output=True,
            timeout=20,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode not in (0, 1) or not proc.stdout:
        return ""
    try:
        root = ElementTree.fromstring(proc.stdout)
    except ElementTree.ParseError:
        return ""
    boxes = _quad_boxes(quads)
    words: list[str] = []
    for word in root.iter("word"):
        try:
            x0, y0 = float(word.get("xMin", 0)), float(word.get("yMin", 0))
            x1, y1 = float(word.get("xMax", 0)), float(word.get("yMax", 0))
        except ValueError:
            continue
        if height:
            pdf_box = (x0, height - y1, x1, height - y0)
        else:
            pdf_box = (x0, y0, x1, y1)
        if any(_overlap(pdf_box, box) for box in boxes) or any(_overlap((x0, y0, x1, y1), box) for box in boxes):
            text = (word.text or "").strip()
            if text:
                words.append(text)
    return " ".join(words)[:400]


def _quad_boxes(quads: list[float]) -> list[tuple[float, float, float, float]]:
    boxes = []
    for index in range(0, len(quads) - 7, 8):
        xs = quads[index : index + 8 : 2]
        ys = quads[index + 1 : index + 8 : 2]
        boxes.append((min(xs), min(ys), max(xs), max(ys)))
    return boxes


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def render_annot(item: dict, *, excerpt_id: str = "") -> str:
    page = item.get("page") or "?"
    subtype = item.get("subtype") or "Annot"
    author = item.get("author") or item.get("title") or "?"
    date = item.get("date") or "?"
    loc = item.get("file") or ""
    prefix = f"`{loc}` page {page} · {subtype} · {author} · {date}" if loc else f"page {page} · {subtype} · {author} · {date}"
    if excerpt_id:
        prefix += f" [{excerpt_id}]"
    lines = [prefix]
    passage = (item.get("passage") or "").strip()
    comment = (item.get("contents") or "").strip()
    if passage:
        lines.append(f"passage : « {passage} »")
    if comment:
        lines.append(f"commentaire : {comment}")
    elif not passage:
        lines.append("(annot sans /Contents)")
    return "\n".join(lines)
