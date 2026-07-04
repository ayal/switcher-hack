import SwiftUI

/// The AC state as served by the local backend (GET /api/state). Tolerant of
/// missing/null fields so a partially-populated data.json never breaks decoding.
struct ACState: Decodable {
    var mode = "manual"
    var isOn = false
    var temperature: Double? = nil
    var acTemp: Double? = nil
    var coolTemp = 26.0
    var tooHot = 27.0
    var tooCold = 26.0
    var cycleOnMin = 5.0
    var cycleOffMin = 25.0
    var cyclePhase = ""
    var cyclePhaseUntil: String? = nil

    enum CodingKeys: String, CodingKey {
        case mode, temperature
        case isOn = "is_on"
        case acTemp = "ac_temp"
        case coolTemp = "cool_temp"
        case tooHot = "too_hot_temp"
        case tooCold = "too_cold_temp"
        case cycleOnMin = "cycle_on_min"
        case cycleOffMin = "cycle_off_min"
        case cyclePhase = "cycle_phase"
        case cyclePhaseUntil = "cycle_phase_until"
    }

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        mode = try c.decodeIfPresent(String.self, forKey: .mode) ?? "manual"
        isOn = try c.decodeIfPresent(Bool.self, forKey: .isOn) ?? false
        temperature = try c.decodeIfPresent(Double.self, forKey: .temperature)
        acTemp = try c.decodeIfPresent(Double.self, forKey: .acTemp)
        coolTemp = try c.decodeIfPresent(Double.self, forKey: .coolTemp) ?? 26
        tooHot = try c.decodeIfPresent(Double.self, forKey: .tooHot) ?? 27
        tooCold = try c.decodeIfPresent(Double.self, forKey: .tooCold) ?? 26
        cycleOnMin = try c.decodeIfPresent(Double.self, forKey: .cycleOnMin) ?? 5
        cycleOffMin = try c.decodeIfPresent(Double.self, forKey: .cycleOffMin) ?? 25
        cyclePhase = try c.decodeIfPresent(String.self, forKey: .cyclePhase) ?? ""
        cyclePhaseUntil = try c.decodeIfPresent(String.self, forKey: .cyclePhaseUntil)
    }
}

/// Thin client of the local server. Polls state continuously (so the menu-bar
/// title stays live even when the popover is closed) and sends changes through
/// the same API the web dashboard uses, so the two stay in sync.
@MainActor
final class ACModel: ObservableObject {
    @Published var state = ACState()
    @Published var online = false

    /// Set while the user is dragging the target slider, so a background refresh
    /// doesn't yank the knob mid-drag.
    var editingTarget = false

    private let base = URL(string: "http://127.0.0.1:3001")!

    init() {
        start()
    }

    var menuTitle: String {
        guard online, let t = state.temperature else { return "AC" }
        return String(format: "%.1f°", t)
    }

    func start() {
        Task { @MainActor in
            while !Task.isCancelled {
                await refresh()
                try? await Task.sleep(nanoseconds: 5_000_000_000)
            }
        }
    }

    func refresh() async {
        do {
            let (data, _) = try await URLSession.shared.data(from: base.appending(path: "api/state"))
            var next = try JSONDecoder().decode(ACState.self, from: data)
            if editingTarget { next.coolTemp = state.coolTemp }  // don't fight the drag
            state = next
            online = true
        } catch {
            online = false
        }
    }

    // MARK: - intents

    func setMode(_ m: String) {
        state.mode = m
        postConfig(["mode": m])
    }

    func setCool(_ t: Int) {
        state.coolTemp = Double(t)
        postConfig(["cool_temp": t])
        if state.isOn { control("on", temp: t) }  // apply now if it's running
    }

    func setCycleOn(_ m: Int) { postConfig(["cycle_on_min": m]) }
    func setCycleOff(_ m: Int) { postConfig(["cycle_off_min": m]) }

    func togglePower() {
        if state.isOn {
            control("off")
        } else {
            control("on", temp: Int(state.coolTemp.rounded()))
        }
    }

    // MARK: - networking

    private func postConfig(_ patch: [String: Any]) {
        var req = URLRequest(url: base.appending(path: "api/config"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: patch)
        Task { @MainActor in
            _ = try? await URLSession.shared.data(for: req)
            await refresh()
        }
    }

    private func control(_ action: String, temp: Int? = nil) {
        var comps = URLComponents(url: base.appending(path: "control/\(action)"),
                                  resolvingAgainstBaseURL: false)!
        if let temp {
            comps.queryItems = [
                .init(name: "temp", value: "\(temp)"),
                .init(name: "fan", value: "low"),
                .init(name: "mode", value: "cool"),
            ]
        }
        let url = comps.url!
        Task { @MainActor in
            _ = try? await URLSession.shared.data(from: url)
            try? await Task.sleep(nanoseconds: 1_300_000_000)
            await refresh()
        }
    }
}
