import hashlib
import json
import os
from pathlib import Path

import pytest

from backend.qcc.auto_twin import materialization_builder
from backend.qcc.auto_twin import materialized_storage_dedupe as dedupe
from backend.qcc.auto_twin.materialized_storage_dedupe import (
    apply_plan,
    dedupe_staged_revision,
    list_revision_directories,
    plan_twin_root,
    replace_with_hardlink,
    sha256_file,
)

from scripts import qcc_auto_twin_storage_dedupe as cli

MIN = 1024
BIG = b"A" * 200_000
CSS = b"body{color:red}" * 500


def _rev(root, suffix, files, manifest=True):
    directory = root / ("matrev-" + suffix.ljust(24, "0"))
    directory.mkdir(parents=True)

    for relative, content in files.items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    if manifest:
        (directory / "manifest.json").write_text(
            json.dumps({
                "artifact_manifest": [
                    {
                        "path": relative,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "size_bytes": len(content),
                    }
                    for relative, content in files.items()
                ]
            }),
            encoding="utf-8",
        )

    return directory


def _snapshot(root):
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _inode(path):
    return (path.stat().st_dev, path.stat().st_ino)


def test_identical_files_become_hardlinks(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(BIG)
    b.write_bytes(BIG)

    digest = hashlib.sha256(BIG).hexdigest()

    assert replace_with_hardlink(a, b, digest) == "linked"
    assert os.path.samefile(a, b)
    assert a.stat().st_nlink == 2
    assert b.read_bytes() == BIG


def test_different_bytes_never_linked(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(BIG)
    b.write_bytes(b"B" * len(BIG))

    with pytest.raises(dedupe.StorageDedupeError):
        replace_with_hardlink(a, b, hashlib.sha256(BIG).hexdigest())

    assert not os.path.samefile(a, b)
    assert b.read_bytes() == b"B" * len(BIG)


def test_same_size_different_bytes_never_linked_by_planner(tmp_path):
    root = tmp_path / "mercurio"
    _rev(root, "a", {"x/f.bin": b"A" * 5000})
    _rev(root, "b", {"x/f.bin": b"B" * 5000})

    plan = plan_twin_root(root, min_bytes=MIN)

    assert plan["files_dedupable"] == 0
    assert apply_plan(plan)["linked"] == 0

    for revision in list_revision_directories(root):
        assert (revision / "x/f.bin").stat().st_nlink == 1


def test_duplicate_asset_in_same_revision_dedupes(tmp_path):
    root = tmp_path / "mercurio"
    revision = _rev(
        root,
        "a",
        {"states/01/a.css": CSS, "states/02/a.css": CSS},
    )

    plan = plan_twin_root(root, min_bytes=MIN)
    report = apply_plan(plan)

    assert report["ok"] and report["linked"] == 1
    assert os.path.samefile(
        revision / "states/01/a.css",
        revision / "states/02/a.css",
    )


def test_duplicate_across_revisions_dedupes_and_apply_preserves_hashes(
    tmp_path,
):
    root = tmp_path / "mercurio"
    _rev(root, "a", {"site.json": BIG, "s/own.txt": b"1" * 3000})
    _rev(root, "b", {"site.json": BIG, "s/own.txt": b"2" * 3000})

    before = _snapshot(root)
    plan = plan_twin_root(root, min_bytes=MIN)

    assert plan["files_dedupable"] == 1

    report = apply_plan(plan)

    assert report["ok"] and report["linked"] == 1
    assert _snapshot(root) == before

    first, second = list_revision_directories(root)

    assert _inode(first / "site.json") == _inode(second / "site.json")


def test_dry_run_changes_nothing(tmp_path, capsys):
    root = tmp_path / "mercurio"
    _rev(root, "a", {"site.json": BIG})
    _rev(root, "b", {"site.json": BIG})

    before = _snapshot(root)

    assert cli.main(["--root", str(root), "--min-bytes", str(MIN)]) == 0

    out = capsys.readouterr().out

    assert "MODE=DRY_RUN" in out
    assert "FILES_DEDUPABLE=1" in out
    assert _snapshot(root) == before

    for revision in list_revision_directories(root):
        assert (revision / "site.json").stat().st_nlink == 1


def test_second_apply_is_idempotent(tmp_path):
    root = tmp_path / "mercurio"
    _rev(root, "a", {"site.json": BIG, "c.css": CSS})
    _rev(root, "b", {"site.json": BIG, "c.css": CSS})
    _rev(root, "c", {"site.json": BIG, "c.css": CSS})

    assert cli.main(
        ["--root", str(root), "--min-bytes", str(MIN), "--apply"]
    ) == 0

    before = _snapshot(root)
    second = plan_twin_root(root, min_bytes=MIN)

    assert second["files_dedupable"] == 0
    assert second["expected_physical_savings"] == 0
    assert apply_plan(second)["linked"] == 0
    assert _snapshot(root) == before


def test_hardlink_failure_falls_back_for_new_materialization(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "mercurio"
    _rev(root, "a", {"site.json": BIG})

    staging = tmp_path / "staging"
    (staging / "states").mkdir(parents=True)
    (staging / "site.json").write_bytes(BIG)
    (staging / "states/copy.json").write_bytes(BIG)

    manifest = [
        {
            "path": path,
            "sha256": hashlib.sha256(BIG).hexdigest(),
            "size_bytes": len(BIG),
        }
        for path in ("site.json", "states/copy.json")
    ]

    def boom(*args, **kwargs):
        raise OSError("hardlinks unsupported")

    monkeypatch.setattr(os, "link", boom)

    stats = dedupe_staged_revision(
        staging,
        twin_root=root,
        artifact_manifest=manifest,
        min_bytes=MIN,
    )

    assert stats["linked"] == 0
    assert stats["failed"] >= 1
    assert (staging / "site.json").read_bytes() == BIG
    assert (staging / "states/copy.json").read_bytes() == BIG
    assert not list(staging.rglob(".dedupe-*"))


def test_builder_materialization_survives_hardlink_failure(
    tmp_path,
    monkeypatch,
):
    from scripts.tests import (
        test_qcc_auto_twin_materialized_carry_forward as carry,
    )

    calls = []
    real = materialization_builder.dedupe_staged_revision

    def aggressive(*args, **kwargs):
        calls.append(1)
        kwargs["min_bytes"] = 0
        return real(*args, **kwargs)

    monkeypatch.setattr(
        materialization_builder, "dedupe_staged_revision", aggressive
    )
    monkeypatch.setattr(
        os,
        "link",
        lambda *a, **k: (_ for _ in ()).throw(OSError("no links")),
    )

    carry.test_materialized_state_is_carried_forward_byte_for_byte(
        tmp_path
    )

    assert calls


def test_migration_failure_does_not_corrupt_destination(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "mercurio"
    a = _rev(root, "a", {"site.json": BIG})
    b = _rev(root, "b", {"site.json": BIG})

    plan = plan_twin_root(root, min_bytes=MIN)

    def boom(src, dst):
        raise PermissionError("locked")

    monkeypatch.setattr(os, "replace", boom)

    report = apply_plan(plan)

    assert not report["ok"] and report["linked"] == 0
    assert (a / "site.json").read_bytes() == BIG
    assert (b / "site.json").read_bytes() == BIG
    assert not list(root.rglob(".dedupe-*"))
    assert (b / "site.json").stat().st_nlink == 1


def test_link_hash_verification_failure_leaves_destination_intact(
    tmp_path,
    monkeypatch,
):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(BIG)
    b.write_bytes(BIG)
    digest = hashlib.sha256(BIG).hexdigest()

    calls = {"n": 0}
    real = dedupe.sha256_file

    def flaky(path):
        calls["n"] += 1
        # canonical, destination ok; temp link "differs"
        return "0" * 64 if calls["n"] == 3 else real(path)

    monkeypatch.setattr(dedupe, "sha256_file", flaky)

    with pytest.raises(dedupe.StorageDedupeError):
        replace_with_hardlink(a, b, digest)

    assert not os.path.samefile(a, b)
    assert b.read_bytes() == BIG
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "a.bin",
        "b.bin",
    ]


def test_unrelated_directories_are_ignored(tmp_path):
    root = tmp_path / "mercurio"
    _rev(root, "a", {"site.json": BIG})
    _rev(root, "b", {"site.json": BIG})

    for name in (".staging-abc", "matrev-short", "other", "matrev-XYZ"):
        _rev(root, "z", {"site.json": BIG}, manifest=True)
        (root / ("matrev-" + "z".ljust(24, "0"))).rename(root / name)

    (root / "stray.json").write_bytes(BIG)

    plan = plan_twin_root(root, min_bytes=MIN)

    assert plan["revision_count"] == 2
    assert plan["files_dedupable"] == 1
    apply_plan(plan)

    assert (root / "other/site.json").stat().st_nlink == 1
    assert (root / ".staging-abc/site.json").stat().st_nlink == 1


def test_revision_enumeration_only_valid_matrev(tmp_path):
    root = tmp_path / "mercurio"
    good = _rev(root, "a", {"f.bin": BIG})
    _rev(root, "b", {"f.bin": BIG}, manifest=False)
    (root / "matrev-nothex").mkdir()
    (root / "notes").mkdir()

    assert list_revision_directories(root) == [good]


def test_resolves_state_files_after_dedupe(tmp_path):
    root = tmp_path / "mercurio"
    files = {
        "runtime/index.html": b"<html>" + b"x" * 5000,
        "states/01-S/runtime/state.json": b'{"a":1}' + b" " * 5000,
        "states/01-S/evidence/page.mhtml": BIG,
        "states/01-S/source/site_architecture.json": CSS,
    }
    a = _rev(root, "a", files)
    b = _rev(root, "b", files)

    assert apply_plan(plan_twin_root(root, min_bytes=MIN))["ok"]

    for revision in (a, b):
        for relative, content in files.items():
            assert (revision / relative).read_bytes() == content

    assert (b / "states/01-S/evidence/page.mhtml").stat().st_nlink == 2
    assert json.loads(
        (b / "states/01-S/runtime/state.json").read_text()
    ) == {"a": 1}


def test_sandbox_future_revision_proof(tmp_path):
    root = tmp_path / "mercurio"
    first = _rev(root, "a", {"site.json": BIG, "css/a.css": CSS})

    staging = tmp_path / "stage"
    (staging / "css").mkdir(parents=True)
    (staging / "site.json").write_bytes(BIG)
    (staging / "css/a.css").write_bytes(CSS)
    (staging / "css/b.css").write_bytes(CSS)

    manifest = [
        {"path": p, "sha256": hashlib.sha256(c).hexdigest(),
         "size_bytes": len(c)}
        for p, c in (
            ("site.json", BIG), ("css/a.css", CSS), ("css/b.css", CSS)
        )
    ]

    stats = dedupe_staged_revision(
        staging, twin_root=root, artifact_manifest=manifest, min_bytes=MIN
    )

    assert stats["failed"] == 0 and stats["linked"] == 3

    second = root / ("matrev-" + "b".ljust(24, "0"))
    staging.rename(second)
    (second / "manifest.json").write_text("{}")

    assert second != first
    assert (second / "site.json").stat().st_nlink == 2
    assert (first / "css/a.css").stat().st_nlink == 3
    assert (second / "site.json").stat().st_size == len(BIG)

    expected = hashlib.sha256(BIG).hexdigest()

    import shutil

    shutil.rmtree(second)

    assert sha256_file(first / "site.json") == expected
    assert (first / "site.json").stat().st_nlink == 1
