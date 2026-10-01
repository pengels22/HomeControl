//
//  CircularGlyphImageDecoder.swift
//  Home Control
//

import CoreGraphics
import UIKit

enum CircularGlyphImageDecoder {
    static func decode(image: UIImage) throws -> PairingPayload {
        guard let cgImage = image.cgImage else { throw PairingGlyphError.invalidMatrix }

        let size = HomeControlCircularPairingCodeSpec.matrixSize
        let width = cgImage.width
        let height = cgImage.height
        let side = Int(Double(min(width, height)) * HomeControlCircularPairingCodeSpec.centeredPhotoCropScale)
        let originX = (width - side) / 2
        let originY = (height - side) / 2
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
                let isDark = luma(atX: sampleX, y: sampleY, in: cgImage) < HomeControlCircularPairingCodeSpec.darkLumaThreshold
                row.append(isDark ? "1" : "0")
            }
            rows.append(row)
        }

        let payload = try PairingGlyphCodec.decode(matrix: rows)
        return try PairingGlyphCodec.parse(payload: payload)
    }

    private static func luma(atX x: Int, y: Int, in image: CGImage) -> Double {
        guard let dataProvider = image.dataProvider,
              let data = dataProvider.data,
              let bytes = CFDataGetBytePtr(data) else {
            return 255
        }
        let clampedX = max(0, min(image.width - 1, x))
        let clampedY = max(0, min(image.height - 1, y))
        let offset = clampedY * image.bytesPerRow + clampedX * max(1, image.bitsPerPixel / 8)
        let r = Double(bytes[offset])
        let g = Double(bytes[offset + 1])
        let b = Double(bytes[offset + 2])
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    }
}
