from app.snapshots import digest_tree, prepare_baseline


def test_readonly_snapshot_is_stable_and_shared(settings, project):
    info = prepare_baseline(settings, project, "t1", "readonly")
    first = digest_tree(__import__("pathlib").Path(info["snapshot_path"]))
    assert info["input_digest"] == first
    (project / "src" / "app.py").write_text("changed\n", encoding="utf-8")
    assert digest_tree(__import__("pathlib").Path(info["snapshot_path"])) == first
