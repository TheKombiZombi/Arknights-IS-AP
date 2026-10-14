#!/usr/bin/env python3
"""Import a complete user-supplied icon directory into canonical package assets.

No network access is performed. Source filenames are URL-decoded as UTF-8 before
matching catalog operator names, so apostrophes and non-ASCII names remain stable.
"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
from urllib.parse import unquote
import zlib

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "arknights_is"
OPERATORS_DIR = PACKAGE / "assets" / "operators"
LOCKED_OPERATORS_DIR = PACKAGE / "assets" / "operators_locked"
CLASSES_DIR = PACKAGE / "assets" / "classes"
MANIFEST_PATH = PACKAGE / "portrait_sources.json"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ASSET_PATTERN = re.compile(r"^(?P<size>\d+)px-(?P<name>.+?)(?P<operator>_icon)?\.png$")
PERCENT_PATTERN = re.compile(r"%(?![0-9A-Fa-f]{2})")


def load_metadata() -> tuple[list[str], list[str], dict[str, str]]:
    catalog = json.loads((PACKAGE / "catalog.json").read_text(encoding="utf8"))
    class_data = json.loads((PACKAGE / "operator_classes.json").read_text(encoding="utf8"))
    return catalog["operators"], class_data["classes"], class_data["operators"]


def decode_asset_name(filename: str) -> tuple[str, str]:
    """Return (kind, decoded name) for one accepted source PNG filename."""
    if PERCENT_PATTERN.search(filename):
        raise ValueError(f"malformed URL escape in source filename: {filename}")
    match = ASSET_PATTERN.fullmatch(filename)
    if not match:
        raise ValueError(f"unexpected source filename: {filename}")
    decoded = unquote(match.group("name"), encoding="utf8", errors="strict").replace("_", " ")
    return ("operator" if match.group("operator") else "class", decoded)


def png_dimensions(data: bytes, label: str) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != PNG_SIGNATURE or data[12:16] != b"IHDR":
        raise ValueError(f"{label}: not a valid PNG with an IHDR header")
    width, height = struct.unpack(">II", data[16:24])
    if not width or not height:
        raise ValueError(f"{label}: invalid PNG dimensions {width}x{height}")
    return width, height


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    return above if above_distance <= upper_left_distance else upper_left


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
    )


def grayscale_png(data: bytes, label: str) -> bytes:
    """Return a deterministic grayscale RGBA PNG without external image libraries."""
    width, height = png_dimensions(data, label)
    bit_depth, color_type, compression, filtering, interlace = struct.unpack(
        ">BBBBB", data[24:29]
    )
    if (bit_depth, color_type, compression, filtering, interlace) != (8, 6, 0, 0, 0):
        raise ValueError(f"{label}: expected non-interlaced 8-bit RGBA PNG")

    idat_parts: list[bytes] = []
    offset = 8
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        if kind == b"IDAT":
            idat_parts.append(payload)
        offset += 12 + length
        if kind == b"IEND":
            break

    packed = zlib.decompress(b"".join(idat_parts))
    stride = width * 4
    expected_size = height * (stride + 1)
    if len(packed) != expected_size:
        raise ValueError(f"{label}: unexpected decompressed PNG size")

    rows: list[bytearray] = []
    source_offset = 0
    for _row_index in range(height):
        filter_type = packed[source_offset]
        filtered = packed[source_offset + 1 : source_offset + 1 + stride]
        source_offset += stride + 1
        previous = rows[-1] if rows else bytearray(stride)
        row = bytearray(stride)
        for index, value in enumerate(filtered):
            left = row[index - 4] if index >= 4 else 0
            above = previous[index]
            upper_left = previous[index - 4] if index >= 4 else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            elif filter_type == 4:
                predictor = _paeth(left, above, upper_left)
            else:
                raise ValueError(f"{label}: unsupported PNG filter {filter_type}")
            row[index] = (value + predictor) & 0xFF
        rows.append(row)

    grayscale_rows = bytearray()
    for row in rows:
        grayscale_rows.append(0)
        for index in range(0, stride, 4):
            red, green, blue, alpha = row[index : index + 4]
            luminance = (77 * red + 150 * green + 29 * blue + 128) >> 8
            grayscale_rows.extend((luminance, luminance, luminance, alpha))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"".join(
        (
            PNG_SIGNATURE,
            _png_chunk(b"IHDR", header),
            _png_chunk(b"IDAT", zlib.compress(bytes(grayscale_rows), level=9)),
            _png_chunk(b"IEND", b""),
        )
    )


def scan_source(source: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    operators, classes, _operator_classes = load_metadata()
    expected_operators = set(operators)
    expected_classes = set(classes)
    found_operators: dict[str, Path] = {}
    found_classes: dict[str, Path] = {}
    for path in sorted(source.iterdir(), key=lambda candidate: candidate.name.encode("utf8")):
        if not path.is_file():
            raise ValueError(f"unexpected non-file in source directory: {path.name}")
        kind, name = decode_asset_name(path.name)
        target = found_operators if kind == "operator" else found_classes
        expected = expected_operators if kind == "operator" else expected_classes
        if name not in expected:
            raise ValueError(f"source {kind} is not in metadata: {name!r} ({path.name})")
        if name in target:
            raise ValueError(f"duplicate decoded {kind} name: {name!r}")
        target[name] = path
    missing_operators = expected_operators - set(found_operators)
    missing_classes = expected_classes - set(found_classes)
    if missing_operators or missing_classes:
        raise ValueError(
            f"incomplete source; missing operators={sorted(missing_operators)!r}, "
            f"missing classes={sorted(missing_classes)!r}"
        )
    return found_operators, found_classes


def record(name: str, operator_class: str, filename: str, source_filename: str, data: bytes) -> dict[str, object]:
    width, height = png_dimensions(data, source_filename)
    return {
        "name": name,
        "class": operator_class,
        "filename": filename,
        "source_filename": source_filename,
        "width": width,
        "height": height,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def build_manifest(operator_sources: dict[str, Path], class_sources: dict[str, Path]) -> tuple[dict[str, object], dict[Path, bytes]]:
    operators, classes, operator_classes = load_metadata()
    outputs: dict[Path, bytes] = {}
    operator_records = []
    for index, name in enumerate(operators):
        source = operator_sources[name]
        data = source.read_bytes()
        filename = f"{index:03d}.png"
        width, height = png_dimensions(data, source.name)
        if (width, height) != (90, 90):
            raise ValueError(f"{source.name}: expected 90x90 portrait, got {width}x{height}")
        locked_data = grayscale_png(data, source.name)
        outputs[OPERATORS_DIR / filename] = data
        outputs[LOCKED_OPERATORS_DIR / filename] = locked_data
        operator_record = record(name, operator_classes[name], filename, source.name, data)
        operator_record.update(
            {
                "locked_filename": filename,
                "locked_bytes": len(locked_data),
                "locked_sha256": hashlib.sha256(locked_data).hexdigest(),
            }
        )
        operator_records.append(operator_record)

    class_records = []
    for name in classes:
        source = class_sources[name]
        data = source.read_bytes()
        width, height = png_dimensions(data, source.name)
        if width > 48 or height > 48:
            raise ValueError(f"{source.name}: class icon exceeds 48x48: {width}x{height}")
        filename = f"{name}.png"
        outputs[CLASSES_DIR / filename] = data
        class_records.append(record(name, name, filename, source.name, data))

    manifest: dict[str, object] = {
        "schema_version": 3,
        "source": "user-authorized local icons directory (not retained)",
        "importer": "scripts/import_icons.py",
        "catalog_coverage": len(operator_records),
        "class_coverage": len(class_records),
        "assets_bundled": True,
        "locked_assets_bundled": True,
        "rights": (
            "Operator portraits and class icons are copyrighted game art supplied locally by the user. "
            "No redistribution permission is asserted."
        ),
        "operators": operator_records,
        "classes": class_records,
    }
    return manifest, outputs


def write_import(manifest: dict[str, object], outputs: dict[Path, bytes]) -> None:
    expected = set(outputs)
    for directory in (OPERATORS_DIR, LOCKED_OPERATORS_DIR, CLASSES_DIR):
        directory.mkdir(parents=True, exist_ok=True)
        for stale in directory.glob("*.png"):
            if stale not in expected:
                stale.unlink()
    for path, data in outputs.items():
        path.write_bytes(data)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf8")


def check_canonical() -> None:
    operators, classes, operator_classes = load_metadata()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf8"))
    if manifest.get("catalog_coverage") != len(operators) or manifest.get("class_coverage") != len(classes):
        raise ValueError("manifest coverage counts do not match metadata")
    if [entry["name"] for entry in manifest["operators"]] != operators:
        raise ValueError("manifest operator order does not exactly match catalog order")
    if [entry["name"] for entry in manifest["classes"]] != classes:
        raise ValueError("manifest class order does not exactly match class metadata")

    expected_operator_files = {f"{index:03d}.png" for index in range(len(operators))}
    expected_class_files = {f"{name}.png" for name in classes}
    if {path.name for path in OPERATORS_DIR.glob("*.png")} != expected_operator_files:
        raise ValueError("canonical portrait filenames do not exactly cover the catalog")
    if {path.name for path in LOCKED_OPERATORS_DIR.glob("*.png")} != expected_operator_files:
        raise ValueError("locked portrait filenames do not exactly cover the catalog")
    if {path.name for path in CLASSES_DIR.glob("*.png")} != expected_class_files:
        raise ValueError("canonical class-icon filenames do not cover all eight classes")

    for entry in manifest["operators"]:
        data = (OPERATORS_DIR / entry["filename"]).read_bytes()
        width, height = png_dimensions(data, entry["filename"])
        if hashlib.sha256(data).hexdigest() != entry["sha256"] or len(data) != entry["bytes"]:
            raise ValueError(f"canonical asset checksum mismatch: {entry['filename']}")
        if [width, height] != [entry["width"], entry["height"]]:
            raise ValueError(f"canonical asset dimensions mismatch: {entry['filename']}")
        locked_data = (LOCKED_OPERATORS_DIR / entry["locked_filename"]).read_bytes()
        if locked_data != grayscale_png(data, entry["filename"]):
            raise ValueError(f"locked portrait is not the deterministic grayscale asset: {entry['filename']}")
        if (
            hashlib.sha256(locked_data).hexdigest() != entry["locked_sha256"]
            or len(locked_data) != entry["locked_bytes"]
        ):
            raise ValueError(f"locked portrait checksum mismatch: {entry['filename']}")
        if entry["class"] != operator_classes[entry["name"]]:
            raise ValueError(f"manifest class mismatch: {entry['name']}")

    for entry in manifest["classes"]:
        directory = CLASSES_DIR
        data = (directory / entry["filename"]).read_bytes()
        width, height = png_dimensions(data, entry["filename"])
        if hashlib.sha256(data).hexdigest() != entry["sha256"] or len(data) != entry["bytes"]:
            raise ValueError(f"canonical asset checksum mismatch: {entry['filename']}")
        if [width, height] != [entry["width"], entry["height"]]:
            raise ValueError(f"canonical asset dimensions mismatch: {entry['filename']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, help="complete local source icon directory")
    parser.add_argument("--check", action="store_true", help="only validate canonical package assets")
    args = parser.parse_args()
    if args.check:
        if args.source is not None:
            parser.error("--check does not accept a source directory")
        check_canonical()
        operators, classes, _ = load_metadata()
        print(f"validated {len(operators)} portraits and {len(classes)} class icons")
        return 0
    if args.source is None:
        parser.error("a local source directory is required unless --check is used")
    operator_sources, class_sources = scan_source(args.source)
    manifest, outputs = build_manifest(operator_sources, class_sources)
    write_import(manifest, outputs)
    check_canonical()
    print(f"imported {len(operator_sources)} portraits and {len(class_sources)} class icons")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
