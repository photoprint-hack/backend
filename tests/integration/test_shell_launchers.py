import os
import subprocess

import pytest


@pytest.mark.parametrize(
    "name", ["seed", "import_data", "export_openapi", "start_server", "test_postgres", "worker", "check_ai"]
)
def test_launcher_works_from_other_directory_and_preserves_arguments(tmp_path, name, project_root):
    root = project_root
    fake = tmp_path / "uv"
    fake.write_text(
        '#!/bin/bash\nprintf \'%s\\0\' "$PWD" "$@" > "$WRAPPER_TRACE"\nexit "${WRAPPER_EXIT:-0}"\n'
    )
    fake.chmod(0o755)
    trace = tmp_path / "trace"
    args = ["argument with spaces", "literal;$(not-a-command)", "--flag"]
    env = {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "WRAPPER_TRACE": str(trace),
        "WRAPPER_EXIT": "7",
    }
    result = subprocess.run(
        [str(root / "sh" / (name + ".sh")), *args], cwd=tmp_path, env=env, capture_output=True
    )
    assert result.returncode == 7
    actual = trace.read_bytes().decode().split("\0")[:-1]
    prefix = (
        ["run", "--python", "3.12", "--no-project", "--with", "pgserver", "python"]
        if name == "test_postgres"
        else ["run", "python"]
    )
    assert actual == [str(root), *prefix, f"scripts/{name}.py", *args]
