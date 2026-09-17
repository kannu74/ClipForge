import os
import subprocess
import tempfile
from pathlib import Path

import pytest

# Point CLIPFORGE_DATA_DIR at a temp dir before app.config is imported anywhere,
# so tests never touch real project data.
_tmp = tempfile.mkdtemp(prefix="clipforge_test_")
os.environ["CLIPFORGE_DATA_DIR"] = _tmp

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def sample_video() -> Path:
    """A real, ffmpeg-generated MP4 (5s, 640x360, 30fps, H.264 + AAC tone).
    Used to exercise ffprobe/upload/audio-extraction against an actual
    decodable video file rather than a mocked one."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="clipforge_fixture_"))
    out_path = tmp_dir / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=5",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            str(out_path),
        ],
        capture_output=True,
        check=True,
        timeout=60,
    )
    return out_path

@pytest.fixture(scope="session")
def synthetic_energy_audio() -> Path:
    """6s mono WAV: 2s quiet tone, 2s loud tone, 2s quiet tone. Used to
    verify compute_energy_profile actually distinguishes loud vs quiet
    sections on real decoded audio, not mocked data."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="clipforge_energy_fixture_"))

    def make_tone(path: Path, volume: float):
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "sine=frequency=220:duration=2:sample_rate=16000",
                "-filter:a", f"volume={volume}",
                "-ac", "1",
                str(path),
            ],
            capture_output=True, check=True, timeout=30,
        )

    quiet1, loud, quiet2 = tmp_dir / "q1.wav", tmp_dir / "loud.wav", tmp_dir / "q2.wav"
    make_tone(quiet1, 0.02)
    make_tone(loud, 1.0)
    make_tone(quiet2, 0.02)

    list_file = tmp_dir / "list.txt"
    list_file.write_text(f"file '{quiet1}'\nfile '{loud}'\nfile '{quiet2}'\n")

    out_path = tmp_dir / "energy_test.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(out_path)],
        capture_output=True, check=True, timeout=30,
    )
    return out_path
