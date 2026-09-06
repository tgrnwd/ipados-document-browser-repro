#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Run only this standalone reproducer, on a disposable GitHub-hosted Mac."""
import hashlib
import re
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
    raise SystemExit("Run this through the manual GitHub Actions workflow.")
mode = sys.argv[1]
assert mode in ("cold", "prepared", "warm", "kick", "openurl", "version",
                "stress", "stress-load", "stress-nokey", "stress-nokey-load")
# sys/stat.h: "UF_TRACKED is used for dealing with document IDs."
UF_TRACKED = 0x40
root = Path.cwd()
out = root / "results"
out.mkdir(exist_ok=True)
bundle_id = "org.example.DocumentBrowserProbe"
stages = []
children = []
device = None


def stop(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGINT)
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        except ProcessLookupError:
            pass


def run(args, name, timeout=180, check=True, env=None):
    print(f"Starting {name}", flush=True)
    start = time.monotonic()
    with (out / f"{name}.log").open("w") as log:
        process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            stop(process)
            code = 124
        except BaseException:
            stop(process)
            raise
    print(f"Finished {name}: exit={code}, seconds={time.monotonic()-start:.2f}", flush=True)
    if code:
        print((out / f"{name}.log").read_text(errors="replace")[-6000:], flush=True)
    if check and code:
        raise RuntimeError(f"{name} exited {code}")
    return code


def capture(args, name):
    run(args, name)
    return (out / f"{name}.log").read_text().strip()


def data_container(label):
    return Path(capture(["xcrun", "simctl", "get_app_container", device, bundle_id, "data"], label))


def revisions_library():
    """revisiond's per-volume library for the simulator, at the device data root."""
    return Path.home() / "Library/Developer/CoreSimulator/Devices" / device / "data/.DocumentRevisions-V100"


def tracked(path):
    """Read-only: does the file carry a kernel document ID (UF_TRACKED)? None when absent."""
    try:
        return bool(os.stat(path).st_flags & UF_TRACKED)
    except OSError:
        return None


def docid_state(label, *paths):
    """Read-only: is revisiond's library present, and which documents carry an ID?"""
    library = revisions_library()
    line = dict(at=time.strftime("%Y-%m-%dT%H:%M:%S"), label=label, library=library.is_dir(),
                library_status=(library / "LibraryStatus").is_file(),
                files={str(path): tracked(path) for path in paths})
    with (out / "docid-state.log").open("a") as log:
        log.write(json.dumps(line) + "\n")
    print(json.dumps(line), flush=True)
    return line


def recreate_seed(label):
    """Same bytes at the same path, but a new inode, so its document ID is allocated afresh."""
    data = data_container(label + "-container")
    seed = data / "Documents/seed.docprobe"
    archived = data / "tmp/old-seed.docprobe"
    archived.parent.mkdir(exist_ok=True)
    contents = seed.read_bytes()
    assert contents == b"0\n" and not archived.exists()
    run(["/bin/mv", str(seed), str(archived)], "preserve-old-seed")
    with seed.open("xb") as output:
        output.write(contents)
    assert seed.stat().st_ino != archived.stat().st_ino
    (out / "recreated-seed.json").write_text(json.dumps(dict(old_inode=archived.stat().st_ino,
        old_tracked=tracked(archived), new_inode=seed.stat().st_ino,
        sha256=hashlib.sha256(contents).hexdigest()), indent=2))
    return seed


def warm(seed, seconds=300):
    """Prime revisiond's library without any UI test: launch the app normally so the document
    browser appears, and wait until the seed carries a document ID or the library exists."""
    run(["xcrun", "simctl", "launch", device, bundle_id], "warm-launch")
    started = time.monotonic()
    observed = None
    # A plain launch shows Recents, which does not enumerate the app container, so the seed
    # stays untracked; revisiond's library still appeared about 130 s after launch (run
    # 34008028659). Wait for the library itself; LibraryStatus is written at the end of init.
    while time.monotonic() - started < seconds:
        state = docid_state("warm poll", seed)
        if state["library_status"]:
            observed = round(time.monotonic() - started, 1)
            break
        time.sleep(5)
    time.sleep(15)
    final = docid_state("warm settled", seed)
    run(["xcrun", "simctl", "terminate", device, bundle_id], "warm-terminate", check=False)
    (out / "warm.json").write_text(json.dumps(dict(seconds_until_observed=observed, final=final), indent=2))
    return observed


