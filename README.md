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

In [run 34007744965](https://github.com/tgrnwd/ipados-document-browser-repro/actions/runs/34007744965), commit `9337dde`, on iPadOS 26.5:

| Mode | Result | Whole job |
| --- | --- | --- |
| `prepared` | Both tests passed; zero skips | 12m10s |
| `cold` | Seed tile was not found; create/save/reopen passed; zero skips | 11m31s |

The cold video remained on Recents after the Browse tap; that test never attempted to open the seed. Browser navigation now checks progress with bounded attempts so the cold comparison can reach the intended operation. The prepared system log shows the recreated seed received a different document ID and resolved successfully, even after another app-container relocation. This is one successful generic sequence, not proof of a workaround for another application's failure or certification of another application's test suite.

License: GPL-3.0-only; see [LICENSE](LICENSE).
