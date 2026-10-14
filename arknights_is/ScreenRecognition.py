"""Screenshot recognition for the manual Arknights IS client.

Recognition is pure: callers explicitly provide a file or in-memory frame, and this module
returns a high-confidence proposal without sending any Archipelago packet. The dashboard owns
the separately enabled live-capture lifecycle and automatic submission policy.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
import json
import importlib.util
from importlib.resources import files
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from typing import Any

NATIVE_SIZE = (1920, 1080)
NORMAL_CROP = (105, 700, 105 + 530, 700 + 78)
ENDING_CROP = (460, 270, 460 + 950, 270 + 150)
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png"}
MAX_DIRECTORY_IMAGES = 100
MIN_SCORE = 0.80
MIN_MARGIN = 0.15


class RecognitionError(RuntimeError):
    """A safe, user-facing recognition failure."""


@dataclass(frozen=True)
class RecognitionResult:
    source: str
    kind: str
    title: str
    ocr_text: str
    score: float
    runner_up_score: float
    location_names: tuple[str, ...]
    ending_location: str | None = None
    needs_ending_record: bool = False

    @property
    def confidence_summary(self) -> str:
        return (
            f"{self.score:.3f} confidence; "
            f"{self.score - self.runner_up_score:.3f} runner-up margin"
        )


@dataclass(frozen=True)
class RecognitionIssue:
    source: str
    message: str


@dataclass(frozen=True)
class RecognitionBatch:
    results: tuple[RecognitionResult, ...]
    issues: tuple[RecognitionIssue, ...]


OCRRunner = Callable[[Any, int], str]


def _pillow_available() -> bool:
    try:
        return importlib.util.find_spec("PIL") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


@lru_cache(maxsize=1)
def _tesseract_executable() -> str | None:
    found = shutil.which("tesseract")
    if found:
        return found
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if not base:
                continue
            candidate = Path(base) / "Tesseract-OCR" / "tesseract.exe"
            if candidate.is_file():
                return str(candidate)
    return None


def _subprocess_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def _clean_python_environment() -> dict[str, str]:
    environment = os.environ.copy()
    # Do not let the game/client working directory or an inherited development path shadow
    # Pillow when the trusted bundled helper starts a normal system Python.
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    return environment


@lru_cache(maxsize=1)
def _external_pillow_python() -> tuple[str, ...] | None:
    """Find a normal Python with Pillow for frozen Archipelago distributions.

    Official Windows builds deliberately exclude PIL. A small packaged helper lets the
    APWorld use the player's ordinary Python installation instead of asking them to modify
    Archipelago's frozen runtime.
    """

    candidates: list[tuple[str, ...]] = []
    if os.name == "nt" and shutil.which("py"):
        candidates.append((shutil.which("py") or "py", "-3"))
    for name in ("python", "python3"):
        executable = shutil.which(name)
        if executable:
            candidate = (executable,)
            if candidate not in candidates:
                candidates.append(candidate)
    for command in candidates:
        try:
            completed = subprocess.run(
                [*command, "-P", "-c", "from PIL import Image, ImageGrab; print('ok')"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                env=_clean_python_environment(),
                creationflags=_subprocess_flags(),
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode == 0 and completed.stdout.strip() == "ok":
            return command
    return None


def _external_helper_available() -> bool:
    return _external_pillow_python() is not None


def normalize_text(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.casefold()).strip()


def display_ending_name(catalog_name: str) -> str:
    return re.sub(r"\s+\(ED\d+\)$", "", catalog_name).strip()


def validate_normal_stage_names(catalog: Mapping[str, Any]) -> None:
    """Reject title-only recognition when the catalog cannot identify a unique stage."""

    seen: dict[str, str] = {}
    duplicates: list[tuple[str, str]] = []
    for mode, data in catalog["modes"].items():
        for entry in data["normal"]:
            title = str(entry["name"])
            key = normalize_text(title)
            prior = seen.get(key)
            if prior is not None:
                duplicates.append((prior, f"{mode}: {title}"))
            else:
                seen[key] = f"{mode}: {title}"
    if duplicates:
        details = "; ".join(f"{left} / {right}" for left, right in duplicates)
        raise RecognitionError(
            "Screen recognition is disabled because normal-operation titles are not unique: "
            + details
        )


def capability_problem() -> str | None:
    missing = []
    if not _pillow_available() and not _external_helper_available():
        missing.append(
            "Pillow in a normal Python installation "
            "(run 'py -m pip install Pillow' on Windows)"
        )
    if _tesseract_executable() is None:
        missing.append("Tesseract OCR ('tesseract' executable)")
    if not missing:
        return None
    return (
        "Screenshot recognition is unavailable. Install "
        + " and ".join(missing)
        + ", then restart the manual client. Manual check submission remains available."
    )


def capture_capability_problem() -> str | None:
    problem = capability_problem()
    if problem:
        return problem
    if not _pillow_available():
        return None
    try:
        from PIL import ImageGrab  # noqa: F401
    except (ImportError, OSError) as exc:
        return f"Live capture is unavailable through Pillow ImageGrab: {exc}"
    return None


def _default_ocr(image: Any, psm: int) -> str:
    with tempfile.TemporaryDirectory(prefix="arknights-is-ocr-") as directory:
        image_path = Path(directory) / "crop.png"
        image.save(image_path, format="PNG")
        try:
            completed = subprocess.run(
                [
                    _tesseract_executable() or "tesseract",
                    str(image_path),
                    "stdout",
                    "--psm",
                    str(psm),
                    "-l",
                    "eng",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RecognitionError(f"Tesseract OCR could not run: {exc}") from exc
    if completed.returncode:
        detail = completed.stderr.strip() or f"exit status {completed.returncode}"
        raise RecognitionError(f"Tesseract OCR failed: {detail}")
    return completed.stdout.strip()


def _run_external_helper(mode: str, path: str | Path | None = None) -> dict[str, Any]:
    command = _external_pillow_python()
    tesseract = _tesseract_executable()
    if command is None or tesseract is None:
        raise RecognitionError(capability_problem() or "External recognition helper is unavailable.")
    if __package__:
        helper_source = files(__package__).joinpath("RecognitionHelper.py").read_text(encoding="utf8")
    else:  # Direct module loading in focused tests and local diagnostics.
        helper_source = Path(__file__).with_name("RecognitionHelper.py").read_text(encoding="utf8")
    args = [*command, "-P", "-c", helper_source, mode]
    if path is not None:
        args.append(str(path))
    environment = _clean_python_environment()
    environment["ARKNIGHTS_TESSERACT"] = tesseract
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
            env=environment,
            creationflags=_subprocess_flags(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RecognitionError(f"External screenshot helper could not run: {exc}") from exc
    payload = None
    for line in reversed(completed.stdout.splitlines()):
        try:
            payload = json.loads(line)
            break
        except json.JSONDecodeError:
            continue
    if not isinstance(payload, dict):
        detail = completed.stderr.strip() or completed.stdout.strip() or "no helper output"
        raise RecognitionError(f"External screenshot helper failed: {detail}")
    if completed.returncode or payload.get("error"):
        raise RecognitionError(f"External screenshot helper failed: {payload.get('error', 'unknown error')}")
    return payload


def _prepare_crop(image: Any, box: tuple[int, int, int, int], scale: int) -> Any:
    from PIL import ImageFilter, ImageOps

    crop = ImageOps.grayscale(image.crop(box))
    crop = ImageOps.autocontrast(crop)
    crop = crop.resize((crop.width * scale, crop.height * scale))
    return crop.filter(ImageFilter.SHARPEN)


def _score(ocr_text: str, expected: str) -> float:
    return SequenceMatcher(None, normalize_text(ocr_text), normalize_text(expected)).ratio()


def _rank(value: str, candidates: Iterable[tuple[str, str]]) -> tuple[str, str, float, float]:
    ranked = sorted(
        ((_score(value, title), title, location) for title, location in candidates),
        key=lambda row: (row[0], row[1]),
        reverse=True,
    )
    if not ranked:
        raise RecognitionError("No eligible unresolved locations are available for recognition.")
    best_score, best_title, best_location = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
    return best_title, best_location, best_score, runner_up


def _confident(score: float, runner_up: float) -> bool:
    return score >= MIN_SCORE and score - runner_up >= MIN_MARGIN


def _normal_candidates(catalog: Mapping[str, Any]) -> list[tuple[str, str]]:
    result = []
    for mode, data in catalog["modes"].items():
        for entry in data["normal"]:
            location = f'{mode} — Floor {entry["floor"]}: {entry["name"]}'
            result.append((str(entry["name"]), location))
    return result


def _ending_candidates(catalog: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    return [
        (display_ending_name(catalog_name), mode, catalog_name)
        for mode, data in catalog["modes"].items()
        for catalog_name in data["endings"]
    ]


def _extract_witnessed_title(ocr_text: str) -> str | None:
    match = re.search(r"\bWitnessed\s+the\s+([^\r\n]+)", ocr_text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _recognize_ocr_texts(
    source: str,
    width: int,
    height: int,
    ending_ocr: str,
    normal_ocr: str,
    catalog: Mapping[str, Any],
    location_ids: Mapping[str, int],
    checked_locations: Iterable[int],
    completed_endings: Iterable[str] = (),
) -> RecognitionResult:
    """Turn helper/in-process OCR text into one side-effect-free proposal."""

    validate_normal_stage_names(catalog)
    if (width, height) != NATIVE_SIZE:
        raise RecognitionError(
            f"Expected a native 1920×1080 screenshot; got {width}×{height}."
        )
    checked = set(checked_locations)
    completed = set(completed_endings)
    witnessed = _extract_witnessed_title(ending_ocr)
    if witnessed:
        ending_rows = _ending_candidates(catalog)
        title, marker, score, runner_up = _rank(
            witnessed,
            ((title, f"{mode}\0{catalog_name}") for title, mode, catalog_name in ending_rows),
        )
        if not _confident(score, runner_up):
            raise RecognitionError(
                f"Ending text was ambiguous ({score:.3f} best, {runner_up:.3f} runner-up): "
                f"{witnessed!r}"
            )
        mode, catalog_name = marker.split("\0", 1)
        ending_location = f"{mode} — Ending: {catalog_name}"
        any_ending = f"{mode} — Any Ending Cleared"
        actionable = []
        for location in (ending_location, any_ending):
            code = location_ids.get(location)
            if code is not None and code not in checked:
                actionable.append(location)
        needs_record = ending_location not in completed
        if not actionable and not needs_record:
            raise RecognitionError(f"Recognized {title}, but its checks are already resolved.")
        return RecognitionResult(
            source,
            "ending",
            title,
            ending_ocr,
            score,
            runner_up,
            tuple(actionable),
            ending_location,
            needs_record,
        )

    title, location, score, runner_up = _rank(normal_ocr, _normal_candidates(catalog))
    if not _confident(score, runner_up):
        raise RecognitionError(
            f"No unique high-confidence normal-operation match "
            f"({score:.3f} best, {runner_up:.3f} runner-up): {normal_ocr!r}"
        )
    code = location_ids.get(location)
    if code is None:
        raise RecognitionError(f"Recognized {title}, but that location is not active in this slot.")
    if code in checked:
        raise RecognitionError(f"Recognized {title}, but its check is already resolved.")
    return RecognitionResult(source, "operation", title, normal_ocr, score, runner_up, (location,))


def recognize_frame(
    image: Any,
    source: str,
    catalog: Mapping[str, Any],
    location_ids: Mapping[str, int],
    checked_locations: Iterable[int],
    completed_endings: Iterable[str] = (),
    *,
    ocr_runner: OCRRunner | None = None,
) -> RecognitionResult:
    """Recognize one supplied native 1920x1080 frame without side effects."""

    problem = capability_problem() if ocr_runner is None else None
    if problem:
        raise RecognitionError(problem)
    if image.size != NATIVE_SIZE:
        raise RecognitionError(
            f"Expected a native 1920×1080 screenshot; got {image.width}×{image.height}."
        )
    image = image.convert("RGB")
    run_ocr = ocr_runner or _default_ocr
    ending_ocr = run_ocr(_prepare_crop(image, ENDING_CROP, 4), 6)
    normal_ocr = "" if _extract_witnessed_title(ending_ocr) else run_ocr(
        _prepare_crop(image, NORMAL_CROP, 5), 13
    )
    return _recognize_ocr_texts(
        source,
        image.width,
        image.height,
        ending_ocr,
        normal_ocr,
        catalog,
        location_ids,
        checked_locations,
        completed_endings,
    )


def recognize_live_capture(
    catalog: Mapping[str, Any],
    location_ids: Mapping[str, int],
    checked_locations: Iterable[int],
    completed_endings: Iterable[str] = (),
    previous_signature: str | None = None,
) -> tuple[str, RecognitionResult | None]:
    """Capture and recognize the primary display using in-process or external Pillow."""

    problem = capture_capability_problem()
    if problem:
        raise RecognitionError(problem)
    if _pillow_available():
        from PIL import ImageGrab

        frame = ImageGrab.grab(all_screens=False)
        import hashlib

        signature = hashlib.sha256(frame.convert("RGB").resize((64, 36)).tobytes()).hexdigest()
        if previous_signature and signature == previous_signature:
            return signature, None
        return signature, recognize_frame(
            frame,
            "live primary display",
            catalog,
            location_ids,
            checked_locations,
            completed_endings,
        )
    payload = _run_external_helper("live", previous_signature)
    if payload.get("unchanged"):
        return str(payload["signature"]), None
    result = _recognize_ocr_texts(
        str(payload.get("source", "live primary display")),
        int(payload["width"]),
        int(payload["height"]),
        str(payload.get("ending_ocr", "")),
        str(payload.get("normal_ocr", "")),
        catalog,
        location_ids,
        checked_locations,
        completed_endings,
    )
    return str(payload["signature"]), result


def recognize_image(
    path: str | Path,
    catalog: Mapping[str, Any],
    location_ids: Mapping[str, int],
    checked_locations: Iterable[int],
    completed_endings: Iterable[str] = (),
    *,
    ocr_runner: OCRRunner | None = None,
) -> RecognitionResult:
    """Recognize one explicitly supplied native 1920x1080 result screenshot."""

    source = Path(path).expanduser()
    if not source.is_file():
        raise RecognitionError(f"Screenshot does not exist or is not a file: {source}")
    if source.suffix.casefold() not in SUPPORTED_SUFFIXES:
        raise RecognitionError(f"Unsupported screenshot type: {source.suffix or '(none)'}")
    problem = capability_problem() if ocr_runner is None else None
    if problem:
        raise RecognitionError(problem)
    if ocr_runner is None and not _pillow_available():
        payload = _run_external_helper("file", source)
        return _recognize_ocr_texts(
            str(source),
            int(payload["width"]),
            int(payload["height"]),
            str(payload.get("ending_ocr", "")),
            str(payload.get("normal_ocr", "")),
            catalog,
            location_ids,
            checked_locations,
            completed_endings,
        )
    try:
        from PIL import Image, UnidentifiedImageError
        with Image.open(source) as opened:
            opened.load()
            image = opened.convert("RGB")
    except (OSError, UnidentifiedImageError) as exc:
        raise RecognitionError(f"Could not read screenshot: {exc}") from exc
    return recognize_frame(
        image,
        str(source),
        catalog,
        location_ids,
        checked_locations,
        completed_endings,
        ocr_runner=ocr_runner,
    )


def recognize_path(
    path: str | Path,
    catalog: Mapping[str, Any],
    location_ids: Mapping[str, int],
    checked_locations: Iterable[int],
    completed_endings: Iterable[str] = (),
    *,
    ocr_runner: OCRRunner | None = None,
) -> RecognitionBatch:
    """Recognize one selected image or the supported images directly inside a directory."""

    selected = Path(path).expanduser()
    if selected.is_dir():
        images = sorted(
            (
                child
                for child in selected.iterdir()
                if child.is_file() and child.suffix.casefold() in SUPPORTED_SUFFIXES
            ),
            key=lambda child: child.name.casefold(),
        )
        if len(images) > MAX_DIRECTORY_IMAGES:
            return RecognitionBatch(
                (),
                (RecognitionIssue(str(selected), f"Directory contains more than {MAX_DIRECTORY_IMAGES} images."),),
            )
        if not images:
            return RecognitionBatch((), (RecognitionIssue(str(selected), "Directory contains no supported images."),))
    else:
        images = [selected]

    results: list[RecognitionResult] = []
    issues: list[RecognitionIssue] = []
    reserved_locations: set[str] = set()
    for image in images:
        try:
            result = recognize_image(
                image,
                catalog,
                location_ids,
                checked_locations,
                completed_endings,
                ocr_runner=ocr_runner,
            )
        except RecognitionError as exc:
            issues.append(RecognitionIssue(str(image), str(exc)))
            continue
        # A folder can contain duplicate captures. Present each Archipelago action only once.
        new_locations = tuple(
            location for location in result.location_names if location not in reserved_locations
        )
        duplicate_record = any(
            prior.ending_location == result.ending_location and prior.needs_ending_record
            for prior in results
        )
        needs_record = result.needs_ending_record and not duplicate_record
        if not new_locations and not needs_record:
            issues.append(RecognitionIssue(str(image), f"Duplicate recognized result: {result.title}"))
            continue
        reserved_locations.update(new_locations)
        results.append(
            RecognitionResult(
                result.source,
                result.kind,
                result.title,
                result.ocr_text,
                result.score,
                result.runner_up_score,
                new_locations,
                result.ending_location,
                needs_record,
            )
        )
    return RecognitionBatch(tuple(results), tuple(issues))
