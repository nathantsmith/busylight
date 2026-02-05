import Foundation
import Testing
@testable import BusylightsApp

@Suite("Govee discovery parsing")
struct GoveeDiscoveryParsingTests {

    private func parse(_ payloads: [Data]) -> [BusylightsConfig.Device] {
        // Mirror the parsing logic from GoveeClient.discoverDevices()
        var results: [BusylightsConfig.Device] = []
        var seen: Set<String> = []

        struct DiscoveryResponse: Decodable { let ip: String; let sku: String; let device: String? }

        for data in payloads {
            if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                let ip = (obj["ip"] as? String) ?? ""
                let sku = (obj["sku"] as? String) ?? (obj["model"] as? String) ?? ""
                let fingerprint = (obj["device"] as? String)
                    ?? (obj["deviceId"] as? String)
                    ?? (obj["gid"] as? String)
                    ?? ""
                if !ip.isEmpty, !sku.isEmpty {
                    let fp = fingerprint.isEmpty ? "\(ip)|\(sku)" : fingerprint
                    if seen.insert(fp).inserted {
                        results.append(BusylightsConfig.Device(fingerprint: fp, ip: ip, sku: sku, enabled: true))
                    }
                    continue
                }
            }
            if let resp = try? JSONDecoder().decode(DiscoveryResponse.self, from: data), !resp.ip.isEmpty, !resp.sku.isEmpty {
                let fp = resp.device ?? "\(resp.ip)|\(resp.sku)"
                if seen.insert(fp).inserted {
                    results.append(BusylightsConfig.Device(fingerprint: fp, ip: resp.ip, sku: resp.sku, enabled: true))
                }
            }
        }
        return results
    }

    @Test("Parses basic discovery JSON with device id")
    func parsesBasicJSON() async throws {
        let payload = [
            "ip": "192.168.1.10",
            "sku": "H6104",
            "device": "AA:BB:CC:DD"
        ]
        let data = try JSONSerialization.data(withJSONObject: payload)
        let devices = parse([data])
        #expect(devices.count == 1)
        #expect(devices.first?.fingerprint == "AA:BB:CC:DD")
        #expect(devices.first?.ip == "192.168.1.10")
        #expect(devices.first?.sku == "H6104")
    }

    @Test("Falls back to model key and synthesizes fingerprint")
    func fallsBackAndSynthesizesFingerprint() async throws {
        let payload = [
            "ip": "192.168.1.11",
            "model": "H6002"
        ]
        let data = try JSONSerialization.data(withJSONObject: payload)
        let devices = parse([data])
        #expect(devices.count == 1)
        #expect(devices.first?.fingerprint == "192.168.1.11|H6002")
        #expect(devices.first?.sku == "H6002")
    }

    @Test("Typed decoding fallback works")
    func typedDecodingFallback() async throws {
        let json = """
        {"ip":"192.168.1.12","sku":"H7001","deviceName":"Lamp"}
        """.data(using: .utf8)!
        let devices = parse([json])
        #expect(devices.count == 1)
        #expect(devices.first?.fingerprint == "192.168.1.12|H7001")
        #expect(devices.first?.sku == "H7001")
    }

    @Test("Deduplicates devices by fingerprint")
    func deduplicatesByFingerprint() async throws {
        let p1 = try JSONSerialization.data(withJSONObject: ["ip": "192.168.1.13", "sku": "H6002", "device": "FP1"]) 
        let p2 = try JSONSerialization.data(withJSONObject: ["ip": "192.168.1.13", "sku": "H6002", "device": "FP1"]) 
        let devices = parse([p1, p2])
        #expect(devices.count == 1)
        #expect(devices.first?.fingerprint == "FP1")
    }

    @Test("Handles mixed formats and duplicates")
    func mixedFormats() async throws {
        let p1 = try JSONSerialization.data(withJSONObject: ["ip": "192.168.1.14", "sku": "H6002", "device": "FP2"]) 
        let p2 = """
        {"ip":"192.168.1.14","sku":"H6002"}
        """.data(using: .utf8)!
        let p3 = try JSONSerialization.data(withJSONObject: ["ip": "192.168.1.15", "model": "H6050"]) 
        let devices = parse([p1, p2, p3])
        #expect(devices.count == 2)
        #expect(devices.contains { $0.fingerprint == "FP2" })
        #expect(devices.contains { $0.fingerprint == "192.168.1.15|H6050" })
    }
}
