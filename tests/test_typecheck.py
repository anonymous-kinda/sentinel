"""The type checker's configuration means what it says.

`make typecheck` runs mypy over sentinel/, and CI runs it on every Python in
the matrix. The core (bus, crdt, sync, triage) and the risk engine get every
check `mypy --strict` enables; the rest of sentinel/ gets mypy's standard
checks. A per-module `strict = true` switches strict mode on for every
module, so pyproject.toml sets the strict flags one by one. These tests read
back the options mypy itself derives from pyproject.toml, module by module:
a flag dropped from the list, or strictness leaking everywhere, fails here
instead of passing quietly.

Offline and fast: mypy parses its configuration; nothing is type-checked.
"""

from __future__ import annotations

import pathlib

import yaml
from mypy.main import process_options
from mypy.options import Options

ROOT = pathlib.Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
STRICT_PACKAGES = ("bus", "crdt", "sync", "triage", "risk")
NO_CONFIG = ""  # mypy reads no configuration file when given an empty path


def options(config: pathlib.Path | str, *flags: str) -> Options:
    _, parsed = process_options(["--config-file", str(config), *flags, "-c", "pass"])
    return parsed


def _values(opts: Options) -> dict[str, object]:
    names = (name for name in dir(opts) if not name.startswith("_"))
    return {name: getattr(opts, name) for name in names if not callable(getattr(opts, name))}


def strict_flags() -> dict[str, object]:
    """Every option `mypy --strict` changes, with the value it sets."""
    standard, strict = _values(options(NO_CONFIG)), _values(options(NO_CONFIG, "--strict"))
    return {name: value for name, value in strict.items() if standard[name] != value}


def module_names(packages: tuple[str, ...]) -> list[str]:
    paths = (path for package in packages for path in (ROOT / "sentinel" / package).rglob("*.py"))
    return sorted(".".join(path.relative_to(ROOT).with_suffix("").parts).removesuffix(".__init__") for path in paths)


def all_packages() -> tuple[str, ...]:
    return tuple(path.name for path in (ROOT / "sentinel").iterdir() if (path / "__init__.py").exists())


def loose(config: Options, module: str) -> list[str]:
    """The strict checks this module does not get."""
    effective = config.clone_for_module(module)
    missing = [name for name, value in strict_flags().items() if getattr(effective, name) != value]
    return sorted(missing + (["ignore_errors"] if effective.ignore_errors else []))


def test_strict_flags_are_read_from_mypy():
    assert {"disallow_untyped_defs", "warn_return_any", "disallow_any_generics"} <= set(strict_flags())


def test_the_core_and_the_risk_engine_get_every_strict_check():
    config = options(PYPROJECT)
    modules = module_names(STRICT_PACKAGES)
    assert "sentinel.sync.agent" in modules and "sentinel.risk" in modules
    assert {module: loose(config, module) for module in modules if loose(config, module)} == {}


def test_the_rest_of_sentinel_gets_the_standard_checks():
    config = options(PYPROJECT)
    rest = module_names(tuple(p for p in all_packages() if p not in STRICT_PACKAGES))
    assert "sentinel.api.app" in rest
    assert [module for module in rest if config.clone_for_module(module).disallow_untyped_defs] == []


def test_the_check_catches_a_dropped_flag(tmp_path):
    loosened = tmp_path / "pyproject.toml"
    loosened.write_text(PYPROJECT.read_text().replace("warn_return_any = true", "warn_return_any = false"))
    assert loose(options(loosened), "sentinel.risk.engine") == ["warn_return_any"]


def test_ci_runs_the_type_check():
    steps = yaml.safe_load(CI.read_text())["jobs"]["python"]["steps"]
    assert {"name": "Type check (mypy)", "run": "make typecheck"} in steps
