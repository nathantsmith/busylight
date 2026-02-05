// swift-tools-version:6.0
import PackageDescription

let package = Package(
    name: "BusylightsApp",
    platforms: [
        .macOS(.v13)
    ],
    targets: [
        .executableTarget(
            name: "BusylightsApp",
            path: ".",
            exclude: [
                "GoveeClientDiscoveryTests.swift",
                "GoveeClientTests.swift",
                "BusylightsAppTests.swift"
            ]
        ),
        .testTarget(
            name: "BusylightsAppTests",
            dependencies: [
                "BusylightsApp",
                .product(name: "Testing", package: "swift-tools-support-core") // but per instructions, no external dependencies, so just import Testing
            ],
            path: ".",
            sources: [
                "GoveeClientDiscoveryTests.swift",
                "GoveeClientTests.swift",
                "BusylightsAppTests.swift"
            ]
        )
    ]
)
