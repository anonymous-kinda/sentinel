"""The sentinel role's tasks run in an order that works on a fresh host.

The play has never run against a host, so its order is checked here, from
the task list. The template module does not create parent directories: a
file templated into the install prefix before anything creates the prefix
fails on a fresh host, where install.sh has not run yet.
"""

import pathlib

import yaml

TASKS = pathlib.Path(__file__).resolve().parent.parent / "deploy" / "ansible" / "roles" / "sentinel" / "tasks" / "main.yml"
PREFIX = "{{ sentinel_prefix }}"
WRITES_FILES = ("ansible.builtin.template", "ansible.builtin.copy")


def tasks() -> list[dict]:
    return yaml.safe_load(TASKS.read_text())


def destination(task: dict) -> str | None:
    """Where a template or copy task writes, if it is one."""
    module = next((task[name] for name in WRITES_FILES if name in task), None)
    return module["dest"] if module else None


def creates_prefix(task: dict) -> bool:
    module = task.get("ansible.builtin.file") or {}
    return module.get("path") == PREFIX and module.get("state") == "directory"


def test_the_prefix_is_created_before_anything_is_written_into_it():
    ordered = tasks()
    writers = [i for i, task in enumerate(ordered) if (destination(task) or "").startswith(f"{PREFIX}/")]
    assert writers, "the role writes node settings into the prefix"
    first_writer = ordered[writers[0]]["name"]
    assert any(creates_prefix(task) for task in ordered[: writers[0]]), f"{first_writer!r} runs before the prefix exists"


def test_the_prefix_gets_the_owner_and_mode_install_sh_gives_it():
    """install.sh runs as root and makes the prefix with `mkdir -p` (root, 0755
    under the default umask); the service user owns only <prefix>/var."""
    (task,) = [task for task in tasks() if creates_prefix(task)]
    module = task["ansible.builtin.file"]
    assert (module.get("owner"), module.get("group"), module.get("mode")) == ("root", "root", "0755")
