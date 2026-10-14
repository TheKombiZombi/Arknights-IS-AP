from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from scripts.import_icons import check_canonical

ROOT = Path(__file__).parent
OUTPUT = ROOT / "dist"
TARGET = OUTPUT / "arknights_integrated_strategies.apworld"
PACKAGE_ROOT = "arknights_integrated_strategies"
INCLUDED_SUFFIXES = {".py", ".json", ".png"}

check_canonical()
OUTPUT.mkdir(exist_ok=True)
with ZipFile(TARGET, "w", ZIP_DEFLATED) as archive:
    archive.write(ROOT / "archipelago.json", f"{PACKAGE_ROOT}/archipelago.json")
    # An APWorld's single top-level directory is itself the importable world module.
    for path in sorted((ROOT / "arknights_is").rglob("*")):
        if path.is_file() and path.suffix in INCLUDED_SUFFIXES:
            relative = path.relative_to(ROOT / "arknights_is")
            archive.write(path, f"{PACKAGE_ROOT}/{relative.as_posix()}")
print(TARGET)