def kick(seconds=90):
    """Deterministic priming candidate, no UI: start revisiond inside the simulator before any
    document is enumerated. Its launchd job (RunAtLoad, KeepAlive) creates .DocumentRevisions-V100
    for the data volume at startup; in the cold passes it happened to start a few seconds before
    the seed's lookup, in the real app it starts only at that lookup and the lookup fails."""
    docid_state("before kick")
    # launchd_sim hosts daemons in the user/foreground domain; "system/..." only warns
    # (rdar://78126471 in its own output, run 34009201672) and starts nothing.
    job = "user/foreground/com.apple.revisiond"
    run(["xcrun", "simctl", "spawn", device, "launchctl", "print", job], "launchctl-print-before", check=False)
    code = run(["xcrun", "simctl", "spawn", device, "launchctl", "kickstart", job], "kickstart", check=False)
    if code:
        run(["xcrun", "simctl", "spawn", device, "launchctl", "start", "com.apple.revisiond"],
            "launchctl-start", check=False)
    started = time.monotonic()
    library = revisions_library()
    while time.monotonic() - started < seconds:
        state = docid_state("kick poll")
        # metadata and db-V1 appear at library creation; LibraryStatus can be written later.
        if (library / "metadata").is_file() and (library / "db-V1").is_dir():
            time.sleep(10)
            run(["xcrun", "simctl", "spawn", device, "launchctl", "print", job], "launchctl-print-after", check=False)
            docid_state("kick settled")
            return round(time.monotonic() - started, 1)
        time.sleep(2)
    run(["xcrun", "simctl", "spawn", device, "launchctl", "print", job], "launchctl-print-after", check=False)
    return None


def test(method, label):
    expected = f"DocumentUITests/{method}"
    result = out / f"{label}.xcresult"
    code = run(["xcodebuild", "test-without-building", "-xctestrun", str(manifest),
        "-destination", f"platform=iOS Simulator,id={device}", "-parallel-testing-enabled", "NO",
        "-only-testing:DocumentBrowserProbeUITests/" + expected, "-resultBundlePath", str(result)],
        label, timeout=600, check=False)
    summary = json.loads(capture(["xcrun", "xcresulttool", "get", "test-results", "summary", "--path", str(result)], label+"-summary"))
    details = json.loads(capture(["xcrun", "xcresulttool", "get", "test-results", "tests", "--path", str(result)], label+"-tests"))
    def identities(node):
        if isinstance(node, dict):
            if node.get("nodeType") == "Test Case":
                yield node.get("nodeIdentifier", "").removeprefix("DocumentBrowserProbeUITests/").removesuffix("()")
            for value in node.values():
                yield from identities(value)
        elif isinstance(node, list):
            for value in node:
                yield from identities(value)
    passed = code == 0 and list(identities(details)) == [expected] and all(
        summary.get(k) == v for k, v in dict(result="Passed", totalTestCount=1, passedTests=1,
            failedTests=0, skippedTests=0, expectedFailures=0).items())
    stages.append(dict(method=method, passed=passed, exit=code, summary=summary))
    print(json.dumps(stages[-1], indent=2), flush=True)
    return passed


