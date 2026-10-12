import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from precedent.console.guide import (
    CONTENT,
    chapter_key,
    evidence_runs,
    load_evidence,
    load_guide,
    mp3_seconds,
    performance_matches,
    tour_version,
)
from precedent.console.server import STATIC, create_app
from precedent.worker.events import EventLog


def test_guide_is_read_only_and_works_without_company_or_retained_run(tmp_path):
    launched = []
    app = create_app(tmp_path, launcher=lambda *a, **kw: launched.append(a))
    with TestClient(app) as client:
        response = client.get("/guide")
        assert response.status_code == 200
        assert 'href="/#request"' in response.text
        assert "not installed here" in response.text  # cited runs are absent: no dead links
        assert 'href="/runs/' not in response.text
        assert "Read Ava’s narration" in response.text and "Read the scene" in response.text
        assert not launched and not list(tmp_path.iterdir())


def test_active_task_returns_to_existing_run_without_launching(tmp_path):
    app = create_app(tmp_path)
    app.state.manager.processes["existing"] = SimpleNamespace(poll=lambda: None)
    # Avoid invoking shutdown for this deliberately fake process.
    client = TestClient(app)
    response = client.get("/guide")
    assert 'href="/runs/existing"' in response.text
    assert "Return to Ava’s task" in response.text
    assert 'href="/#request"' not in response.text


def test_evidence_uses_retained_company_not_current_demo(tmp_path):
    run = load_evidence()["hero"]["run_id"]
    log = EventLog(run, root=tmp_path)
    log.emit("run_started", request="Invoice", seed=7, worker="precedent", model="scripted")
    log.emit("observation", url="http://original:8115/books/bills/INV-921")
    log.emit("run_finished", outcome="unknown")
    (log.dir / "launch.json").write_text(json.dumps({"apps_url": "http://original:8115"}))
    client = TestClient(create_app(tmp_path, apps_url="http://fresh:8118"))
    page = client.get("/guide").text
    assert 'href="http://original:8115/books/bills/INV-921"' in page
    assert 'href="http://fresh:8118/books/bills/INV-921"' not in page
    assert f'href="/runs/{run}"' in page  # an installed cited run is linked


def _install(tmp_path, guide, voice=None, skip=None, loki=None):
    voice = voice or guide["narration_voice"]
    loki = loki or guide.get("loki_voice")
    version = tour_version(guide)
    folder = tmp_path / "audio/guide" / version
    folder.mkdir(parents=True, exist_ok=True)
    chapters = {}
    for chapter in guide["chapters"]:
        (folder / f"{chapter['id']}.mp3").write_bytes(b"fixture")
        if chapter["id"] != skip:
            chapters[chapter["id"]] = {
                "file": f"{version}/{chapter['id']}.mp3",
                "key": chapter_key(chapter, voice, loki),
                "seconds": 10,
            }
            if "dialogue" in chapter:
                chapters[chapter["id"]]["cues"] = [i * 2.0 for i in range(len(chapter["dialogue"]))]
    manifest = {"version": version, "voice": voice, "chapters": chapters}
    (tmp_path / "audio/guide/manifest.json").write_text(json.dumps(manifest))
    return manifest


def test_versioned_narration_is_all_or_nothing_and_never_stale(tmp_path):
    guide = json.loads(CONTENT.read_text())
    _install(tmp_path, guide)
    loaded = load_guide(tmp_path)
    assert loaded["audio_ready"] and all(c["audio"] for c in loaded["chapters"])
    assert loaded["audio_seconds"] == 10 * len(guide["chapters"])
    assert "performance" not in loaded["chapters"][0]  # delivery markup never reaches the page
    # Any delivery setting change invalidates every clip: voice, model and style prompt.
    for change in ({"voice": "Other"}, {"model": "other-tts"}, {"style": "Shout."}):
        _install(tmp_path, guide, voice={**guide["narration_voice"], **change})
        assert load_guide(tmp_path)["audio_ready"] is False
    # One missing chapter means no narration at all, not a half-updated tour.
    _install(tmp_path, guide, skip=guide["chapters"][2]["id"])
    loaded = load_guide(tmp_path)
    assert loaded["audio_ready"] is False and not any(c["audio"] for c in loaded["chapters"])
    (tmp_path / "audio/guide/manifest.json").write_text("invalid")
    assert load_guide(tmp_path)["audio_ready"] is False


def test_performance_may_add_pauses_but_not_words():
    chapter = {
        "narration": "Hi, I’m Ava. Welcome.",
        "performance": "Hi, I’m Ava. [short pause] Welcome!",
    }
    assert performance_matches(chapter)
    assert not performance_matches({**chapter, "performance": "Hi, I’m Ava. Welcome, friend."})
    guide = json.loads(CONTENT.read_text())
    assert all(performance_matches(c) for c in guide["chapters"])


def test_manifest_paths_and_audio_bytes_are_validated(tmp_path):
    guide = json.loads(CONTENT.read_text())
    manifest = _install(tmp_path, guide)
    first = guide["chapters"][0]["id"]
    manifest["chapters"][first]["file"] = "../../../console/guide.json"
    (tmp_path / "audio/guide/manifest.json").write_text(json.dumps(manifest))
    assert load_guide(tmp_path)["audio_ready"] is False
    assert mp3_seconds(b"not audio" * 100) == 0
    real = sorted((STATIC / "audio/guide").glob("v-*/hello.mp3"))
    assert real and mp3_seconds(real[-1].read_bytes()) > 5


def test_dialogue_is_voiced_per_line_and_cued(tmp_path):
    guide = json.loads(CONTENT.read_text())
    scene = next(c for c in guide["chapters"] if "dialogue" in c)
    assert {line["speaker"] for line in scene["dialogue"]} == {"ava", "loki"}
    assert performance_matches(scene)
    _install(tmp_path, guide)
    loaded = next(c for c in load_guide(tmp_path)["chapters"] if c["id"] == scene["id"])
    assert loaded["cues"] == [i * 2.0 for i in range(len(scene["dialogue"]))]
    assert loaded["narration"].startswith("Ava: ") and "Loki: " in loaded["narration"]
    assert all("performance" not in line for line in loaded["dialogue"])
    # Loki's voice is part of the key: changing it invalidates the whole tour.
    _install(tmp_path, guide, loki={**guide["loki_voice"], "voice": "Other"})
    assert load_guide(tmp_path)["audio_ready"] is False
    # A dialogue line may gain pauses but never different words.
    changed = {**scene, "dialogue": [{**scene["dialogue"][0], "performance": "Done, darling."}]}
    assert not performance_matches(changed)


def test_evidence_snapshot_cites_runs_and_only_installed_runs_are_linked(tmp_path):
    evidence = load_evidence()
    runs = evidence_runs(evidence)
    assert evidence["hero"]["run_id"] in runs and evidence["ghost"]["run_id"] in runs
    assert evidence["ghost"]["approver"] != evidence["ghost"]["ava_approver"]
    assert evidence["hero"]["grader"]["passed"] == evidence["hero"]["grader"]["total"]
    assert load_evidence(tmp_path / "missing.json") == {}
    for frame in evidence["hero"]["frames"]:
        assert (STATIC / frame["src"].removeprefix("/static/")).is_file()
