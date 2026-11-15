import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "tools" / "stitch_talk.sh"

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg and ffprobe"
)


def clip(path: Path, seconds: float, size: str = "640x360", rate: int = 30,
         volume: float = 0.3, audio: bool = True) -> Path:
    """A test-pattern clip with a sine tone at the given volume."""
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
           "-i", f"testsrc2=size={size}:rate={rate}:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                "-af", f"volume={volume}", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def loudness(path: Path, start: float, seconds: float) -> float:
    """Integrated loudness (LUFS) of one stretch of the file."""
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-ss", str(start), "-t", str(seconds),
         "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True, check=True)
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", out.stderr)[-1])


def stitch(folder: Path, out: Path, max_seconds: int | None = None):
    env = dict(os.environ)
    if max_seconds is not None:
        env["STITCH_MAX_SECONDS"] = str(max_seconds)
    return subprocess.run(["bash", str(SCRIPT), str(folder), str(out)],
                          capture_output=True, text=True, env=env)


def test_joins_parts_in_slide_order_at_one_size_and_loudness(tmp_path):
    parts = tmp_path / "recordings"
    parts.mkdir()
    clip(parts / "04_agent_b.mp4", 3, size="1280x720", rate=25, volume=0.9)
    clip(parts / "01_agent_a.mp4", 3, size="640x480", volume=0.02)
    clip(parts / "06_agent_c.mp4", 2)
    out = tmp_path / "talk_final.mp4"

    result = stitch(parts, out)

    assert result.returncode == 0, result.stderr
    order = [line.split()[0] for line in result.stdout.splitlines() if line.endswith(" s")]
    assert order == ["01_agent_a.mp4", "04_agent_b.mp4", "06_agent_c.mp4"]
    info = probe(out)
    assert abs(float(info["format"]["duration"]) - 8.0) < 0.3
    video = [s for s in info["streams"] if s["codec_type"] == "video"]
    assert (video[0]["width"], video[0]["height"]) == (1920, 1080)
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    quiet, loud = loudness(out, 0.5, 2.0), loudness(out, 3.5, 2.0)
    assert abs(quiet - loud) < 4  # the inputs differ by about 33 LU


def test_refuses_a_talk_over_the_limit(tmp_path):
    parts = tmp_path / "recordings"
    parts.mkdir()
    clip(parts / "01_agent_a.mp4", 2)
    clip(parts / "04_agent_b.mp4", 2)
    out = tmp_path / "talk_final.mp4"

    result = stitch(parts, out, max_seconds=3)

    assert result.returncode != 0
    assert "over the 0:03 limit" in result.stderr
    assert not out.exists()


def test_refuses_a_folder_without_parts(tmp_path):
    (tmp_path / "notes.mp4").write_text("x")
    result = stitch(tmp_path, tmp_path / "talk_final.mp4")
    assert result.returncode != 0
    assert "no NN_name.mp4 parts" in result.stderr


def test_refuses_a_part_without_sound(tmp_path):
    clip(tmp_path / "01_agent_a.mp4", 1)
    clip(tmp_path / "04_agent_b.mp4", 1, audio=False)
    result = stitch(tmp_path, tmp_path / "talk_final.mp4")
    assert result.returncode != 0
    assert "04_agent_b.mp4 has no sound" in result.stderr


def test_refuses_two_parts_for_one_slide(tmp_path):
    clip(tmp_path / "04_agent_b.mp4", 1)
    clip(tmp_path / "04_agent_c.mp4", 1)
    result = stitch(tmp_path, tmp_path / "talk_final.mp4")
    assert result.returncode != 0
    assert "two parts start at slide 04" in result.stderr


def test_writes_into_the_recordings_folder_by_default(tmp_path):
    clip(tmp_path / "01_agent_a.mp4", 1)
    result = subprocess.run(["bash", str(SCRIPT), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "talk_final.mp4").exists()
    assert not list(tmp_path.glob("*.partial.mp4"))
