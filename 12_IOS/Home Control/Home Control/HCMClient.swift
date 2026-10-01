//
//  HCMClient.swift
//  Home Control
//

import Foundation

struct AuthSession: Decodable {
    let user: String
    let role: String
}

struct HCMDevice: Identifiable, Decodable, Equatable {
    let type: String
    let id: String
    let label: String
}

struct SimulatorState: Decodable {
    let devices: [HCMDevice]
    let hcm: HCMState
    let rcm: RCMState?
    let lcm: LCMState?
    let sim: SIMState?
    let pnl: PNLState?
}

struct HCMState: Decodable {
    let hvac: HVACState
    let pairing: PairingGlyph?
}

struct HVACState: Decodable {
    let mode: String
    let setpointF: Double
    let averageF: Double?
    let fan: Bool
    let heat: Bool
    let cool: Bool

    enum CodingKeys: String, CodingKey {
        case mode
        case setpointF = "setpoint_f"
        case averageF = "average_f"
        case fan
        case heat
        case cool
    }
}

struct RCMState: Decodable {
    let relays: [String: Bool]
    let locks: [String: Bool]?
    let names: [String: String]?
    let ioMode: String?

    enum CodingKeys: String, CodingKey {
        case relays
        case locks
        case names
        case ioMode = "io_mode"
    }
}

struct LCMState: Decodable {
    let relays: [String: Bool]
    let names: [String: String]?
    let hvDimmers: [String: DimmerState]
    let lvDimmers: [String: DimmerState]

    enum CodingKeys: String, CodingKey {
        case relays
        case names
        case hvDimmers = "hv_dimmers"
        case lvDimmers = "lv_dimmers"
    }
}

struct DimmerState: Decodable {
    let percent: Double
}

struct SIMState: Decodable {
    let rmcNodes: [String: RMCNode]

    enum CodingKeys: String, CodingKey {
        case rmcNodes = "rmc_nodes"
    }
}

struct RMCNode: Decodable {
    let temperatureF: Double?
    let humidityPct: Double?
    let lux: Double?
    let presence: Bool?

    enum CodingKeys: String, CodingKey {
        case temperatureF = "temperature_f"
        case humidityPct = "humidity_pct"
        case lux
        case presence
    }
}

struct PNLState: Decodable {
    let room: String?
    let dashboardURL: String?

    enum CodingKeys: String, CodingKey {
        case room
        case dashboardURL = "dashboard_url"
    }
}

struct PairingCompareResponse: Decodable {
    let ok: Bool
    let expectedHcm: String
    let token: String?

    enum CodingKeys: String, CodingKey {
        case ok
        case expectedHcm = "expected_hcm"
        case token
    }
}

enum HCMClientError: Error, LocalizedError {
    case unauthorized
    case badURL
    case server(Int)

    var errorDescription: String? {
        switch self {
        case .unauthorized:
            return "Sign in to the HCM before opening this configuration."
        case .badURL:
            return "The HCM URL is invalid."
        case .server(let status):
            return "HCM returned HTTP \(status)."
        }
    }
}

struct HCMClient {
    var baseURL: URL
    var token: String?

    func validateSession() async throws -> AuthSession {
        try await request("/api/v1/auth/session")
    }

    func login(username: String, password: String) async throws -> String {
        struct LoginBody: Encodable {
            let username: String
            let password: String
        }
        struct LoginResponse: Decodable {
            let token: String
        }
        let response: LoginResponse = try await request(
            "/api/v1/auth/login",
            method: "POST",
            body: LoginBody(username: username, password: password),
            includeToken: false
        )
        return response.token
    }

    func simulatorState() async throws -> SimulatorState {
        try await request("/api/state", includeToken: false)
    }

    func comparePairingPayload(_ payload: String) async throws -> PairingCompareResponse {
        struct CompareBody: Encodable {
            let payload: String
        }
        return try await request(
            "/api/pairing-glyph/compare",
            method: "POST",
            body: CompareBody(payload: payload)
        )
    }

    private func request<T: Decodable>(
        _ path: String,
        method: String = "GET",
        body: Encodable? = nil,
        includeToken: Bool = true
    ) async throws -> T {
        guard let url = URL(string: path, relativeTo: baseURL) else { throw HCMClientError.badURL }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if includeToken, let token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(AnyEncodable(body))
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw HCMClientError.server(-1) }
        if http.statusCode == 401 || http.statusCode == 403 { throw HCMClientError.unauthorized }
        guard 200..<300 ~= http.statusCode else { throw HCMClientError.server(http.statusCode) }
        return try JSONDecoder().decode(T.self, from: data)
    }
}

private struct AnyEncodable: Encodable {
    let value: Encodable

    init(_ value: Encodable) {
        self.value = value
    }

    func encode(to encoder: Encoder) throws {
        try value.encode(to: encoder)
    }
}
