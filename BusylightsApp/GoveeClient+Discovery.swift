import Foundation

// This file provides a discovery stub so calls to `GoveeClient.discoverDevices()` compile.
// Replace the placeholder implementation with real discovery logic as needed.
extension GoveeClient {
    /// Discover Govee devices on the local network.
    /// - Returns: An array of BusylightsConfig.Device entries representing discovered devices.
    ///
    /// NOTE: This is a placeholder implementation that returns an empty list.
    /// Implement actual discovery (mDNS/UDP broadcast/API) and map results into BusylightsConfig.Device.
    static func discoverDevices() -> [BusylightsConfig.Device] {
        // TODO: Implement real discovery.
        // Example of how to construct a device if you have details at runtime:
        // let device = BusylightsConfig.Device(sku: "H6002", ip: "192.168.1.50", fingerprint: "unique-id-123", enabled: true)
        // return [device]
        return []
    }
}
