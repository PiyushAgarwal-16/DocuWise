"""
core/ocr.py — Optical Character Recognition layer for DocuWise (Phase 3 & 8).

Architecture
------------
    BaseOCREngine   (abstract interface — the ONLY thing the pipeline knows about)
        ├── RapidOCREngine    (default — ONNX Runtime-backed, fast CPU inference)
        └── PaddleOCREngine   (legacy — requires paddlepaddle, slower on CPU)

The extraction pipeline never imports OCR libraries directly. It only depends on
``BaseOCREngine`` and the ``get_ocr_engine()`` factory, so engines can be swapped
by changing ``config.OCR_ENGINE``.

Performance (Phase 8)
---------------------
  - RapidOCR loads in ~3s (vs ~12s for PaddleOCR) with models bundled in-package.
  - No separate model downloads, no paddlepaddle dependency, no numpy conflicts.
  - Uses ONNX Runtime for CPU-optimized inference with multi-threading.
  - Images are downscaled to ``OCR_MAX_IMAGE_SIZE`` before recognition.

Resilience (Phase 12)
---------------------
  - If the OCR library is not installed or fails to initialise, ``get_ocr_engine()``
    returns an engine whose ``is_available()`` is False. Callers then skip OCR
    and fall back to native text / ``image_only`` — OCR failure never crashes a
    scan.

This module does NOT perform:
  - PDF rendering (that is the extractor's job — it hands raster images here)
  - Any database or UI interaction
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from config import (
    OCR_ENGINE,
    OCR_LANGUAGE,
    OCR_MAX_IMAGE_SIZE,
    OCR_VERSION,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class OCRResult:
    """
    Structured result of OCR over a single image (one PDF page or one image file).

    Attributes:
        text:       Recognised plain text (newline-joined lines). Empty on failure.
        confidence: Mean confidence of recognised lines in [0.0, 1.0]. 0.0 if none.
        line_count: Number of text lines recognised.
        success:    True if OCR ran without raising. Note: a successful run may
                    still yield empty text for a blank page.
        error_message: Human-readable failure reason, or None.
    """
    text: str = ""
    confidence: float = 0.0
    line_count: int = 0
    success: bool = False
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Abstract base — the pipeline's only OCR dependency
# ---------------------------------------------------------------------------

class BaseOCREngine(ABC):
    """
    Interface every OCR engine must implement.

    Concrete engines are responsible for their own (lazy) model loading and for
    never raising out of :meth:`recognize` — a failed page must return an
    ``OCRResult`` with ``success=False`` rather than propagating an exception.
    """

    #: Short engine identifier persisted with every result (e.g. "paddleocr").
    name: str = "base"

    #: Engine/model version tag persisted for cache-invalidation on upgrades.
    version: str = "0"

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the engine loaded successfully and can run OCR."""

    @abstractmethod
    def recognize(self, image: Any) -> OCRResult:
        """
        Run OCR over a single in-memory image.

        Args:
            image: An image accepted by the concrete engine. The PaddleOCR
                   implementation accepts a NumPy ``ndarray`` (H×W×3, RGB) or a
                   PIL ``Image``; both are normalised internally.

        Returns:
            An :class:`OCRResult`. Never raises — failures are reported via
            ``success=False`` and ``error_message``.
        """

    def warmup(self) -> None:
        """
        Optionally trigger model loading ahead of first use.

        Default implementation is a no-op. Engines with expensive initialisation
        override this so the first real document does not pay the load cost.
        """
        return None


# ---------------------------------------------------------------------------
# Null engine — used when no OCR backend is available
# ---------------------------------------------------------------------------

class _UnavailableOCREngine(BaseOCREngine):
    """
    Sentinel engine returned when the configured backend cannot be loaded.

    ``is_available()`` is always False and ``recognize()`` always reports a
    failure, so the extractor transparently falls back to native text / the
    ``image_only`` state without any special-casing.
    """

    name = "none"
    version = "0"

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def is_available(self) -> bool:
        return False

    def recognize(self, image: Any) -> OCRResult:
        return OCRResult(success=False, error_message=f"OCR unavailable: {self._reason}")


# ---------------------------------------------------------------------------
# RapidOCR engine (default — ONNX Runtime)
# ---------------------------------------------------------------------------

