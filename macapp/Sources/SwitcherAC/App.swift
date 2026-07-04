import SwiftUI
import AppKit

/// Hide the Dock icon — this is a menu-bar-only agent app.
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
    }
}

@main
struct SwitcherACApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var model = ACModel()

    var body: some Scene {
        MenuBarExtra {
            ContentView().environmentObject(model)
        } label: {
            // Live menu-bar label: an SF Symbol + the room temp.
            Image(systemName: model.state.isOn ? "snowflake" : "thermometer.medium")
            Text(model.menuTitle)
        }
        .menuBarExtraStyle(.window)
    }
}
