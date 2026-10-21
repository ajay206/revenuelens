import os
import shutil
import subprocess
from pathlib import Path

import pytest

# Skip whole module if required binaries are missing
missing = [cmd for cmd in ("bash", "openssl") if shutil.which(cmd) is None]
pytestmark = pytest.mark.skipif(missing, reason="bash or openssl not available")


def run_script(tmp_path: Path, slug: str, name: str | None = None) -> subprocess.CompletedProcess:
    """Execute new-company.sh with SKIP_UP=1 in an isolated copy of the repo."""
    src_scripts = Path(__file__).resolve().parents[1] / "scripts"
    dst_scripts = tmp_path / "scripts"
    shutil.copytree(src_scripts, dst_scripts, dirs_exist_ok=True)

    env = os.environ.copy()
    env["SKIP_UP"] = "1"

    cmd = ["bash", str(dst_scripts / "new-company.sh"), slug]
    if name:
        cmd.append(name)

    result = subprocess.run(
        cmd,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result


def test_valid_deployments(tmp_path: Path):
    slugs = ["acme-inc", "beta-co"]
    for slug in slugs:
        proc = run_script(tmp_path, slug)
        assert proc.returncode == 0, f"Script failed for {slug}: {proc.stderr}"

        env_path = tmp_path / "deployments" / slug / ".env"
        assert env_path.is_file()

        mode = env_path.stat().st_mode & 0o777
        assert mode == 0o600

        content = env_path.read_text()
        env_vars = dict(line.split("=", 1) for line in content.splitlines() if "=" in line)

        assert env_vars["COMPOSE_PROJECT_NAME"] == f"rl-{slug}"
        for key in ("DB_PASSWORD", "JWT_SECRET", "COMPANY_ID", "API_PORT"):
            assert env_vars.get(key)

    env1 = (tmp_path / "deployments" / slugs[0] / ".env").read_text()
    env2 = (tmp_path / "deployments" / slugs[1] / ".env").read_text()
    assert env1 != env2
    vars1 = dict(line.split("=", 1) for line in env1.splitlines() if "=" in line)
    vars2 = dict(line.split("=", 1) for line in env2.splitlines() if "=" in line)

    for secret in ("DB_PASSWORD", "JWT_SECRET", "COMPANY_ID", "API_PORT"):
        assert vars1[secret] != vars2[secret]


def test_invalid_slug(tmp_path: Path):
    proc = run_script(tmp_path, "Bad_Slug")
    assert proc.returncode != 0
    assert "slug must match" in proc.stderr.lower()