try:
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    run(["xcodebuild", "-version"], "xcode")
    run(["sw_vers"], "macos")
    run(["sysctl", "hw.ncpu", "hw.memsize"], "hardware")
    (out / "image.json").write_text(json.dumps({key: os.environ.get(key) for key in ("ImageOS", "ImageVersion", "GITHUB_SHA")}))
    if "nokey" in mode:
        # Photoslop #228 (2026-08): LSSupportsOpeningDocumentsInPlace without
        # UIFileSharingEnabled could not create documents on a fresh simulator.
        run(["plutil", "-remove", "UIFileSharingEnabled", "App/Info.plist"], "plist-remove-filesharing")
    run(["plutil", "-p", "App/Info.plist"], "plist")
    run(["xcodebuild", "build-for-testing", "-project", "DocumentBrowserProbe.xcodeproj",
         "-scheme", "DocumentBrowserProbe", "-destination", "generic/platform=iOS Simulator",
         "-derivedDataPath", ".build", "ARCHS=arm64"], "build", timeout=600)
    manifests = list((root / ".build/Build/Products").glob("*.xctestrun"))
    assert len(manifests) == 1
    manifest = manifests[0]
    runtimes = json.loads(capture(["xcrun", "simctl", "list", "runtimes", "--json"], "runtimes"))["runtimes"]
    runtime = max((r for r in runtimes if r.get("isAvailable") and r["name"].startswith("iOS 26.")),
                  key=lambda r: tuple(int(v) for v in r["version"].split(".")))["identifier"]
    device_types = json.loads(capture(["xcrun", "simctl", "list", "devicetypes", "--json"], "device-types"))["devicetypes"]
    matching_types = [entry for entry in device_types if entry["name"] == "iPad Pro 13-inch (M5)"]
    assert len(matching_types) == 1, "Expected iPad Pro 13-inch (M5) device type is unavailable"
    device = capture(["xcrun", "simctl", "create", "Document browser repro", matching_types[0]["identifier"], runtime], "create")
    run(["defaults", "write", "com.apple.iphonesimulator", "ConnectHardwareKeyboard", "-bool", "false"], "keyboard")
    run(["xcrun", "simctl", "boot", device], "boot")
    run(["open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", device], "simulator")
    run(["xcrun", "simctl", "bootstatus", device], "bootstatus", timeout=360)
    predicate = 'process == "revisiond" OR process == "ResolverService" OR process == "LocalStorageFileProvider" OR process == "fileproviderd"'
    for command, name in [
        (["log", "stream", "--style", "compact", "--level", "debug", "--predicate", predicate], "document-services.log"),
        (["xcrun", "simctl", "spawn", device, "log", "stream", "--style", "compact", "--level", "debug", "--predicate", predicate], "simulator-services.log"),
        (["xcrun", "simctl", "io", device, "recordVideo", "--codec=h264", str(out / "session.mov")], "recorder.log")]:
        handle = (out / name).open("w")
        children.append((subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True), handle))
    deadline = time.monotonic()+180
    while "Recording started" not in (out / "recorder.log").read_text():
        if time.monotonic() > deadline or children[-1][0].poll() is not None:
            raise RuntimeError("video did not become ready")
        time.sleep(1)
    app = root / ".build/Build/Products/Debug-iphonesimulator/DocumentBrowserProbe.app"
    run(["xcrun", "simctl", "install", device, str(app)], "install")
    folder = data_container("initial-container") / "Documents"
    folder.mkdir(exist_ok=True)
    seed = folder / "seed.docprobe"
    if mode == "kick":
        kicked = kick()
        (out / "kick.json").write_text(json.dumps(dict(seconds_until_library=kicked), indent=2))
        assert kicked is not None, "starting revisiond did not create its library"
    seed_env = dict(os.environ, SIMCTL_CHILD_DOCUMENT_PROBE_SEED=str(seed))
    if mode == "version":
        seed_env["SIMCTL_CHILD_DOCUMENT_PROBE_SEED_VERSION"] = "1"
    run(["xcrun", "simctl", "launch", "--console", device, bundle_id], "seed", env=seed_env)
    assert seed.read_bytes() == b"0\n"
    docid_state("after seed export", seed)
    if mode == "prepared":
        assert test("testCreateEditAndReopen", "create-save"), "document preparation failed"
        docid_state("after create-save", data_container("prepared-check") / "Documents/seed.docprobe")
        seed = recreate_seed("prepared")
        docid_state("after recreating the seed", seed)
        test("testOpenSeed", "open-seed")
    elif mode == "warm":
        # No UI test before the seed is final: a plain launch shows the browser, which may
        # allocate the seed's document ID and let revisiond create its library. Then the seed
        # is recreated (new inode) and the tests run in the cold order.
        observed = warm(seed)
        assert observed is not None, "plain launch never led to revisiond creating its library"
        seed = recreate_seed("warm")
        docid_state("after recreating the seed", seed)
        test("testOpenSeed", "open-seed")
        test("testCreateEditAndReopen", "create-save")
    elif mode.startswith("stress"):
        env_extra = dict(os.environ)
        # The test target inherits the runner's environment via the xctestrun's
        # UITargetAppEnvironmentVariables only when written there; pass it through
        # the launch environment instead by editing the manifest.
        import plistlib
        manifest_data = plistlib.loads(manifest.read_bytes())
        for config in manifest_data.get("TestConfigurations", []):
            for target in config.get("TestTargets", []):
                target.setdefault("UITargetAppEnvironmentVariables", {})["DOCUMENT_PROBE_LOAD"] = "1" if "load" in mode else "0"
        stressed = manifest.with_name("Stress.xctestrun")
        stressed.write_bytes(plistlib.dumps(manifest_data))
        manifest = stressed
        test("testCreateRepeatedly", "create-repeatedly")
        outcomes = re.findall(r"DOCUMENT-STRESS creation=(\d+) outcome=(\w+)", (out / "create-repeatedly.log").read_text(errors="replace"))
        (out / "stress.json").write_text(json.dumps(dict(mode=mode, outcomes=outcomes,
            alerts=sum(1 for _, o in outcomes if o == "importAlert"), total=len(outcomes)), indent=2))
        print(json.dumps(json.loads((out / "stress.json").read_text())), flush=True)
    elif mode == "openurl":
        # Two documented file-URL deliveries, no browser: from XCTest, then from the host.
        test("testOpenSeedByURL", "open-seed")
        run(["xcrun", "simctl", "openurl", device, "file://" + str(seed)], "simctl-openurl", check=False)
        time.sleep(10)
        docid_state("after simctl openurl", seed)
        run(["xcrun", "simctl", "terminate", device, bundle_id], "terminate-after-openurl", check=False)
        test("testOpenSeed", "open-seed-browser")
    else:  # cold, kick and version (which only differ before or during seeding)
        test("testOpenSeed", "open-seed")
        test("testCreateEditAndReopen", "create-save")
    final_seed = data_container("final-container") / "Documents/seed.docprobe"
    docid_state("after all tests", final_seed)
    assert final_seed.read_bytes() == b"0\n"
    expected_stages = 1 if mode.startswith("stress") else 2
    assert len(stages) == expected_stages and all(stage["passed"] for stage in stages), "UI tests failed"
except BaseException as error:
    print(f"::error::{type(error).__name__}: {error}", flush=True)
    (out / "error.txt").write_text(f"{type(error).__name__}: {error}\n")
finally:
    for process, handle in reversed(children):
        stop(process)
        handle.close()
    (out / "results.json").write_text(json.dumps(dict(mode=mode, stages=stages), indent=2))
    if device:
        run(["xcrun", "simctl", "shutdown", device], "shutdown", check=False)
        run(["xcrun", "simctl", "delete", device], "delete", check=False)
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
        summary.write(f"## {mode}\n\n")
        for stage in stages:
            summary.write(f"- {stage['method']}: **{'PASS' if stage['passed'] else 'FAIL'}**\n")
        if (out / "error.txt").exists():
            summary.write("\n"+(out / "error.txt").read_text())
sys.exit(0 if len(stages) == (1 if mode.startswith("stress") else 2) and all(stage["passed"] for stage in stages) and not (out / "error.txt").exists() else 1)
