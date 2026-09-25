"""Boolean node settings accept a documented set of spellings, and nothing else.

`SENTINEL_READ_ONLY=enabled` used to read as false: the public node started
writable and said nothing. A value outside the set now stops the node at
start-up with an error that names the variable, whatever its default.
"""

import pytest

from sentinel.api import create_app
from sentinel.api.settings import Settings

FLAGS = {
    "SENTINEL_EXERCISE": "exercise",
    "SENTINEL_LIBRARY": "library",
    "SENTINEL_READ_ONLY": "read_only",
    "SENTINEL_DEMO_CONTROLS": "demo_controls",
    "SENTINEL_AI": "ai",
    "SENTINEL_AI_CLOUD": "ai_cloud",
}
TRUE = ["1", "true", "yes", "on", "TRUE", "Yes", " on "]
FALSE = ["0", "false", "no", "off", "FALSE", "No", " off "]
NOT_A_BOOLEAN = ["enabled", "disabled", "", "2", "y", "t", "readonly", "ture"]


@pytest.fixture
def clean_env(monkeypatch):
    for name in FLAGS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.mark.parametrize("name", FLAGS)
@pytest.mark.parametrize("value", TRUE)
def test_a_true_spelling_reads_as_true(clean_env, name, value):
    clean_env.setenv(name, value)
    assert getattr(Settings.from_env(), FLAGS[name]) is True


@pytest.mark.parametrize("name", FLAGS)
@pytest.mark.parametrize("value", FALSE)
def test_a_false_spelling_reads_as_false(clean_env, name, value):
    clean_env.setenv(name, value)
    assert getattr(Settings.from_env(), FLAGS[name]) is False


@pytest.mark.parametrize("name", FLAGS)
@pytest.mark.parametrize("value", NOT_A_BOOLEAN)
def test_any_other_value_is_refused_naming_the_variable(clean_env, name, value):
    clean_env.setenv(name, value)
    with pytest.raises(ValueError, match=f"^{name} must be one of .*, not {value!r}$"):
        Settings.from_env()


def test_an_unset_flag_takes_its_default(clean_env):
    settings = Settings.from_env()
    assert {field: getattr(settings, field) for field in FLAGS.values()} == {
        "exercise": True,
        "library": True,
        "read_only": False,
        "demo_controls": False,
        "ai": True,
        "ai_cloud": False,
    }


def test_read_only_enabled_stops_the_node_instead_of_starting_it_writable(clean_env):
    clean_env.setenv("SENTINEL_READ_ONLY", "enabled")
    with pytest.raises(ValueError, match="SENTINEL_READ_ONLY"):
        create_app()
