// SPDX-License-Identifier: GPL-3.0-only
import XCTest

final class DocumentUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    @MainActor private func launch(_ app: XCUIApplication) {
        app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
    }

    @MainActor private func open(_ name: String, in app: XCUIApplication) {
        let stem = (name as NSString).deletingPathExtension
        let cell = app.cells.matching(NSPredicate(format: "label BEGINSWITH %@", stem)).firstMatch
        if !cell.waitForExistence(timeout: 8) {
            // Cold browser, run 34007744965: one tap on the Browse segment left "No Recents" on
            // screen and the seed was never enumerated. Tap again rather than fail on the tap;
            // the tile itself is still asserted below.
            let browse = app.buttons["Browse"].firstMatch
            XCTAssertTrue(browse.waitForExistence(timeout: 10))
            for attempt in 1...3 {
                browse.tap()
                print("BROWSE-TAP attempt=\(attempt) selected=\(browse.isSelected)")
                if cell.waitForExistence(timeout: 10) { break }
                // Browse may land in the locations list instead of this app's folder.
                let folder = app.cells.matching(NSPredicate(format: "label BEGINSWITH %@", "DocumentBrowserProbe")).firstMatch
                if folder.exists {
                    print("BROWSE-FOLDER attempt=\(attempt)")
                    folder.tap()
                    if cell.waitForExistence(timeout: 10) { break }
                }
            }
        }
        XCTAssertTrue(cell.waitForExistence(timeout: 5), "Document tile missing: \(name)")
        cell.tap()
    }

    private func documents() throws -> URL {
        let parent = URL(fileURLWithPath: NSHomeDirectory()).deletingLastPathComponent()
        for container in try FileManager.default.contentsOfDirectory(at: parent, includingPropertiesForKeys: nil) {
            let folder = container.appendingPathComponent("Documents")
            if FileManager.default.fileExists(atPath: folder.appendingPathComponent("seed.docprobe").path) {
                return folder
            }
        }
        throw CocoaError(.fileNoSuchFile)
    }

    @MainActor func testOpenSeed() {
        let app = XCUIApplication()
        defer { app.terminate() }
        launch(app)
        open("seed.docprobe", in: app)
        let value = app.staticTexts["counterValue"]
        XCTAssertTrue(value.waitForExistence(timeout: 20), "Seed never reached document content")
        XCTAssertEqual(value.label, "Value: 0")
    }

    @MainActor func testCreateEditAndReopen() throws {
        let app = XCUIApplication()
        defer { app.terminate() }
        let value = app.staticTexts["counterValue"]
        var folder: URL?
        // Preparation retries are explicit. Native test failures are not retried.
        for attempt in 1...3 {
            launch(app)
            let current = try documents()
            folder = current
            for file in try FileManager.default.contentsOfDirectory(at: current, includingPropertiesForKeys: nil)
                where file.pathExtension == "docprobe" && file.lastPathComponent != "seed.docprobe" {
                try FileManager.default.removeItem(at: file)
            }
            app.terminate()
            launch(app)
            let create = app.buttons["Create Document"].firstMatch
            XCTAssertTrue(create.waitForExistence(timeout: 30), "Create Document button missing")
            create.tap()
            let deadline = Date().addingTimeInterval(25)
            while Date() < deadline && !value.exists && !app.alerts.firstMatch.exists {
                Thread.sleep(forTimeInterval: 0.2)
            }
            print("DOCUMENT-ENTRANCE attempt=\(attempt) content=\(value.exists) alert=\(app.alerts.firstMatch.exists)")
            if value.exists { break }
            app.terminate()
        }
        XCTAssertTrue(value.exists, "New document never reached content")
        XCTAssertEqual(value.label, "Value: 0")
        app.buttons["increment"].tap()
        XCTAssertEqual(value.label, "Value: 1")
        let back = app.navigationBars.buttons.element(boundBy: 0)
        XCTAssertTrue(back.exists)
        back.tap()
        let closed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: value)
        XCTAssertEqual(XCTWaiter.wait(for: [closed], timeout: 15), .completed)
        let files = try FileManager.default.contentsOfDirectory(at: XCTUnwrap(folder), includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "docprobe" && $0.lastPathComponent != "seed.docprobe" }
        XCTAssertEqual(files.count, 1)
        let saved = try XCTUnwrap(files.first)
        let saveDeadline = Date().addingTimeInterval(15)
        while Date() < saveDeadline && (try? String(contentsOf: saved, encoding: .utf8)) != "1\n" {
            Thread.sleep(forTimeInterval: 0.2)
        }
        XCTAssertEqual(try String(contentsOf: saved, encoding: .utf8), "1\n")
        open(saved.lastPathComponent, in: app)
        XCTAssertTrue(value.waitForExistence(timeout: 20))
        XCTAssertEqual(value.label, "Value: 1")
    }
}
