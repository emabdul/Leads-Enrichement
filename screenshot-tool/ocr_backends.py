"""OCR backends for playstore_finder.

Each backend returns a list of TextLine(text, x0, y0, x1, y1).
Backends are tried in order of preference; the first importable one wins.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class TextLine:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float = 1.0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return self.y1 - self.y0


class OcrError(RuntimeError):
    pass


def _rapidocr(image_path: str) -> List[TextLine]:
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    result, _ = engine(image_path)
    if not result:
        return []
    lines = []
    for box, text, conf in result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        lines.append(TextLine(text, min(xs), min(ys), max(xs), max(ys), float(conf)))
    return lines


def _pytesseract(image_path: str) -> List[TextLine]:
    import pytesseract
    from PIL import Image

    img = Image.open(image_path)
    # Upscale: card labels are small, tesseract does much better at 2-3x.
    img = img.convert("L").resize((img.width * 3, img.height * 3), Image.LANCZOS)
    data = pytesseract.image_to_data(
        img, output_type=pytesseract.Output.DICT, config="--psm 11"
    )

    # Rebuild words into lines using tesseract's own block/par/line grouping.
    groups: dict = {}
    for i, word in enumerate(data["text"]):
        word = word.strip()
        if not word:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf < 30:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        x, y = data["left"][i], data["top"][i]
        w, h = data["width"][i], data["height"][i]
        groups.setdefault(key, []).append((x, y, x + w, y + h, word, conf))

    lines = []
    for parts in groups.values():
        parts.sort(key=lambda p: p[0])
        text = " ".join(p[4] for p in parts)
        lines.append(
            TextLine(
                text,
                min(p[0] for p in parts) / 3,
                min(p[1] for p in parts) / 3,
                max(p[2] for p in parts) / 3,
                max(p[3] for p in parts) / 3,
                sum(p[5] for p in parts) / len(parts) / 100,
            )
        )
    return lines


BACKENDS = [("rapidocr", _rapidocr), ("tesseract", _pytesseract)]


def available_backends() -> List[str]:
    found = []
    for name, _ in BACKENDS:
        try:
            if name == "rapidocr":
                import rapidocr_onnxruntime  # noqa: F401
            else:
                import pytesseract  # noqa: F401

                pytesseract.get_tesseract_version()
            found.append(name)
        except Exception:
            pass
    return found


def run_ocr(image_path: str, prefer: str = "auto") -> tuple[str, List[TextLine]]:
    order = BACKENDS
    if prefer != "auto":
        order = [b for b in BACKENDS if b[0] == prefer]
        if not order:
            raise OcrError(f"unknown OCR backend: {prefer}")

    errors = []
    for name, fn in order:
        try:
            return name, fn(image_path)
        except Exception as exc:  # import failure, missing binary, bad DLL...
            errors.append(f"  {name}: {type(exc).__name__}: {exc}")

    raise OcrError(
        "No usable OCR backend. Tried:\n"
        + "\n".join(errors)
        + "\n\nInstall one of:\n"
        "  pip install rapidocr-onnxruntime      (no system install needed)\n"
        "  pip install pytesseract  +  the Tesseract binary\n"
        "Or skip OCR entirely with --names-file (see --help)."
    )