class RapidOCREngine(BaseOCREngine):
    """
    RapidOCR-backed OCR engine using ONNX Runtime.

    Uses the same PP-OCR models as PaddleOCR but exported to ONNX format,
    running through ONNX Runtime instead of PaddlePaddle. This eliminates
    all heavy-framework dependencies and provides faster CPU inference.

    Models are bundled inside the ``rapidocr_onnxruntime`` pip package (~15 MB),
    so there are no first-run model downloads.
    """

    name = "rapidocr"

    def __init__(self, language: str = OCR_LANGUAGE, version: str = OCR_VERSION) -> None:
        import threading
        self.version = version
        self._language = language
        self._model: Optional[Any] = None
        self._load_error: Optional[str] = None
        self._lock = threading.Lock()

    def _ensure_model(self) -> bool:
        """Lazily construct the RapidOCR model. Thread-safe."""
        if self._model is not None:
            return True
        if self._load_error is not None:
            return False

        with self._lock:
            if self._model is not None:
                return True
            if self._load_error is not None:
                return False

            try:
                from rapidocr_onnxruntime import RapidOCR
            except Exception as exc:  # noqa: BLE001
                self._load_error = f"rapidocr import failed: {exc}"
                logger.warning(
                    "OCR disabled — %s. Install with: pip install rapidocr_onnxruntime",
                    self._load_error,
                )
                return False

            try:
                import os
                threads = min(os.cpu_count() or 4, 8)
                t0 = time.time()
                self._model = RapidOCR(
                    rec_batch_num=1,
                    intra_op_num_threads=threads,
                )
                logger.info(
                    "RapidOCR model loaded (threads=%d, %.1fs) — %s",
                    threads, time.time() - t0, self.version,
                )
                return True
            except Exception as exc:  # noqa: BLE001
                self._load_error = f"RapidOCR init failed: {exc}"
                logger.error("OCR disabled — %s", self._load_error)
                return False

    def is_available(self) -> bool:
        return self._ensure_model()

    def warmup(self) -> None:
        self._ensure_model()

    def recognize(self, image: Any) -> OCRResult:
        if not self._ensure_model():
            return OCRResult(success=False, error_message=self._load_error or "model not loaded")

        try:
            array = self._to_ndarray(image)
        except Exception as exc:  # noqa: BLE001
            return OCRResult(success=False, error_message=f"image conversion failed: {exc}")

        try:
            result, _elapse = self._model(array)
            if not result:
                return OCRResult(text="", confidence=0.0, line_count=0, success=True)

            texts = []
            confidences = []
            for line in result:
                # line = [box_coords, text, confidence]
                text = str(line[1]).strip()
                conf = float(line[2])
                if text:
                    texts.append(text)
                    confidences.append(conf)

            text = "\n".join(texts).strip()
            confidence = (sum(confidences) / len(confidences)) if confidences else 0.0
            return OCRResult(
                text=text,
                confidence=round(float(confidence), 4),
                line_count=len(texts),
                success=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("RapidOCR recognition error: %s", exc)
            return OCRResult(success=False, error_message=f"OCR error: {exc}")

    @staticmethod
    def _to_ndarray(image: Any):
        """Normalise image to RGB ndarray, downscale if oversized."""
        import numpy as np

        if hasattr(image, "convert") and hasattr(image, "size"):
            pil = image.convert("RGB")
            w, h = pil.size
            longest = max(w, h)
            if longest > OCR_MAX_IMAGE_SIZE:
                scale = OCR_MAX_IMAGE_SIZE / longest
                pil = pil.resize((max(1, int(w * scale)), max(1, int(h * scale))))
            return np.asarray(pil)

        arr = np.asarray(image)
        if arr.ndim == 2:
            arr = np.stack([arr] * 3, axis=-1)
        elif arr.ndim == 3 and arr.shape[2] == 4:
            arr = arr[:, :, :3]
        return arr


# ---------------------------------------------------------------------------
# PaddleOCR engine (legacy)
# ---------------------------------------------------------------------------

class PaddleOCREngine(BaseOCREngine):
    """
    PaddleOCR-backed OCR engine.

    The underlying ``PaddleOCR`` object is created lazily on the first call and
    then reused for the lifetime of the process (see :func:`get_ocr_engine` — a
    single instance of this class is cached module-wide, and it in turn caches
    the model). PaddleOCR is imported lazily so that this module imports cleanly
    even when the ``paddleocr`` package is absent.
    """

    name = "paddleocr"

    def __init__(self, language: str = OCR_LANGUAGE, version: str = OCR_VERSION) -> None:
        import threading
        self.version = version
        self._language = language
        self._model: Optional[Any] = None
        self._load_error: Optional[str] = None
        self._use_predict_api = False  # PaddleOCR ≥ 3.0 renamed .ocr() → .predict()
        self._lock = threading.Lock()  # Prevent double-loading from concurrent threads

    # -- model loading ------------------------------------------------------

    def _ensure_model(self) -> bool:
        """
        Lazily construct the PaddleOCR model. Returns True if usable.

        The result (success or the failure reason) is memoised so a missing
        dependency is only diagnosed once per process instead of on every page.
        Thread-safe: uses a lock to prevent concurrent loads.
        """
        if self._model is not None:
            return True
        if self._load_error is not None:
            return False

        with self._lock:
            # Double-check after acquiring lock (another thread may have loaded it)
            if self._model is not None:
                return True
            if self._load_error is not None:
                return False

            try:
                from paddleocr import PaddleOCR  # lazy, heavy import
            except Exception as exc:  # noqa: BLE001 — ImportError or transitive failure
                self._load_error = f"paddleocr import failed: {exc}"
                logger.warning(
                    "OCR disabled — %s. Install with: pip install paddleocr paddlepaddle",
                    self._load_error,
                )
                return False

            # PaddleOCR's constructor signature has drifted across versions. Try the
            # most optimized keyword set first (MKLDNN for CPU acceleration), then
            # fall back to simpler configs.
            import os
            cpu_threads = min(os.cpu_count() or 4, 8)  # Use up to 8 cores
            last_exc: Optional[Exception] = None
            for kwargs in (
                {"use_angle_cls": True, "lang": self._language, "show_log": False,
                 "enable_mkldnn": True, "cpu_threads": cpu_threads},
                {"use_angle_cls": True, "lang": self._language, "show_log": False},
                {"use_angle_cls": True, "lang": self._language},
                {"lang": self._language},
                {},
            ):
                try:
                    t0 = time.time()
                    self._model = PaddleOCR(**kwargs)
                    self._use_predict_api = not hasattr(self._model, "ocr")
                    logger.info(
                        "PaddleOCR model loaded (lang=%s, %.1fs) — %s",
                        self._language, time.time() - t0, self.version,
                    )
                    return True
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    continue

            self._load_error = f"PaddleOCR init failed: {last_exc}"
            logger.error("OCR disabled — %s", self._load_error)
            return False

    def is_available(self) -> bool:
        return self._ensure_model()

    def warmup(self) -> None:
        self._ensure_model()

    # -- recognition --------------------------------------------------------

    def recognize(self, image: Any) -> OCRResult:
        if not self._ensure_model():
            return OCRResult(success=False, error_message=self._load_error or "model not loaded")

        try:
            array = self._to_ndarray(image)
        except Exception as exc:  # noqa: BLE001
            return OCRResult(success=False, error_message=f"image conversion failed: {exc}")

        try:
            raw = self._run_model(array)
            texts, confidences = self._parse_output(raw)
            text = "\n".join(texts).strip()
            confidence = (sum(confidences) / len(confidences)) if confidences else 0.0
            return OCRResult(
                text=text,
                confidence=round(float(confidence), 4),
                line_count=len(texts),
                success=True,
            )
        except Exception as exc:  # noqa: BLE001 — OCR must never crash the caller
            logger.warning("PaddleOCR recognition error: %s", exc)
            return OCRResult(success=False, error_message=f"OCR error: {exc}")

    def _run_model(self, array: Any) -> Any:
        """Invoke the model, tolerating both the .ocr() and .predict() APIs."""
        model = self._model
        if self._use_predict_api and hasattr(model, "predict"):
            return model.predict(array)
        try:
            return model.ocr(array, cls=True)
        except TypeError:
            # Older/newer builds may not accept the `cls` keyword.
            return model.ocr(array)

    # -- helpers ------------------------------------------------------------

    def _to_ndarray(self, image: Any):
        """
        Normalise *image* to an RGB ``numpy.ndarray`` and downscale if oversized.

        Accepts a NumPy array or a PIL Image. Downscaling to
        ``OCR_MAX_IMAGE_SIZE`` on the longest edge bounds memory and latency.
        """
        import numpy as np

        # PIL Image → ndarray
        if hasattr(image, "convert") and hasattr(image, "size"):
            pil = image.convert("RGB")
            pil = self._downscale_pil(pil)
            return np.asarray(pil)

        arr = np.asarray(image)
        if arr.ndim == 2:  # grayscale → RGB
            arr = np.stack([arr] * 3, axis=-1)
        elif arr.ndim == 3 and arr.shape[2] == 4:  # RGBA → RGB
            arr = arr[:, :, :3]
        return self._downscale_ndarray(arr)

    @staticmethod
    def _downscale_pil(pil):
        w, h = pil.size
        longest = max(w, h)
        if longest > OCR_MAX_IMAGE_SIZE:
            scale = OCR_MAX_IMAGE_SIZE / longest
            pil = pil.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        return pil

    @staticmethod
    def _downscale_ndarray(arr):
        h, w = arr.shape[:2]
        longest = max(w, h)
        if longest <= OCR_MAX_IMAGE_SIZE:
            return arr
        try:
            from PIL import Image
        except Exception:  # noqa: BLE001 — Pillow missing: skip downscale, OCR still works
            return arr
        scale = OCR_MAX_IMAGE_SIZE / longest
        pil = Image.fromarray(arr).resize((max(1, int(w * scale)), max(1, int(h * scale))))
        import numpy as np
        return np.asarray(pil)

    @staticmethod
    def _parse_output(raw: Any) -> tuple[list[str], list[float]]:
        """
        Extract (texts, confidences) from PaddleOCR output across API versions.

        Legacy ``.ocr()`` returns::

            [[ [box, (text, conf)], [box, (text, conf)], ... ]]   # one item per image

        Newer ``.predict()`` returns a list of dict-like results carrying
        ``rec_texts`` / ``rec_scores``. Both shapes are handled defensively.
        """
        texts: list[str] = []
        confidences: list[float] = []

        if not raw:
            return texts, confidences

        # Newer predict() dict format
        first = raw[0] if isinstance(raw, (list, tuple)) and raw else None
        if isinstance(first, dict) or hasattr(first, "get"):
            for item in raw:
                rec_texts = item.get("rec_texts") if hasattr(item, "get") else None
                rec_scores = item.get("rec_scores") if hasattr(item, "get") else None
                if rec_texts:
                    for i, t in enumerate(rec_texts):
                        if t and str(t).strip():
                            texts.append(str(t).strip())
                            try:
                                confidences.append(float(rec_scores[i]))
                            except (IndexError, TypeError, ValueError):
                                pass
            return texts, confidences

        # Legacy .ocr() nested list format
        pages = raw
        # .ocr() wraps results in an outer list (one entry per image); unwrap it.
        if len(pages) == 1 and isinstance(pages[0], list):
            candidate = pages[0]
            # Distinguish [ [box,(text,conf)], ... ] from a single [box,(text,conf)]
            if candidate and isinstance(candidate[0], (list, tuple)):
                pages = candidate

        for line in pages:
            try:
                # line == [box, (text, confidence)]
                payload = line[1]
                text = payload[0]
                conf = float(payload[1])
                if text and str(text).strip():
                    texts.append(str(text).strip())
                    confidences.append(conf)
            except (IndexError, TypeError, ValueError):
                continue

        return texts, confidences


# ---------------------------------------------------------------------------
# Engine factory (singleton — Phase 8)
# ---------------------------------------------------------------------------

_engine_instance: Optional[BaseOCREngine] = None


def get_ocr_engine() -> BaseOCREngine:
    """
    Return the process-wide OCR engine singleton, constructing it on first call.

    Selection is driven by ``config.OCR_ENGINE``. Unknown engines and load
    failures yield an :class:`_UnavailableOCREngine` so callers can rely on
    ``is_available()`` and never need a try/except around engine construction.

    Returns:
        A ready :class:`BaseOCREngine`. Always non-None. Cheap on repeat calls.
    """
    global _engine_instance
    if _engine_instance is not None:
        return _engine_instance

    name = (OCR_ENGINE or "").strip().lower()
    if name == "rapidocr":
        _engine_instance = RapidOCREngine()
    elif name == "paddleocr":
        _engine_instance = PaddleOCREngine()
    elif name in ("", "none", "disabled"):
        _engine_instance = _UnavailableOCREngine("OCR_ENGINE not configured")
    else:
        # Tesseract is explicitly out of scope (Phase 3). Any other value is a
        # misconfiguration — degrade gracefully rather than crash.
        _engine_instance = _UnavailableOCREngine(f"unsupported OCR_ENGINE '{OCR_ENGINE}'")
        logger.warning("Unsupported OCR_ENGINE '%s' — OCR disabled.", OCR_ENGINE)

    return _engine_instance


def reset_ocr_engine() -> None:
    """Drop the cached engine so the next :func:`get_ocr_engine` rebuilds it.

    Primarily a testing aid; also useful if OCR configuration changes at runtime.
    """
    global _engine_instance
    _engine_instance = None
