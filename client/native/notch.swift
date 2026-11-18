// Prints the size and position of the screen's notch as JSON, for the island overlay.
//
//   npm run build:native        # compiles this to client/native/notch (gitignored)
//   ./native/notch              # {"notch":true,"screenX":0,"screenWidth":1512,"left":663.5,"width":185,"height":32}
//
// Electron can report the menu bar's height but not the notch's width, so main.js runs this
// once at startup. Sizes are in points, the same units as Electron's screen API.
//   screenX, screenWidth   which display has the notch (to match it to an Electron display)
//   left                   distance from the screen's left edge to the notch
//   width, height          the notch itself
// With no notched screen it prints {"notch":false}, and the UI floats as a capsule instead.

import AppKit

var out: [String: Any] = ["notch": false]

for screen in NSScreen.screens {
    // the menu bar areas left and right of the notch; both are nil on screens without one
    guard let left = screen.auxiliaryTopLeftArea, let right = screen.auxiliaryTopRightArea else { continue }
    let frame = screen.frame
    out = [
        "notch": true,
        "screenX": frame.minX,
        "screenWidth": frame.width,
        "left": left.width,
        "width": frame.width - left.width - right.width,
        "height": screen.safeAreaInsets.top,
    ]
    break
}

let data = try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
