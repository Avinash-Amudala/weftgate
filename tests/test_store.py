"""The index store: atomic namespaced writes and incremental sync (git and not)."""

import os
import sqlite3
import time

import pytest

from tests.conftest import git, git_commit_all, git_init, have_git, write
from weftgate.store import Store, cache_path

needs_git = pytest.mark.skipif(not have_git(), reason="git not installed")


def test_cache_path_honours_weft_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("WEFTGATE_CACHE", str(tmp_path / "c"))
    p = cache_path(str(tmp_path / "repo"))
    assert p.startswith(str(tmp_path / "c")) and p.endswith(".sqlite")
    assert cache_path(str(tmp_path / "repo")) == p  # deterministic


def test_meta_and_bookkeeping(tmp_path):
    store = Store(str(tmp_path), path=str(tmp_path / "i.sqlite"))
    assert store.get_meta("schema_version") == "1"
    assert not store.is_built("o")
    store.mark_built("o", "abc", version="2")
    assert store.is_built("o") and store.oracle_commit("o") == "abc"
    assert store.oracle_version("o") == "2"
    store.mark_needs_rebuild("o")
    assert store.needs_rebuild("o")
    store.mark_unbuilt("o")
    assert not store.is_built("o")
    store.close()
    # Reopen: state persists.
    store = Store(str(tmp_path), path=str(tmp_path / "i.sqlite"))
    assert store.get_meta("repo_root") == os.path.abspath(str(tmp_path))
    store.close()


def test_namespace_rebuild_is_atomic(tmp_path):
    store = Store(str(tmp_path), path=str(tmp_path / "i.sqlite"))
    ns = store.namespace("demo")
    ns.rebuild("rows", "file TEXT, name TEXT", [("a.py", "x"), ("b.py", "y")], indexes=["file"])
    assert ns.count("rows") == 2 and ns.tables() == ["rows"]
    # A failing rebuild (rows of the wrong width) leaves the old table intact.
    with pytest.raises(sqlite3.DatabaseError):
        ns.rebuild("rows", "file TEXT, name TEXT", [("a.py", "x"), ("only-one",)])
    assert ns.count("rows") == 2
    assert ns.query("SELECT name FROM {t:rows} ORDER BY name") == [("x",), ("y",)]
    ns.replace_file("rows", "a.py", [("a.py", "z1"), ("a.py", "z2")])
    assert ns.query("SELECT name FROM {t:rows} WHERE file='a.py' ORDER BY name") == [
        ("z1",),
        ("z2",),
    ]
    ns.replace_file("rows", "b.py", [])
    assert ns.count("rows") == 2
    store.replace_set("demo", "s", {"b", "a"})
    assert store.get_set("demo", "s") == {"a", "b"}
    ns.drop_all()
    assert ns.tables() == [] and store.get_set("demo", "s") is None
    with pytest.raises(ValueError):
        ns.table("bad name")
    store.close()


def test_transaction_rolls_back(tmp_path):
    store = Store(str(tmp_path), path=str(tmp_path / "i.sqlite"))
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.set_meta("k", "v")
            with store.transaction():  # nested is fine
                store.set_meta("k2", "v2")
            raise RuntimeError("boom")
    assert store.get_meta("k") is None and store.get_meta("k2") is None
    store.close()


