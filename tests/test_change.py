"""Change parsing: files, text, unified diffs of every common shape, git."""

import os

import pytest

from tests.conftest import git, git_commit_all, git_init, have_git, write
from weft.change import Change

DIFF = """\
diff --git a/app/main.py b/app/main.py
index 1111111..2222222 100644
--- a/app/main.py
+++ b/app/main.py
@@ -1,3 +1,4 @@
 import os
-x = 1
+x = 2
+y = os.getenv('NEW')
 z = 3
@@ -10,2 +11,3 @@ def f():
     pass
+    return 1
 
diff --git a/deleted.py b/deleted.py
deleted file mode 100644
--- a/deleted.py
+++ /dev/null
@@ -1,2 +0,0 @@
-gone = 1
-gone2 = 2
diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+created = True
+more = 1
\\ No newline at end of file
diff --git a/img.png b/img.png
Binary files a/img.png and b/img.png differ
diff --git a/old name.py b/renamed name.py
similarity index 90%
rename from old name.py
rename to renamed name.py
--- "a/old name.py"
+++ "b/renamed name.py"
@@ -1 +1 @@
-a
+b
"""


def test_unified_diff_all_shapes():
    ch = Change.from_unified_diff(DIFF)
    by_file = {r.file: r.lines() for r in ch.regions}
    assert by_file["app/main.py"] == [
        (2, "x = 2"),
        (3, "y = os.getenv('NEW')"),
        (12, "    return 1"),
    ]
    assert "deleted.py" not in by_file
    assert by_file["new.py"] == [(1, "created = True"), (2, "more = 1")]
    assert "img.png" not in by_file
    assert by_file["renamed name.py"] == [(1, "b")]
    assert ch.files() == ["app/main.py", "new.py", "renamed name.py"]
    assert not ch.is_empty() and Change.from_unified_diff("").is_empty()
    assert Change.from_unified_diff(DIFF).regions[0].lines() == ch.regions[0].lines()


def test_no_prefix_and_plain_diffs():
    text = "--- main.py\t2024-01-01\n+++ main.py\t2024-01-02\n@@ -1 +1,2 @@\n a\n+b\n"
    ch = Change.from_unified_diff(text)
    assert ch.regions[0].file == "main.py" and ch.regions[0].lines() == [(2, "b")]
    # A hunk without ---/+++ headers still attaches to the diff --git path.
    text = "diff --git a/x.py b/x.py\n@@ -0,0 +1 @@\n+q = 1\n"
    ch = Change.from_unified_diff(text)
    assert ch.regions[0].file == "x.py" and ch.regions[0].lines() == [(1, "q = 1")]
    # A '+++' inside a hunk is content, not a header.
    text = "--- a/t.py\n+++ b/t.py\n@@ -0,0 +1,2 @@\n+++x\n+y\n"
    ch = Change.from_unified_diff(text)
    assert ch.regions[0].lines() == [(1, "++x"), (2, "y")]


def test_from_file_and_text_carry_full_text(tmp_path):
    root = str(tmp_path)
    p = write(root, "pkg/m.py", "a = 1\nb = 2\n")
    ch = Change.from_file(p, repo_root=root)
    assert ch.regions[0].file == "pkg/m.py"
    assert ch.regions[0].whole_file and ch.regions[0].text() == "a = 1\nb = 2\n"
    assert ch.regions[0].lines() == [(1, "a = 1"), (2, "b = 2")]
    ch2 = Change.from_text("pkg/other.py", "x\n")
    assert ch2.regions[0].full_text == "x\n" and ch2.regions[0].lines() == [(1, "x")]
    rel = Change.from_file(p).relative_to(root)
    assert rel.regions[0].file == "pkg/m.py"
    outside = Change.from_text(os.path.join(os.path.dirname(root), "elsewhere.py"), "z")
    assert outside.relative_to(root).regions[0].file.endswith("elsewhere.py")


def test_from_path_or_diff(tmp_path):
    root = str(tmp_path)
    p = write(root, "a.py", "v = 1\n")
    assert Change.from_path_or_diff(p, None, root).regions[0].file == "a.py"
    assert Change.from_path_or_diff("-", "--- a/q.py\n+++ b/q.py\n@@ -0,0 +1 @@\n+k\n").files() == [
        "q.py"
    ]
    inline = Change.from_path_or_diff("--- a/i.py\n+++ b/i.py\n@@ -0,0 +1 @@\n+k\n")
    assert inline.files() == ["i.py"]
    write(root, "d/one.py", "1\n")
    write(root, "d/two.txt", "2\n")
    with open(os.path.join(root, "d", "bin.dat"), "wb") as fh:
        fh.write(b"\0\1\2")
    d = Change.from_path_or_diff(os.path.join(root, "d"), None, root)
    assert d.files() == ["d/one.py", "d/two.txt"]


@pytest.mark.skipif(not have_git(), reason="git not installed")
def test_from_git(tmp_path):
    root = str(tmp_path)
    git_init(root)
    write(root, "a.py", "x = 1\n")
    git_commit_all(root)
    write(root, "a.py", "x = 1\ny = 2\n")
    write(root, "u.py", "untracked = 1\n")
    ch = Change.from_git(root)
    assert {r.file: r.lines() for r in ch.regions} == {
        "a.py": [(2, "y = 2")],
        "u.py": [(1, "untracked = 1")],
    }
    git(root, "add", "a.py")
    staged = Change.from_git(root, staged=True)
    assert staged.files() == ["a.py"]
    c2 = git_commit_all(root)
    ranged = Change.from_git(root, rev_range=f"{c2}~1..{c2}")
    assert ranged.files() == ["a.py", "u.py"]
