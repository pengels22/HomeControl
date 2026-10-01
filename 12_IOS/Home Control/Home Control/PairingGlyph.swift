//
//  PairingGlyph.swift
//  Home Control
//

import Foundation

struct PairingGlyph: Decodable {
    let format: String
    let payload: String
    let code: String
    let size: Int
    let matrix: [String]
}

struct PairingPayload: Equatable {
    let protocolVersion: String
    let opaqueToken: String
}

enum HomeControlCircularPairingCodeSpec {
    static let format = "HC-CIRCULAR-PAIR-1"
    static let protocolVersion = "HC2"
    static let matrixSize = 17
    static let center = 8
    static let radius = 8.2
    static let eyeCenters = [(x: 4, y: 4), (x: 12, y: 4), (x: 4, y: 12)]
    static let eyeHalfWidth = 1
    static let centeredPhotoCropScale = 0.72
    static let darkLumaThreshold = 140.0

    static func inCircle(_ x: Int, _ y: Int) -> Bool {
        let dx = Double(x - center)
        let dy = Double(y - center)
        return sqrt(dx * dx + dy * dy) <= radius
    }

    static func isEye(_ x: Int, _ y: Int) -> Bool {
        eyeCenters.contains { eye in
            abs(x - eye.x) <= eyeHalfWidth && abs(y - eye.y) <= eyeHalfWidth
        }
    }

    static func dataCells() -> [(Int, Int)] {
        var cells: [(Int, Int)] = []
        for y in 0..<matrixSize {
            for x in 0..<matrixSize where inCircle(x, y) && !isEye(x, y) {
                cells.append((x, y))
            }
        }
        return cells
    }
}

enum PairingGlyphError: Error, LocalizedError {
    case invalidFormat
    case invalidMatrix
    case incompletePayload
    case checksumMismatch
    case nonASCII

    var errorDescription: String? {
        switch self {
        case .invalidFormat:
            return "Unsupported pairing glyph format."
        case .invalidMatrix:
            return "The pairing glyph matrix is not valid."
        case .incompletePayload:
            return "The pairing glyph payload is incomplete."
        case .checksumMismatch:
            return "The pairing glyph checksum did not match."
        case .nonASCII:
            return "The pairing glyph contained non-ASCII data."
        }
    }
}

struct PairingGlyphCodec {
    static let format = HomeControlCircularPairingCodeSpec.format
    static let size = HomeControlCircularPairingCodeSpec.matrixSize

    static func decode(glyph: PairingGlyph) throws -> PairingPayload {
        guard glyph.format == format else { throw PairingGlyphError.invalidFormat }
        let payload = try decode(matrix: glyph.matrix)
        return try parse(payload: payload)
    }

    static func parse(payload: String) throws -> PairingPayload {
        guard payload.hasPrefix("\(HomeControlCircularPairingCodeSpec.protocolVersion):") else {
            throw PairingGlyphError.invalidFormat
        }
        let token = String(payload.dropFirst(HomeControlCircularPairingCodeSpec.protocolVersion.count + 1))
        guard !token.isEmpty,
              token.allSatisfy({ $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" }) else {
            throw PairingGlyphError.invalidFormat
        }
        return PairingPayload(
            protocolVersion: HomeControlCircularPairingCodeSpec.protocolVersion,
            opaqueToken: payload
        )
    }

    static func decode(matrix: [String]) throws -> String {
        guard matrix.count == size, matrix.allSatisfy({ $0.count == size }) else {
            throw PairingGlyphError.invalidMatrix
        }

        let cells = dataCells()
        let bits = cells.map { x, y -> UInt8 in
            let value = matrix[y][matrix[y].index(matrix[y].startIndex, offsetBy: x)]
            return value == "1" || value == "E" ? 1 : 0
        }
        let raw = bytes(from: bits)
        guard let length = raw.first else { throw PairingGlyphError.incompletePayload }

        let bodyEnd = 1 + Int(length)
        guard raw.count >= bodyEnd + 4 else { throw PairingGlyphError.incompletePayload }
        let body = Array(raw[1..<bodyEnd])
        let checksum = Array(raw[bodyEnd..<(bodyEnd + 4)])
        guard crc32(body).bigEndianBytes == checksum else { throw PairingGlyphError.checksumMismatch }
        guard let payload = String(bytes: body, encoding: .ascii) else { throw PairingGlyphError.nonASCII }
        return payload
    }

    private static func dataCells() -> [(Int, Int)] {
        HomeControlCircularPairingCodeSpec.dataCells()
    }

    private static func bytes(from bits: [UInt8]) -> [UInt8] {
        stride(from: 0, to: bits.count, by: 8).compactMap { index in
            guard index + 8 <= bits.count else { return nil }
            return bits[index..<(index + 8)].reduce(UInt8(0)) { ($0 << 1) | $1 }
        }
    }

    private static func crc32(_ bytes: [UInt8]) -> UInt32 {
        var crc: UInt32 = 0xffffffff
        for byte in bytes {
            crc ^= UInt32(byte)
            for _ in 0..<8 {
                crc = (crc & 1) == 1 ? (crc >> 1) ^ 0xedb88320 : crc >> 1
            }
        }
        return crc ^ 0xffffffff
    }
}

private extension UInt32 {
    var bigEndianBytes: [UInt8] {
        [
            UInt8((self >> 24) & 0xff),
            UInt8((self >> 16) & 0xff),
            UInt8((self >> 8) & 0xff),
            UInt8(self & 0xff)
        ]
    }
}
