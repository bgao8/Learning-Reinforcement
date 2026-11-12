// Presses the system play/pause media key once, like the keyboard's ⏯ key (#20).
//
//   npm run build:native        # compiles this to client/native/mediakey (gitignored)
//   ./native/mediakey           # pauses/resumes whatever app is "Now Playing"
//
// Exit codes: 0 = key posted, 2 = Accessibility permission missing.
//
// Why Swift and not an osascript/JXA one-liner: JXA's ObjC bridge can't return
// NSEvent.cgEvent (a CoreFoundation type, not an ObjC object). It hands back an
// empty event (type 0), CGEventPost drops it, and nothing reports an error.
// Swift is compiled against the SDK headers, so it gets the real CGEvent.

import AppKit

// A media key is not a normal key code. macOS sends it as a "system-defined" event:
//   type    .systemDefined (14)
//   subtype 8      NX_SUBTYPE_AUX_CONTROL_BUTTONS (media / volume / brightness keys)
//   data1          bits 16-31 key id (NX_KEYTYPE_PLAY = 16), bits 8-15 state (0xA down, 0xB up)
//   flags          0xA00 down / 0xB00 up, matching what the hardware sends
let NX_KEYTYPE_PLAY = 16

func post(down: Bool) {
    let state = down ? 0xA : 0xB
    let event = NSEvent.otherEvent(
        with: .systemDefined,
        location: .zero,
        modifierFlags: NSEvent.ModifierFlags(rawValue: UInt(state << 8)),
        timestamp: 0,
        windowNumber: 0,
        context: nil,
        subtype: 8,
        data1: (NX_KEYTYPE_PLAY << 16) | (state << 8),
        data2: -1
    )
    // .cghidEventTap injects at the hardware level, so macOS routes it like the real key
    event?.cgEvent?.post(tap: .cghidEventTap)
}

// Without Accessibility permission the post is silently dropped, so check first.
// The permission belongs to whatever launched us (VS Code / Terminal in dev).
guard AXIsProcessTrusted() else {
    FileHandle.standardError.write("Accessibility permission missing\n".data(using: .utf8)!)
    exit(2)
}

post(down: true)
usleep(50_000)      // a real press: down, short gap, up
post(down: false)
print("posted play/pause")
