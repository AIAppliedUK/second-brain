from pathlib import Path

from second_brain_core.config import _candidate_env_files


def test_candidate_env_files_include_working_directory(monkeypatch, tmp_path: Path):
    workspace = tmp_path / "workspace"
    nested = workspace / "nested" / "repo"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    candidates = _candidate_env_files()

    assert candidates[0] == nested / ".env"
    assert workspace / ".env" in candidates
