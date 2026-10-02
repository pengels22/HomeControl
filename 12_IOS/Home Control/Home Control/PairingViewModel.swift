//
//  PairingViewModel.swift
//  Home Control
//

import Foundation

@Observable
final class PairingViewModel {
    var simulatorURL = "http://192.168.20.50:8088"
    var glyph: PairingGlyph?
    var payload: PairingPayload?
    var errorMessage: String?
    var isLoading = false

    func loadSimulatorGlyph() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            guard let url = URL(string: simulatorURL + "/api/pairing-glyph") else {
                throw URLError(.badURL)
            }
            let (data, response) = try await URLSession.shared.data(from: url)
            guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
                throw URLError(.badServerResponse)
            }
            let decodedGlyph = try JSONDecoder().decode(PairingGlyph.self, from: data)
            glyph = decodedGlyph
            payload = try PairingGlyphCodec.decode(glyph: decodedGlyph)
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
