from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DISALLOWED_ROOT_PATTERNS = [
    re.compile(r"^out_"),
    re.compile(r"^err"),
    re.compile(r"^pytest_"),
    re.compile(r"^stage_"),
    re.compile(r"^(query|queryex|start|stop)(\.|$)"),
]
DISALLOWED_ROOT_FILES = {
    "pytest_output.txt",
    "out_sample_activity.html",
    "out_sample_activity.pdf",
}


def test_repo_root_has_no_generated_artifacts():
    root_files = [path.name for path in ROOT.iterdir() if path.is_file()]
    bad_files = [name for name in root_files if name in DISALLOWED_ROOT_FILES or any(pat.match(name) for pat in DISALLOWED_ROOT_PATTERNS)]
    assert not bad_files, (
        "Generated or disposable artifact files should not live at the repository root. "
        f"Move these files into artifacts/ or another dedicated ignored directory: {bad_files}"
    )
