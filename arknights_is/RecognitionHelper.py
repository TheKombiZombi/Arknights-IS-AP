"""External Pillow bridge for frozen Archipelago clients.

This file is executed by a normal system Python when Archipelago's bundled runtime does not
contain Pillow. It emits one JSON object and never writes a full screenshot to disk.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from PIL import Image, ImageFilter, ImageGrab, ImageOps, UnidentifiedImageError

NATIVE_SIZE = (1920, 1080)
NORMAL_CROP = (105, 700, 105 + 530, 700 + 78)
ENDING_CROP = (460, 270, 460 + 950, 270 + 150)


def prepare_crop(image, box, scale):
    crop = ImageOps.grayscale(image.crop(box))
    crop = ImageOps.autocontrast(crop)
    crop = crop.resize((crop.width * scale, crop.height * scale))
    return crop.filter(ImageFilter.SHARPEN)


def run_ocr(image, psm):
    executable = os.environ.get("ARKNIGHTS_TESSERACT", "tesseract")
    with tempfile.TemporaryDirectory(prefix="arknights-is-ocr-") as directory:
        image_path = Path(directory) / "crop.png"
        image.save(image_path, format="PNG")
        completed = subprocess.run(
            [executable, str(image_path), "stdout", "--psm", str(psm), "-l", "eng"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or f"Tesseract exited with {completed.returncode}")
    return completed.stdout.strip()


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in {"live", "file"}:
        raise RuntimeError("Expected live or file mode")
    if sys.argv[1] == "live":
        image = ImageGrab.grab(all_screens=False)
        source = "live primary display"
    else:
        if len(sys.argv) != 3:
            raise RuntimeError("File mode requires one screenshot path")
        source = sys.argv[2]
        try:
            with Image.open(source) as opened:
                opened.load()
                image = opened.convert("RGB")
        except (OSError, UnidentifiedImageError) as exc:
            raise RuntimeError(f"Could not read screenshot: {exc}") from exc
    image = image.convert("RGB")
    signature = hashlib.sha256(image.resize((64, 36)).tobytes()).hexdigest()
    previous_signature = sys.argv[2] if sys.argv[1] == "live" and len(sys.argv) > 2 else ""
    if previous_signature and signature == previous_signature:
        print(json.dumps({
            "source": source,
            "width": image.width,
            "height": image.height,
            "signature": signature,
            "unchanged": True,
        }))
        return
    ending_ocr = run_ocr(prepare_crop(image, ENDING_CROP, 4), 6)
    normal_ocr = ""
    if not re.search(r"\bWitnessed\s+the\s+", ending_ocr, re.IGNORECASE):
        normal_ocr = run_ocr(prepare_crop(image, NORMAL_CROP, 5), 13)
    print(json.dumps({
        "source": source,
        "width": image.width,
        "height": image.height,
        "signature": signature,
        "ending_ocr": ending_ocr,
        "normal_ocr": normal_ocr,
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
