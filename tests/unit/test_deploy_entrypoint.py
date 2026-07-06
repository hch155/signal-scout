"""Deployment entrypoint must load app.py under the same module name the
code imports from.

Request handlers do lazy `from app import ...` (validate_csrf,
_resolve_address_coverage, _coords_in_bounds). Under gunicorn the app was
launched as `src.app:app`, so `sys.modules` held it as `src.app` while the
lazy imports pulled a *second* copy under the bare name `app` — re-running
app.py top-level, re-registering blueprints, and raising AssertionError
("setup method 'add_url_rule' can no longer be called ... already
registered"). The tests never caught it because conftest imports app bare
(`import app as app_module`), so the duplicate never forms in-process.

Guard: the gunicorn target in the Dockerfile must be the bare `app:app`,
matching both the lazy imports and the test harness.
"""
from __future__ import annotations

import pathlib
import re

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_gunicorn_target_is_bare_app_module():
    dockerfile = (_REPO_ROOT / "Dockerfile").read_text()
    targets = re.findall(r'"([\w.]+):app"', dockerfile)
    assert targets, "no gunicorn <module>:app target found in Dockerfile"
    for target in targets:
        assert target == "app", (
            f"gunicorn target {target!r}:app loads app.py under a non-bare module "
            "name; lazy `from app import ...` in request handlers would import "
            "a second copy and re-register blueprints. Use 'app:app'."
        )
