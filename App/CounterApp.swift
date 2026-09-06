// SPDX-License-Identifier: GPL-3.0-only
import SwiftUI
import UniformTypeIdentifiers

extension UTType {
    static let counterDocument = UTType(exportedAs: "org.example.document-browser-probe", conformingTo: .data)
}

final class CounterDocument: ReferenceFileDocument {
    static var readableContentTypes: [UTType] { [.counterDocument] }
    @Published var value: Int

    init() { value = 0 }
    required init(configuration: ReadConfiguration) throws {
        guard let data = configuration.file.regularFileContents,
              let text = String(data: data, encoding: .utf8) else {
            throw CocoaError(.fileReadCorruptFile)
        }
        if let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let number = object["value"] as? Int {
            value = number
        } else if let number = Int(text.trimmingCharacters(in: .whitespacesAndNewlines)) {
            value = number
        } else {
            throw CocoaError(.fileReadCorruptFile)
        }
    }
    func snapshot(contentType: UTType) throws -> Int { value }
    func fileWrapper(snapshot: Int, configuration: WriteConfiguration) throws -> FileWrapper {
        if ProcessInfo.processInfo.environment["DOCUMENT_PROBE_JSON"] == "1" {
            // A ~1 KB JSON body, like a real rig document.
            let padding = String(repeating: "x", count: 900)
            return FileWrapper(regularFileWithContents: Data("{\"value\": \(snapshot), \"padding\": \"\(padding)\"}\n".utf8))
        }
        return FileWrapper(regularFileWithContents: Data("\(snapshot)\n".utf8))
    }
}

struct CounterView: View {
    @ObservedObject var document: CounterDocument
    @Environment(\.undoManager) private var undoManager

    var body: some View {
        VStack(spacing: 24) {
            Text("Value: \(document.value)").accessibilityIdentifier("counterValue")
            Button("Increment") {
                let previous = document.value
                undoManager?.registerUndo(withTarget: document) { $0.value = previous }
                document.value += 1
            }.accessibilityIdentifier("increment")
        }.padding()
    }
}

@main struct CounterApp: App {
    init() {
        if ProcessInfo.processInfo.environment["DOCUMENT_PROBE_FOLDER"] == "1" {
            // Like an app that keeps a downloads folder inside Documents and
            // ensures it exists at every launch.
            let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            try? FileManager.default.createDirectory(at: documents.appendingPathComponent("Downloads"), withIntermediateDirectories: true)
            try? Data("\(Date())\n".utf8).write(to: documents.appendingPathComponent("Downloads/.launched"))
        }
        if ProcessInfo.processInfo.environment["DOCUMENT_PROBE_LOAD"] == "1" {
            // Mimic an app that does real work at launch (an audio engine, model
            // loading): three threads spinning for the life of the process.
            for _ in 0..<3 {
                Thread.detachNewThread {
                    var x: UInt64 = 0x9E3779B97F4A7C15
                    while true { x = x &* 6364136223846793005 &+ 1442695040888963407; if x == 0 { break } }
                }
            }
        }
        #if DEBUG
        if let path = ProcessInfo.processInfo.environment["DOCUMENT_PROBE_SEED"] {
            do {
                let url = URL(fileURLWithPath: path)
                try Data("0\n".utf8).write(to: url)
                if ProcessInfo.processInfo.environment["DOCUMENT_PROBE_SEED_VERSION"] == "1" {
                    // Public document-versions API: registers the file with revisiond, which
                    // allocates its document ID and creates the per-volume library, before any
                    // browser enumeration can allocate an ID that nothing records.
                    // Adding versions is macOS-only; these two queries exist on iOS and go to
                    // the same versions service. Log the kernel document identifier after them.
                    let current = NSFileVersion.currentVersionOfItem(at: url)
                    let others = NSFileVersion.otherVersionsOfItem(at: url)
                    let identifier = try? url.resourceValues(forKeys: [.documentIdentifierKey]).documentIdentifier
                    print("seed versions: current=\(current != nil) others=\(others?.count ?? -1) documentIdentifier=\(String(describing: identifier))")
                }
                exit(0)
            } catch {
                fputs("Seed export failed: \(error)\n", stderr)
                exit(1)
            }
        }
        #endif
    }
    var body: some Scene {
        DocumentGroup(newDocument: { CounterDocument() }) { configuration in
            CounterView(document: configuration.document)
        }
    }
}
