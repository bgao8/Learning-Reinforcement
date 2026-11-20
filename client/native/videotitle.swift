// Prints the title of the video that's probably playing, as JSON, for the session title.
//
//   npm run build:native        # compiles this to client/native/videotitle (gitignored)
//   ./native/videotitle         # {"app":"Google Chrome","source":"sound","title":"Lecture 4 - YouTube 🔊"}
//
// Browser windows are ranked by how sure we are that they hold the video, best first:
//   "sound"  the title ends with 🔊: Chromium browsers (Chrome, Arc, Brave, Edge) add it while
//            the window's selected tab plays sound. Near certain, but the 🔊 isn't always there.
//   "site"   the title names a video site (YouTube, Coursera, ...). Probably the video.
//   "front"  the frontmost browser window on the current screen. Only a guess at where the user
//            is looking, so the app waits before trusting it (see watchTitle in app.js).
// "sound" and "site" also look at windows off the current screen (full screen, another Space),
// preferring on-screen ones. With no titled browser window at all it prints {"title":null}.
// main.js strips the 🔊 and the site name.
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
let videoSites = ["YouTube", "Vimeo", "Coursera", "edX", "Khan Academy", "Udemy", "Panopto", "Kaltura", "Echo360"]

// a page on a video site, not just its home page (a title that is only "YouTube" names no video)
func onVideoSite(_ title: String) -> Bool {
    let t = title.replacingOccurrences(of: "🔊", with: "")
        .replacingOccurrences(of: #"^\(\d+\+?\)\s*"#, with: "", options: .regularExpression)   // "(3) " unread count
        .trimmingCharacters(in: .whitespaces)
    return videoSites.contains { site in
        t.localizedCaseInsensitiveContains(site) && t.caseInsensitiveCompare(site) != .orderedSame
    }
}

// front to back; layer 0 is ordinary app windows (not menus, tooltips or the menu bar)
let windows = CGWindowListCopyWindowInfo([.optionAll, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
let titled = windows.compactMap { w -> (app: String, title: String, onscreen: Bool)? in
    guard let app = w[kCGWindowOwnerName as String] as? String, browsers.contains(app),
          (w[kCGWindowLayer as String] as? Int) == 0,
          let title = w[kCGWindowName as String] as? String, !title.isEmpty
    else { return nil }
    return (app, title, w[kCGWindowIsOnscreen as String] as? Bool ?? false)
}
// the screen being looked at first, each group still front to back
let ranked = titled.filter { $0.onscreen } + titled.filter { !$0.onscreen }

var out: [String: Any] = ["title": NSNull()]
if let w = ranked.first(where: { $0.title.hasSuffix("🔊") }) {
    out = ["app": w.app, "title": w.title, "source": "sound"]
} else if let w = ranked.first(where: { onVideoSite($0.title) }) {
    out = ["app": w.app, "title": w.title, "source": "site"]
} else if let w = titled.first(where: { $0.onscreen }) {
    out = ["app": w.app, "title": w.title, "source": "front"]
}

let data = try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
