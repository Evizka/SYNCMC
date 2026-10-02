"""Publication checks use tiny synthetic ZIPs; no network or native build required."""
import hashlib
import json
import subprocess
import zipfile

import pytest

from scripts import publish_release as release

SOURCE = b'APP_VERSION = "0.2.0"\nDEFAULT_THEME = "aurora"\n'
SHA = "a" * 40
REPOSITORY = "Evizka/SYNCMC"
RUN = {
    "status": "completed", "conclusion": "success", "event": "push",
    "head_repository": {"full_name": REPOSITORY}, "head_sha": SHA,
    "path": ".github/workflows/build.yml", "html_url": "https://github.com/example/run/123",
}


def make_archives(directory, *, source=SOURCE, extra=None, executable=b"MZ test"):
    for name, prefix in release.ARCHIVES.items():
        path = directory / name
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr(prefix + "source/mcsync.py", source)
            if name.startswith("MCSync-windows"):
                bundle.writestr("MCSync/MCSync.exe", executable)
            if extra:
                bundle.writestr(prefix + extra, b"private")
        path.with_suffix(".zip.sha256").write_text(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}\n"
        )


def test_paginated_api_supports_adjacent_json_documents(monkeypatch):
    monkeypatch.setattr(release, "gh", lambda *args: '[{"id":1}]\n  [{"id":2}]\n')
    assert release.api_pages("example") == [[{"id": 1}], [{"id": 2}]]


def test_constants_are_read_without_executing_source():
    source = SOURCE.decode() + '\nraise RuntimeError("must never execute")\n'
    assert release.constants(source) == {"APP_VERSION": "0.2.0", "DEFAULT_THEME": "aurora"}


def test_trusted_successful_run():
    assert release.validate_run(RUN, REPOSITORY) == SHA


@pytest.mark.parametrize("changes", [
    {"status": "in_progress"}, {"conclusion": "failure"}, {"event": "pull_request"},
    {"head_repository": {"full_name": "attacker/fork"}}, {"head_repository": None},
    {"path": ".github/workflows/other.yml"}, {"head_sha": "main"},
])
def test_untrusted_or_incomplete_run_is_rejected(changes):
    with pytest.raises(ValueError):
        release.validate_run(RUN | changes, REPOSITORY)


def build_results():
    jobs = [{"name": name, "conclusion": "success"} for name in release.REQUIRED_JOBS]
    artifacts = [{"name": name, "expired": False} for name in release.ARTIFACT_NAMES]
    return jobs, artifacts


def test_all_platforms_and_live_installation_are_required():
    jobs, artifacts = build_results()
    release.validate_build_results(jobs, artifacts)
    jobs[0]["conclusion"] = "skipped"
    with pytest.raises(ValueError):
        release.validate_build_results(jobs, artifacts)


def test_missing_or_expired_artifacts_are_rejected():
    jobs, artifacts = build_results()
    with pytest.raises(ValueError):
        release.validate_build_results(jobs, artifacts[:-1])
    artifacts[0]["expired"] = True
    with pytest.raises(ValueError):
        release.validate_build_results(jobs, artifacts)


def test_inspection_records_verified_build_sha_and_version(monkeypatch, tmp_path):
    jobs, artifacts = build_results()

    def gh(*args):
        endpoint = args[1]
        if endpoint.endswith("/jobs"):
            return json.dumps({"jobs": jobs})
        if endpoint.endswith("/artifacts"):
            return json.dumps({"artifacts": artifacts})
        return json.dumps(RUN)

    monkeypatch.setattr(release, "gh", gh)
    monkeypatch.setattr(release.subprocess, "check_output", lambda command: SOURCE)
    output = tmp_path / "metadata.json"
    info = release.inspect_run("123", REPOSITORY, output)
    assert json.loads(output.read_text()) == info
    assert info["sha"] == SHA and info["tag"] == "v0.2.0"
    assert info["run_id"] == "123" and info["build_url"] == RUN["html_url"]


@pytest.mark.parametrize("run_id", ["main", "../123", "123; echo unsafe"])
def test_invalid_run_id_never_reaches_github(run_id, monkeypatch, tmp_path):
    def unexpected(*args):
        raise AssertionError("must not contact GitHub")

    monkeypatch.setattr(release, "gh", unexpected)
    with pytest.raises(ValueError, match="numeric"):
        release.inspect_run(run_id, REPOSITORY, tmp_path / "metadata.json")


def test_native_archives_and_checksums(tmp_path):
    make_archives(tmp_path)
    assets = release.validate_archives(tmp_path, SOURCE)
    assert len(assets) == 6 and all(path.is_file() for path in assets)


def test_windows_checkout_line_endings_do_not_change_source_provenance(tmp_path):
    make_archives(tmp_path, source=SOURCE.replace(b"\n", b"\r\n"))
    assert len(release.validate_archives(tmp_path, SOURCE)) == 6


def test_bad_checksum_is_rejected(tmp_path):
    make_archives(tmp_path)
    (tmp_path / "MCSync-windows-x64.zip.sha256").write_text("0" * 64 + "  MCSync-windows-x64.zip\n")
    with pytest.raises(ValueError, match="checksum"):
        release.validate_archives(tmp_path, SOURCE)


def test_source_must_match_the_actual_build_commit(tmp_path):
    make_archives(tmp_path, source=SOURCE + b"# changed\n")
    with pytest.raises(ValueError, match="source differs"):
        release.validate_archives(tmp_path, SOURCE)


