"""Étape 3 — OCR Tesseract + fallback vision Qwen2.5-VL si extraction trop pauvre.

ratio_text = chars_extraits / pixels_page (normalisé). Heuristique simple :
  - une page imprimée nette donne ~0.001-0.005 chars/pixel à 300 dpi
  - on normalise pour que `ratio_text >= 0.70` corresponde à une page bien lisible
  - sous le seuil → vision fallback sur les pages faibles uniquement
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path

import httpx

# Constante de normalisation : ratio brut chars/pixel à 300 dpi attendu pour
# une page imprimée nette (~0.0035 en pratique). On divise par 0.005 pour
# que le ratio normalisé soit ~0.70 sur une page propre.
RATIO_NORMALIZER = 0.005


@dataclass
class OCRResult:
    text: str
    engine: str  # "tesseract" | "tesseract+vision" | "vision_only"
    ratio_text: float
    pages: int


def _normalize_ratio(chars: int, pixels: int) -> float:
    if pixels <= 0:
        return 0.0
    raw = chars / pixels
    return min(raw / RATIO_NORMALIZER, 1.5)


def ocr_tesseract(path: Path, langs: list[str], dpi: int) -> tuple[list[str], list[tuple[int, int]]]:
    """OCR page-par-page. Retourne (textes, dimensions[w,h]).

    Workaround Pillow 12.x / pytesseract 0.3.13 : l'appel direct
    `pytesseract.image_to_string(pil_image)` casse car Pillow 12 a modifié la
    sérialisation interne du buffer PPM passé à tesseract via stdin. On
    contourne en écrivant l'image en PNG temporaire puis en passant le chemin
    à pytesseract (qui accepte les deux signatures).
    Cf. bug investigation 2026-05-16.
    """
    import os
    import tempfile

    import pytesseract
    from PIL import Image

    if path.suffix.lower() == ".pdf":
        from pdf2image import convert_from_path

        pages = convert_from_path(str(path), dpi=dpi)
    else:
        pages = [Image.open(path)]

    lang = "+".join(langs)
    texts: list[str] = []
    dims: list[tuple[int, int]] = []
    for p in pages:
        # Workaround : passer par PNG temp au lieu de l'objet PIL direct.
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            p.save(tmp_path, "PNG")
            texts.append(pytesseract.image_to_string(tmp_path, lang=lang))
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        dims.append(p.size)
    return texts, dims


def _image_to_b64_png(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def ocr_vision(
    path: Path,
    page_indices: list[int],
    dpi: int,
    model: str,
    endpoint: str,
    timeout_s: int,
) -> list[str]:
    """Vision fallback via Ollama generate API + multimodal images."""
    from PIL import Image

    if path.suffix.lower() == ".pdf":
        from pdf2image import convert_from_path

        all_pages = convert_from_path(str(path), dpi=dpi)
    else:
        all_pages = [Image.open(path)]

    out: list[str] = []
    prompt = (
        "Transcris fidèlement TOUT le texte visible sur cette page de document "
        "comptable suisse. Conserve les nombres, dates, IBAN, adresses. "
        "Réponds UNIQUEMENT par le texte transcrit, sans commentaire."
    )
    for idx in page_indices:
        if idx >= len(all_pages):
            continue
        b64 = _image_to_b64_png(all_pages[idx])
        try:
            r = httpx.post(
                f"{endpoint}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "images": [b64],
                    "stream": False,
                    "options": {"temperature": 0.0},
                },
                timeout=timeout_s,
            )
            r.raise_for_status()
            out.append(r.json().get("response", ""))
        except Exception as e:
            out.append(f"[vision_fallback_error: {e}]")
    return out


def run_ocr(
    path: Path,
    langs: list[str],
    dpi: int,
    vision_model: str | None,
    vision_endpoint: str,
    vision_timeout_s: int,
    ratio_threshold: float = 0.70,
) -> OCRResult:
    """Pipeline OCR complet : Tesseract puis vision pour pages sous le seuil."""
    texts, dims = ocr_tesseract(path, langs, dpi)
    page_ratios: list[float] = []
    weak_pages: list[int] = []
    for i, (txt, (w, h)) in enumerate(zip(texts, dims)):
        ratio = _normalize_ratio(len(txt.strip()), w * h)
        page_ratios.append(ratio)
        if ratio < ratio_threshold:
            weak_pages.append(i)

    engine = "tesseract"
    if weak_pages and vision_model:
        vision_texts = ocr_vision(
            path, weak_pages, dpi, vision_model, vision_endpoint, vision_timeout_s
        )
        for vp_idx, vt in zip(weak_pages, vision_texts):
            if vt and len(vt) > len(texts[vp_idx]):
                texts[vp_idx] = vt
        engine = "tesseract+vision"

    full_text = "\n\n".join(texts)
    overall_ratio = sum(page_ratios) / len(page_ratios) if page_ratios else 0.0
    return OCRResult(text=full_text, engine=engine, ratio_text=overall_ratio, pages=len(texts))
