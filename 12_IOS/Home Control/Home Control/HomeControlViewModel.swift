//
//  HomeControlViewModel.swift
//  Home Control
//

import Foundation
import UIKit

@Observable
final class HomeControlViewModel {
    var hcmURL = "http://100.71.53.54:8088"
    var authToken = ""
    var username = ""
    var password = ""
    var session: AuthSession?
    var simulatorState: SimulatorState?
    var selectedTarget: ScannedTarget?
    var errorMessage: String?
    var isLoading = false
    var needsSignIn = false
    var circularCompareOK: Bool?
    private var pendingCircularPayload: String?

    var devices: [HCMDevice] {
        simulatorState?.devices ?? []
    }

    var selectedDevice: HCMDevice? {
        guard let selectedTarget else { return nil }
        return devices.first { $0.id.caseInsensitiveCompare(selectedTarget.targetId) == .orderedSame }
    }

    func scan(rawCode: String) async {
        if let payload = try? PairingGlyphCodec.securePayload(from: rawCode) {
            await captureCircularPayload(payload)
            return
        }

        selectedTarget = ScannedCodeParser.parse(rawCode)
        circularCompareOK = nil
        await openSelectedTarget()
    }

    func captureCircularCode(image: UIImage) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            let decoded = try CircularGlyphImageDecoder.decode(image: image)
            try await completeCircularPairing(payload: decoded.opaqueToken)
        } catch HCMClientError.unauthorized {
            needsSignIn = true
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func captureCircularPayload(_ payload: String) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            let decoded = try PairingGlyphCodec.parse(payload: payload)
            try await completeCircularPairing(payload: decoded.opaqueToken)
        } catch HCMClientError.unauthorized {
            needsSignIn = true
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func loadSimulatorPairingGlyph() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            let glyph: PairingGlyph = try await client(includeToken: false).requestPublic("/api/pairing-glyph")
            let payload = try PairingGlyphCodec.decode(glyph: glyph)
            circularCompareOK = nil
            selectedTarget = ScannedTarget(
                rawValue: glyph.payload,
                hcmId: nil,
                targetId: "HCM01",
                pairingCode: nil
            )
            pendingCircularPayload = payload.opaqueToken
            let comparison = try await client(includeToken: false).comparePairingPayload(payload.opaqueToken)
            circularCompareOK = comparison.ok
            if let token = comparison.token {
                authToken = token
                session = try await client().validateSession()
                simulatorState = try await client().simulatorState()
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func openSelectedTarget() async {
        guard selectedTarget != nil else { return }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            try await ensureSession()
            simulatorState = try await client().simulatorState()
        } catch HCMClientError.unauthorized {
            needsSignIn = true
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func signIn() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            let token = try await client(includeToken: false).login(username: username, password: password)
            authToken = token
            needsSignIn = false
            session = try await client().validateSession()
            if let pendingCircularPayload {
                let comparison = try await client(includeToken: false).comparePairingPayload(pendingCircularPayload)
                circularCompareOK = comparison.ok
                if let token = comparison.token {
                    authToken = token
                    session = try await client().validateSession()
                }
                self.pendingCircularPayload = comparison.ok ? nil : pendingCircularPayload
                if !comparison.ok {
                    errorMessage = "The circular code did not match the token on the HCM."
                    return
                }
            }
            simulatorState = try await client().simulatorState()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func useDevSession() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            struct DevSession: Decodable { let token: String }
            let dev: DevSession = try await client(includeToken: false).requestPublic("/api/v1/auth/dev-session", method: "POST")
            authToken = dev.token
            needsSignIn = false
            session = try await client().validateSession()
            if let pendingCircularPayload {
                let comparison = try await client(includeToken: false).comparePairingPayload(pendingCircularPayload)
                circularCompareOK = comparison.ok
                if let token = comparison.token {
                    authToken = token
                    session = try await client().validateSession()
                }
                self.pendingCircularPayload = comparison.ok ? nil : pendingCircularPayload
                if !comparison.ok {
                    errorMessage = "The circular code did not match the token on the HCM."
                    return
                }
            }
            simulatorState = try await client().simulatorState()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func refresh() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            try await ensureSession()
            simulatorState = try await client().simulatorState()
        } catch HCMClientError.unauthorized {
            needsSignIn = true
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func ensureSession() async throws {
        guard !authToken.isEmpty else {
            throw HCMClientError.unauthorized
        }
        session = try await client().validateSession()
    }

    private func completeCircularPairing(payload: String) async throws {
        pendingCircularPayload = payload
        selectedTarget = ScannedTarget(
            rawValue: payload,
            hcmId: nil,
            targetId: "HCM01",
            pairingCode: nil
        )
        let comparison = try await client(includeToken: false).comparePairingPayload(payload)
        circularCompareOK = comparison.ok
        if let token = comparison.token {
            authToken = token
            session = try await client().validateSession()
        }
        pendingCircularPayload = nil
        if !comparison.ok {
            errorMessage = "The circular code did not match the token on the HCM."
            return
        }
        simulatorState = try await client().simulatorState()
    }

    private func client(includeToken: Bool = true) throws -> HCMClient {
        guard let url = URL(string: hcmURL) else { throw HCMClientError.badURL }
        return HCMClient(baseURL: url, token: includeToken ? authToken : nil)
    }
}

private extension HCMClient {
    func requestPublic<T: Decodable>(_ path: String, method: String = "GET") async throws -> T {
        guard let url = URL(string: path, relativeTo: baseURL) else { throw HCMClientError.badURL }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if method != "GET" {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = Data()
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw HCMClientError.server(-1) }
        guard 200..<300 ~= http.statusCode else { throw HCMClientError.server(http.statusCode) }
        return try JSONDecoder().decode(T.self, from: data)
    }
}
