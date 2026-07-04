// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "SwitcherAC",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(name: "SwitcherAC")
    ]
)
