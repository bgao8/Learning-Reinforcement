// Prints the title of the video that's probably playing, as JSON, for the session title.
//
//   npm run build:native        # compiles this to client/native/videotitle (gitignored)
//   ./native/videotitle         # {"app":"Google Chrome","playing":true,"title":"Lecture 4 - YouTube 🔊"}
//
// Chromium browsers (Chrome, Arc, Brave, Edge) end a window's title with 🔊 while its tab plays
// sound: that's the video being transcribed, wherever it is (full screen, another Space). With
// none, it falls back to the frontmost on-screen browser window with a title, as "playing":false.
// With no titled browser window at all it prints {"title":null}. main.js strips the 🔊 and the
// site name.
//
// Titles come from CGWindowListCopyWindowInfo: window metadata only, never pixels. macOS fills
// them in only for apps with Screen Recording permission, which the app already has for audio
// capture; without it every title is empty and this prints {"title":null}.
//
// (macOS's own "Now Playing" info would be the ideal source, but since macOS 15.4 it returns
// nothing to apps without an Apple-only entitlement.)

import CoreGraphics
import Foundation

let browsers: Set<String> = [
    "Google Chrome", "Arc", "Brave Browser", "Microsoft Edge", "Chromium", "Vivaldi", "Opera",
    "Safari", "Firefox",
]

// front to back; layer 0 is ordinary app windows (not menus, tooltips or the menu bar)
let windows = CGWindowListCopyWindowInfo([.optionAll, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
let titled = windows.compactMap { w -> (app: String, title: String, onscreen: Bool)? in
    guard let app = w[kCGWindowOwnerName as String] as? String, browsers.contains(app),
          (w[kCGWindowLayer as String] as? Int) == 0,
          let title = w[kCGWindowName as String] as? String, !title.isEmpty
    else { return nil }
    return (app, title, w[kCGWindowIsOnscreen as String] as? Bool ?? false)
}

var out: [String: Any] = ["title": NSNull()]
if let w = titled.first(where: { $0.title.hasSuffix("🔊") }) {
    out = ["app": w.app, "title": w.title, "playing": true]
} else if let w = titled.first(where: { $0.onscreen }) {
    out = ["app": w.app, "title": w.title, "playing": false]
}

let data = try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
