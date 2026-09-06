# iPad document-browser reproducer

A standalone SwiftUI counter document for investigating document opening on a fresh iPadOS 26 simulator on a standard GitHub-hosted `macos-26` runner.

The app uses `DocumentGroup` and `ReferenceFileDocument`. Its entire document is one integer stored as UTF-8 text in a `.docprobe` file. An Increment button registers an undo operation and updates the counter. There are no dependencies, remote services, app assets, or credentials.

The two UI tests exercise the real system document browser:

- Open an externally seeded document and verify its value.
- Create a new document, increment its value, close it, verify the saved bytes, and reopen it.

Use **Actions → iPad document browser → Run workflow**. The workflow is manually triggered and checks out only this repository. It accepts no private repository credentials and does not execute issue or pull-request content.

| Mode | Sequence |
| --- | --- |
| `cold` | Install and seed → open seed → create/save/reopen a new document |
| `prepared` | Install and seed → create/save/reopen a new document → preserve the old seed elsewhere and create a fresh file at its path → open seed |
| `both` | Run each mode on its own fresh hosted VM |

Every run builds its own app/test products and creates its own simulator. The selected runtime is the latest installed iPadOS 26 runtime. Each test must appear exactly once and pass with zero skips. The new-document and browser entrances allow up to three explicitly logged navigation/preparation attempts; the test methods themselves are never automatically rerun.

Artifacts contain the environment version, per-stage logs, document-service logs, native `.xcresult` bundles, and video (compressed when the encoder is available). Artifacts expire after one day. Standard hosted runner time is free for public repositories; storage remains subject to the account's applicable limits. No billing settings are changed by this workflow.

Completed runs on iPadOS 26.5, using the standard `macos-26` runner:

| Mode | Result | Whole job | Evidence |
| --- | --- | --- | --- |
| `cold` | Both tests passed; zero skips | 7m16s | [34008472728, commit 9dfd025](https://github.com/tgrnwd/ipados-document-browser-repro/actions/runs/34008472728) |
| `prepared` | Both tests passed; zero skips | 12m10s | [34007744965, commit 9337dde](https://github.com/tgrnwd/ipados-document-browser-repro/actions/runs/34007744965/job/101417955051) |

The first cold attempt at commit `9337dde` failed before opening the seed: its video remained on Recents after the Browse tap. Browser navigation now checks progress with bounded attempts. The corrected cold run passed without recreating its seed, so the prepared sequence has not been shown necessary for this app. The prepared system log also shows its recreated seed received a different document ID and resolved successfully, even after another app-container relocation. These are successful generic sequences, not proof of a workaround for another application's failure or certification of another application's test suite.

License: GPL-3.0-only; see [LICENSE](LICENSE).
