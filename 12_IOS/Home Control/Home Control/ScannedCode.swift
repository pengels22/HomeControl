//
//  ScannedCode.swift
//  Home Control
//

import Foundation

struct ScannedTarget: Equatable {
    let rawValue: String
    let hcmId: String?
    let targetId: String
    let pairingCode: String?

    var displayName: String {
        targetId
    }
}

enum ScannedCodeParser {
    static func parse(_ rawValue: String) -> ScannedTarget {
        let trimmed = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)

        if let data = trimmed.data(using: .utf8),
           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            let hcmId = json["hcm_id"] as? String ?? json["hcmId"] as? String
            let targetId = json["target_id"] as? String ?? json["targetId"] as? String ?? json["id"] as? String ?? trimmed
            let pairingCode = json["pairing_code"] as? String ?? json["pairingCode"] as? String ?? json["code"] as? String
            return ScannedTarget(rawValue: trimmed, hcmId: hcmId, targetId: targetId, pairingCode: pairingCode)
        }

        let parts = trimmed.split(separator: ":", omittingEmptySubsequences: false).map(String.init)
        if parts.count >= 3, parts[0] == "HC1" {
            let hcmId = parts[1]
            let pairingCode = parts[2]
            let targetId = parts.count >= 4 ? parts[3] : hcmId
            return ScannedTarget(rawValue: trimmed, hcmId: hcmId, targetId: targetId, pairingCode: pairingCode)
        }

        return ScannedTarget(rawValue: trimmed, hcmId: nil, targetId: trimmed, pairingCode: nil)
    }
}
