"""Oracle discovery: entry points, built-in fallback, dotted paths, and errors."""

import pytest

from tests.conftest import write
from weft.config import Config
from weft.oracle import Oracle, OracleAPI, file_of_module, module_of_file
from weft.registry import available_oracles, load_oracles, resolve_registrar


def test_builtins_are_discoverable_by_name():
    names = available_oracles()
    assert {"env_vars", "imports_lockfile", "routes_fastapi"} <= set(names)
    oracles = load_oracles(Config(oracles=["routes_fastapi", "env_vars"]))
    assert list(oracles) == ["routes_fastapi", "env_vars"]  # config order is run order
    assert all(isinstance(o, Oracle) for o in oracles.values())


def test_builtin_fallback_without_entry_points(monkeypatch):
    monkeypatch.setattr("weft.registry.entry_point_registrars", lambda: {})
    oracles = load_oracles(Config(oracles=["env_vars"]))
    assert list(oracles) == ["env_vars"]


def test_dotted_path_plugin_is_discovered():
    for path in (
        "tests.plugins.dummy_oracle",
        "tests.plugins.dummy_oracle:register",
        "tests.plugins.dummy_oracle.register",
    ):
        oracles = load_oracles(Config(oracles=["env_vars", path]))
        assert list(oracles) == ["env_vars", "dummy"]
        assert oracles["dummy"].kinds == ("dummy_ref",)


def test_unknown_and_bad_entries_raise():
    with pytest.raises(ValueError, match="unknown oracle"):
        load_oracles(Config(oracles=["no_such_oracle"]))
    with pytest.raises(ModuleNotFoundError):
        load_oracles(Config(oracles=["no_such_pkg_xyz.mod:register"]))
    with pytest.raises(ValueError, match="has no"):
        load_oracles(Config(oracles=["tests.plugins.missing_module"]))
    with pytest.raises(ValueError, match="has no"):
        resolve_registrar("tests.plugins.dummy_oracle:nope")
    with pytest.raises(ValueError, match="duplicate"):
        load_oracles(Config(oracles=["tests.plugins.dummy_oracle:register_twice"]))
    with pytest.raises(TypeError, match="Oracle protocol"):
        load_oracles(Config(oracles=["tests.plugins.dummy_oracle:register_bad"]))


def test_oracle_api_rejects_duplicates_directly():
    from tests.plugins.dummy_oracle import DummyOracle

    api = OracleAPI()
    api.register_oracle(DummyOracle())
    with pytest.raises(ValueError):
        api.register_oracle(DummyOracle())
    assert list(api.oracles()) == ["dummy"]


def test_module_file_mapping(tmp_path):
    assert module_of_file("app/main.py") == "app.main"
    assert module_of_file("src/pkg/__init__.py") == "pkg"
    assert module_of_file("src/pkg/sub/mod.py") == "pkg.sub.mod"
    assert module_of_file("not-a-module.py") is None
    assert module_of_file("README.md") is None
    from weft.config import Config as _C
    from weft.oracle import Context
    from weft.store import Store

    root = str(tmp_path / "repo")
    write(root, "app/__init__.py", "")
    write(root, "app/main.py", "")
    write(root, "src/lib2/util.py", "")
    ctx = Context(root, Store(root, path=str(tmp_path / "i.sqlite")), _C())
    assert file_of_module(ctx, "app.main") == "app/main.py"
    assert file_of_module(ctx, "app") == "app/__init__.py"
    assert file_of_module(ctx, "lib2.util") == "src/lib2/util.py"
    assert file_of_module(ctx, "fastapi") is None
    ctx.store.close()