@needs_git
def test_sync_files_in_git_repo(tmp_path):
    root = str(tmp_path)
    git_init(root)
    write(root, "a.py", "x = 1\n")
    write(root, "pkg/b.py", "y = 2\n")
    write(root, "node_modules/junk.js", "ignored\n")
    write(root, ".gitignore", "node_modules/\n")
    c1 = git_commit_all(root)
    store = Store(root, path=str(tmp_path / "i.sqlite"))
    assert store.is_git_repo() and store.current_commit() == c1
    assert store.all_files() == [".gitignore", "a.py", "pkg/b.py"]
    assert store.sync_files(None) == [".gitignore", "a.py", "pkg/b.py"]

    # Clean tree at the recorded commit: a no-op sync is empty and fast.
    store.forget_sync_cache()
    t0 = time.perf_counter()
    assert store.sync_files(c1) == []
    assert time.perf_counter() - t0 < 1.0

    # Working-tree diff: modified, untracked, deleted, staged all show up.
    write(root, "a.py", "x = 2\n")
    write(root, "new.py", "z = 3\n")
    os.remove(os.path.join(root, "pkg/b.py"))
    write(root, "staged.py", "s = 1\n")
    git(root, "add", "staged.py")
    store.forget_sync_cache()
    assert store.sync_files(c1) == ["a.py", "new.py", "pkg/b.py", "staged.py"]

    # Committed changes since an older commit are included too.
    c2 = git_commit_all(root)
    store.forget_sync_cache()
    assert store.sync_files(c1) == ["a.py", "new.py", "pkg/b.py", "staged.py"]
    store.forget_sync_cache()
    assert store.sync_files(c2) == []
    # Unknown commit falls back to everything, never to an error.
    store.forget_sync_cache()
    assert store.sync_files("0" * 40) == store.all_files()
    store.finish_sync(c2)
    assert store.get_meta("build_commit") == c2
    store.close()


def test_sync_files_without_git(tmp_path):
    root = str(tmp_path / "repo")
    os.makedirs(root)
    write(root, "a.py", "x = 1\n")
    write(root, "sub/b.py", "y = 2\n")
    write(root, ".venv/lib/site.py", "ignored\n")
    store = Store(root, path=str(tmp_path / "i.sqlite"))
    assert not store.is_git_repo()
    assert store.all_files() == ["a.py", "sub/b.py"]
    assert store.sync_files(None) == ["a.py", "sub/b.py"]
    store.finish_sync(None)
    assert store.sync_files(None) == []  # fingerprints recorded: no-op now
    write(root, "a.py", "x = 12345\n")
    os.remove(os.path.join(root, "sub/b.py"))
    write(root, "c.py", "c = 1\n")
    store.forget_sync_cache()
    assert store.sync_files(None) == ["a.py", "c.py", "sub/b.py"]
    # Not finishing the sync keeps the change pending for the next run.
    store.forget_sync_cache()
    assert store.sync_files(None) == ["a.py", "c.py", "sub/b.py"]
    store.finish_sync(None)
    store.forget_sync_cache()
    assert store.sync_files(None) == []
    store.close()


def test_nested_failure_can_be_caught_without_committing_inner_writes(tmp_path):
    with Store(str(tmp_path), path=":memory:") as store:
        with store.transaction():
            store.set_meta("outer", "kept")
            with pytest.raises(RuntimeError), store.transaction():
                store.set_meta("inner", "must rollback")
                raise RuntimeError("inner failed")
        assert store.get_meta("outer") == "kept"
        assert store.get_meta("inner") is None


def test_namespace_names_do_not_match_sql_wildcards(tmp_path):
    with Store(str(tmp_path), path=":memory:") as store:
        store.namespace("a_b").rebuild("rows", "file TEXT", [("one",)])
        store.namespace("axb").rebuild("rows", "file TEXT", [("two",)])
        assert store.namespace("a_b").tables() == ["rows"]
        store.namespace("a_b").drop_all()
        assert store.namespace("axb").count("rows") == 1


@needs_git
def test_sync_detects_reverted_worktree_and_removed_untracked_file(tmp_path):
    root = str(tmp_path)
    git_init(root)
    write(root, "a.py", "x = 1\n")
    commit = git_commit_all(root)
    with Store(root, path=":memory:") as store:
        store.sync_files(None)
        store.finish_sync(commit)
        write(root, "a.py", "x = 2\n")
        write(root, "new.py", "y = 2\n")
        assert store.sync_files(commit) == ["a.py", "new.py"]
        store.finish_sync(commit)
        assert store.sync_files(commit) == []
        store.forget_sync_cache()
        git(root, "restore", "a.py")
        os.remove(tmp_path / "new.py")
        assert store.sync_files(commit) == ["a.py", "new.py"]
