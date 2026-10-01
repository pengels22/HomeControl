//
//  CircularGlyphImageDecoder.swift
//  Home Control
//

import CoreGraphics
import UIKit

enum CircularGlyphImageDecoder {
    static func decode(image: UIImage) throws -> PairingPayload {
        guard let cgImage = normalizedCGImage(from: image) else { throw PairingGlyphError.invalidMatrix }
        return try decode(cgImage: cgImage)
    }

    static func decode(cgImage: CGImage) throws -> PairingPayload {
        let cropScales = [
            HomeControlCircularPairingCodeSpec.centeredPhotoCropScale,
            0.62,
            0.68,
            0.76,
            0.84,
            0.92
        ]
        let thresholds = [
            HomeControlCircularPairingCodeSpec.darkLumaThreshold,
            110.0,
            125.0,
            155.0,
            175.0,
            195.0
        ]

        var lastError: Error = PairingGlyphError.invalidMatrix
        let sampler = try PixelSampler(cgImage: cgImage)
        for cropScale in cropScales {
            for threshold in thresholds {
                do {
                    let matrix = sampleMatrix(from: sampler, cropScale: cropScale, threshold: threshold)
                    let payload = try PairingGlyphCodec.decode(matrix: matrix)
                    return try PairingGlyphCodec.parse(payload: payload)
                } catch {
                    lastError = error
                }
            }
        }
        throw lastError
    }

    private static func sampleMatrix(from sampler: PixelSampler, cropScale: Double, threshold: Double) -> [String] {
        let size = HomeControlCircularPairingCodeSpec.matrixSize
        let side = Int(Double(min(sampler.width, sampler.height)) * cropScale)
        let originX = (sampler.width - side) / 2
        let originY = (sampler.height - side) / 2
        let cell = Double(side) / Double(size)

        var rows: [String] = []
        for y in 0..<size {
            var row = ""
            for x in 0..<size {
                if !HomeControlCircularPairingCodeSpec.inCircle(x, y) {
                    row.append(" ")
                    continue
                }
                let sampleX = originX + Int((Double(x) + 0.5) * cell)
                let sampleY = originY + Int((Double(y) + 0.5) * cell)
                let isDark = sampler.luma(atX: sampleX, y: sampleY) < threshold
                row.append(isDark ? "1" : "0")
            }
            rows.append(row)
        }
        return rows
    }

    private static func normalizedCGImage(from image: UIImage) -> CGImage? {
        if image.imageOrientation == .up, let cgImage = image.cgImage {
            return cgImage
        }
        let renderer = UIGraphicsImageRenderer(size: image.size)
        let normalized = renderer.image { _ in
            image.draw(in: CGRect(origin: .zero, size: image.size))
        }
        return normalized.cgImage
    }
}

private struct PixelSampler {
    let width: Int
    let height: Int
    private let bytes: [UInt8]
    private let bytesPerPixel = 4

    init(cgImage: CGImage) throws {
        width = cgImage.width
        height = cgImage.height
        let bytesPerRow = width * bytesPerPixel
        var buffer = [UInt8](repeating: 255, count: height * bytesPerRow)
        let colorSpace = CGColorSpaceCreateDeviceRGB()
        guard let context = CGContext(
            data: &buffer,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: bytesPerRow,
            space: colorSpace,
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ) else {
            throw PairingGlyphError.invalidMatrix
        }
        context.draw(cgImage, in: CGRect(x: 0, y: 0, width: width, height: height))
        bytes = buffer
    }

    func luma(atX x: Int, y: Int) -> Double {
        let clampedX = max(0, min(width - 1, x))
        let clampedY = max(0, min(height - 1, y))
        let offset = (clampedY * width + clampedX) * bytesPerPixel
        let r = Double(bytes[offset])
        let g = Double(bytes[offset + 1])
        let b = Double(bytes[offset + 2])
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    }
}