@pytest.mark.parametrize("private_name", sorted(release.PRIVATE_FILES))
def test_private_launcher_data_is_never_published(private_name, tmp_path):
    make_archives(tmp_path, extra="data/" + private_name)
    with pytest.raises(ValueError, match="private"):
        release.validate_archives(tmp_path, SOURCE)


def test_windows_archive_requires_a_real_executable_header(tmp_path):
    make_archives(tmp_path, executable=b"not an exe")
    with pytest.raises(ValueError, match="Windows executable"):
        release.validate_archives(tmp_path, SOURCE)


def prepare_publication(monkeypatch, tmp_path, *, existing=None, missing_asset=False,
                        upload_fails=False, existing_tag=None):
    make_archives(tmp_path)
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({"sha": SHA, "tag": "v0.2.0", "version": "0.2.0",
                                   "repository": REPOSITORY, "build_url": RUN["html_url"]}))
    calls = []
    monkeypatch.setattr(release.subprocess, "check_output", lambda command: SOURCE)

    def git(command, **kwargs):
        if command[1] == "archive":
            output = next(arg.removeprefix("--output=") for arg in command if arg.startswith("--output="))
            with zipfile.ZipFile(output, "w") as archive:
                archive.writestr("MCSync-source/mcsync.py", SOURCE)
            return subprocess.CompletedProcess(command, 0)
        assert command[1] == "rev-parse" and command[-1].endswith("^{commit}")
        return subprocess.CompletedProcess(command, 0 if existing_tag else 1, stdout=existing_tag or "")

    def gh(*args):
        calls.append(args)
        if args[0] == "api":
            return json.dumps([existing] if existing else [])
        if args[:2] == ("release", "upload") and upload_fails:
            raise subprocess.CalledProcessError(1, args)
        if args[:2] == ("release", "view"):
            paths = sorted(tmp_path.glob("*.zip")) + sorted(tmp_path.glob("*.sha256"))
            if missing_asset:
                paths = paths[:-1]
            return json.dumps({"isDraft": True, "assets": [
                {"name": path.name, "size": path.stat().st_size} for path in paths
            ]})
        return ""

    monkeypatch.setattr(release.subprocess, "run", git)
    monkeypatch.setattr(release, "gh", gh)
    return metadata, calls


def test_publish_only_after_all_eight_assets_are_uploaded(monkeypatch, tmp_path):
    metadata, calls = prepare_publication(monkeypatch, tmp_path)
    release.publish(tmp_path, metadata)
    creation = next(call for call in calls if call[:2] == ("release", "create"))
    assert "--draft" in creation and "--prerelease" in creation
    assert creation[creation.index("--target") + 1] == SHA
    upload = next(call for call in calls if call[:2] == ("release", "upload"))
    assert len([arg for arg in upload if arg.endswith((".zip", ".sha256"))]) == 8
    assert "--draft=false" in calls[-1]
    assert calls.index(upload) < len(calls) - 1


def test_failed_upload_never_publishes_a_partial_release(monkeypatch, tmp_path):
    metadata, calls = prepare_publication(monkeypatch, tmp_path, upload_fails=True)
    with pytest.raises(subprocess.CalledProcessError):
        release.publish(tmp_path, metadata)
    assert not any("--draft=false" in call for call in calls)


def test_incomplete_uploaded_assets_keep_the_release_a_draft(monkeypatch, tmp_path):
    metadata, calls = prepare_publication(monkeypatch, tmp_path, missing_asset=True)
    with pytest.raises(ValueError, match="incomplete"):
        release.publish(tmp_path, metadata)
    assert not any("--draft=false" in call for call in calls)


@pytest.mark.parametrize("existing", [
    {"tag_name": "v0.2.0", "draft": False},
    {"tag_name": "v0.2.0", "draft": True, "target_commitish": "b" * 40},
])
def test_published_release_or_different_draft_is_never_overwritten(existing, monkeypatch, tmp_path):
    metadata, calls = prepare_publication(monkeypatch, tmp_path, existing=existing)
    with pytest.raises(ValueError):
        release.publish(tmp_path, metadata)
    assert not any(call[:2] == ("release", "upload") for call in calls)


def test_existing_tag_must_resolve_to_the_verified_commit(monkeypatch, tmp_path):
    metadata, calls = prepare_publication(monkeypatch, tmp_path, existing_tag="b" * 40)
    with pytest.raises(ValueError, match="tag"):
        release.publish(tmp_path, metadata)
    assert not any(call[:2] == ("release", "upload") for call in calls)


@pytest.mark.parametrize("explicit,message,expected", [
    ("123", "ordinary commit", "123"),
    ("", "release: 37032863485", "37032863485"),
    ("", "release: 123\n\nPublish verified binaries", "123"),
])
def test_publication_request_uses_only_a_numeric_run_id(explicit, message, expected):
    assert release.requested_run_id(explicit, message) == expected


@pytest.mark.parametrize("explicit,message", [
    ("", "ordinary commit"), ("", "release: 123; echo unsafe"),
    ("../../123", "release: 123"), ("", ""),
])
def test_ordinary_or_unsafe_commits_cannot_request_publication(explicit, message):
    with pytest.raises(ValueError):
        release.requested_run_id(explicit, message)


def test_github_failure_keeps_the_server_error_for_diagnostics(monkeypatch):
    monkeypatch.setattr(release.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args, 1, stdout="", stderr="HTTP 403: permission denied"))
    with pytest.raises(RuntimeError, match="HTTP 403: permission denied"):
        release.gh("release", "create", "v0.2.0")
