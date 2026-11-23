"""Read the runner with sourced scientific modules at their execution positions."""
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
MODULES = ("annotation_prepare.sh", "annotation_funannotate.sh", "annotation_braker3.sh", "detection_antismash.sh", "detection_funbgcex.sh")


def annotation_source() -> str:
    text = (ROOT / "run_annotation_and_detection.sh").read_text(encoding="utf-8")
    for name in (*MODULES, "detection_plantismash.sh"):
        text = text.replace(f'source "${{SCRIPT_DIR}}/{name}"\n\n', (ROOT / name).read_text(encoding="utf-8") + "\n")
    return text


def shell_function(source: str, name: str) -> str:
    marker = name + "() {"
    return marker + source.split(marker, 1)[1].split("\n}", 1)[0] + "\n}\n"


def runner_source_command() -> str:
    return f'<({shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).resolve()))})'


if __name__ == "__main__":
    print(annotation_source(), end="")
