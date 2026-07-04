import SwiftUI
import AppKit

private let dashboardURL = URL(string: "http://127.0.0.1:3001")!

/// Parse the backend's naive-local ISO timestamp ("...THH:mm:ss.ffffff", no TZ).
private func parseLocal(_ s: String) -> Date? {
    let base = s.split(separator: ".").first.map(String.init) ?? s
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_US_POSIX")
    f.timeZone = .current
    f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
    return f.date(from: base)
}

struct ContentView: View {
    @EnvironmentObject var m: ACModel

    var body: some View {
        VStack(spacing: 12) {
            header
            PowerTile()
            Picker("", selection: modeBinding) {
                Text("Manual").tag("manual")
                Text("Auto").tag("thermostat")
                Text("Cycle").tag("cycle")
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            TargetTile()
            if m.state.mode == "cycle" {
                CycleTile()
            }
            footer
        }
        .padding(16)
        .frame(width: 300)
    }

    private var modeBinding: Binding<String> {
        Binding(get: { m.state.mode }, set: { m.setMode($0) })
    }

    private var tempText: String {
        if let t = m.state.temperature { return String(format: "%.1f°", t) }
        return "--°"
    }

    private var bandText: String {
        guard let t = m.state.temperature else { return "—" }
        if t > m.state.tooHot { return "Above limit" }
        if t < m.state.tooCold { return "Below limit" }
        return "Comfortable"
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 1) {
                Text("AYAL AC").font(.headline)
                Text(m.online ? bandText : "offline")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Text(tempText)
                .font(.system(size: 26, weight: .bold, design: .rounded))
                .monospacedDigit()
        }
    }

    private var footer: some View {
        HStack {
            Button {
                NSWorkspace.shared.open(dashboardURL)
            } label: {
                Label("Dashboard", systemImage: "safari")
            }
            .buttonStyle(.plain)
            Spacer()
            Button("Quit") { NSApplication.shared.terminate(nil) }
                .buttonStyle(.plain)
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }
}

/// The big Control-Center-style power tile.
struct PowerTile: View {
    @EnvironmentObject var m: ACModel

    var body: some View {
        Button(action: { m.togglePower() }) {
            HStack(spacing: 12) {
                Image(systemName: m.state.isOn ? "snowflake" : "power")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(m.state.isOn ? AnyShapeStyle(.white) : AnyShapeStyle(.secondary))
                    .frame(width: 42, height: 42)
                    .background(
                        m.state.isOn ? AnyShapeStyle(Color.blue.gradient) : AnyShapeStyle(.quaternary),
                        in: Circle()
                    )
                VStack(alignment: .leading, spacing: 2) {
                    Text(m.state.isOn ? "AC On" : "AC Off")
                        .font(.system(size: 15, weight: .semibold))
                    Text(subtitle).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
            }
            .padding(12)
            .background(.quaternary, in: RoundedRectangle(cornerRadius: 16))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private var subtitle: String {
        if m.state.isOn {
            let t = Int((m.state.acTemp ?? m.state.coolTemp).rounded())
            return "Target \(t)°C"
        }
        return "Tap to turn on"
    }
}

/// Target temperature slider tile. Commits on release (not on every drag tick).
struct TargetTile: View {
    @EnvironmentObject var m: ACModel

    var body: some View {
        VStack(spacing: 8) {
            HStack {
                Label("Target", systemImage: "thermometer.snowflake")
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
                Text("\(Int(m.state.coolTemp.rounded()))°C")
                    .font(.system(size: 14, weight: .semibold))
                    .monospacedDigit()
            }
            Slider(value: coolBinding, in: 16...30, step: 1, onEditingChanged: { editing in
                m.editingTarget = editing
                if !editing { m.setCool(Int(m.state.coolTemp.rounded())) }
            })
            .tint(.blue)
        }
        .padding(12)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 16))
    }

    private var coolBinding: Binding<Double> {
        Binding(get: { m.state.coolTemp }, set: { m.state.coolTemp = $0 })
    }
}

/// Cycle-mode tile: live phase + countdown and on/off duration steppers.
struct CycleTile: View {
    @EnvironmentObject var m: ACModel

    var body: some View {
        VStack(spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: m.state.cyclePhase == "on" ? "snowflake" : "moon.zzz")
                    .foregroundStyle(m.state.cyclePhase == "on" ? AnyShapeStyle(.blue) : AnyShapeStyle(.secondary))
                Text(m.state.cyclePhase == "on" ? "Cooling" : "Idle")
                    .font(.system(size: 14, weight: .semibold))
                Spacer()
                CountdownText(until: m.state.cyclePhaseUntil)
            }
            Stepper("On for  \(Int(m.state.cycleOnMin))m", value: onBinding, in: 1...240)
                .font(.caption)
            Stepper("Off for  \(Int(m.state.cycleOffMin))m", value: offBinding, in: 1...240)
                .font(.caption)
        }
        .padding(12)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 16))
    }

    private var onBinding: Binding<Double> {
        Binding(get: { m.state.cycleOnMin }, set: { m.state.cycleOnMin = $0; m.setCycleOn(Int($0)) })
    }
    private var offBinding: Binding<Double> {
        Binding(get: { m.state.cycleOffMin }, set: { m.state.cycleOffMin = $0; m.setCycleOff(Int($0)) })
    }
}

/// A once-per-second live countdown to the next cycle phase switch.
struct CountdownText: View {
    let until: String?

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            Text("in " + remaining(context.date))
                .font(.caption).foregroundStyle(.secondary).monospacedDigit()
        }
    }

    private func remaining(_ now: Date) -> String {
        guard let until, let d = parseLocal(until) else { return "—" }
        let secs = max(0, Int(d.timeIntervalSince(now)))
        let m = secs / 60, s = secs % 60
        return m > 0 ? String(format: "%d:%02d", m, s) : "\(s)s"
    }
}
