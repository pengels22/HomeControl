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
        var lastError: Error = PairingGlyphError.invalidMatrix
        for image in imageOrientations(cgImage) {
            do {
                return try decodeSingleOrientation(cgImage: image)
            } catch {
                lastError = error
            }
        }
        throw lastError
    }

    private static func decodeSingleOrientation(cgImage: CGImage) throws -> PairingPayload {
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
        for crop in candidateCrops(from: sampler) {
            for threshold in thresholds {
                let matrix = sampleMatrix(from: sampler, crop: crop, threshold: threshold)
                for orientedMatrix in matrixOrientations(matrix) {
                    do {
                        let payload = try PairingGlyphCodec.decode(matrix: orientedMatrix)
                        return try PairingGlyphCodec.parse(payload: payload)
                    } catch {
                        lastError = error
                    }
                }
            }
        }
        throw lastError
    }

    private static func candidateCrops(from sampler: PixelSampler) -> [CGRect] {
        var crops: [CGRect] = []
        if let detected = brightCodeCrop(from: sampler) {
            crops.append(detected)
            crops.append(detected.insetBy(dx: -detected.width * 0.06, dy: -detected.height * 0.06))
            crops.append(detected.insetBy(dx: detected.width * 0.05, dy: detected.height * 0.05))
        }

        for scale in [0.36, 0.42, 0.48, 0.56, 0.64, HomeControlCircularPairingCodeSpec.centeredPhotoCropScale, 0.80, 0.92] {
            let side = Double(min(sampler.width, sampler.height)) * scale
            for offsetY in [-0.12, -0.06, 0.0, 0.06, 0.12] {
                for offsetX in [-0.08, 0.0, 0.08] {
                    crops.append(CGRect(
                        x: (Double(sampler.width) - side) / 2 + Double(sampler.width) * offsetX,
                        y: (Double(sampler.height) - side) / 2 + Double(sampler.height) * offsetY,
                        width: side,
                        height: side
                    ))
                }
            }
        }

        return crops.map { clampSquare($0, width: sampler.width, height: sampler.height) }
    }

    private static func brightCodeCrop(from sampler: PixelSampler) -> CGRect? {
        let step = max(3, min(sampler.width, sampler.height) / 180)
        let marginX = sampler.width / 10
        let marginY = sampler.height / 10
        var minX = sampler.width
        var minY = sampler.height
        var maxX = 0
        var maxY = 0
        var hits = 0

        for y in stride(from: marginY, to: sampler.height - marginY, by: step) {
            for x in stride(from: marginX, to: sampler.width - marginX, by: step) {
                guard sampler.luma(atX: x, y: y) > 215 else { continue }
                minX = min(minX, x)
                minY = min(minY, y)
                maxX = max(maxX, x)
                maxY = max(maxY, y)
                hits += 1
            }
        }

        guard hits > 24, maxX > minX, maxY > minY else { return nil }
        let centerX = Double(minX + maxX) / 2
        let centerY = Double(minY + maxY) / 2
        let side = Double(max(maxX - minX, maxY - minY)) * 1.12
        return CGRect(x: centerX - side / 2, y: centerY - side / 2, width: side, height: side)
    }

    private static func clampSquare(_ rect: CGRect, width: Int, height: Int) -> CGRect {
        let side = min(rect.width, rect.height, Double(width), Double(height))
        let x = min(max(rect.midX - side / 2, 0), Double(width) - side)
        let y = min(max(rect.midY - side / 2, 0), Double(height) - side)
        return CGRect(x: x, y: y, width: side, height: side)
    }

    private static func sampleMatrix(from sampler: PixelSampler, crop: CGRect, threshold: Double) -> [String] {
        let size = HomeControlCircularPairingCodeSpec.matrixSize
        let cell = crop.width / Double(size)

        var rows: [String] = []
        for y in 0..<size {
            var row = ""
            for x in 0..<size {
                if !HomeControlCircularPairingCodeSpec.inCircle(x, y) {
                    row.append(" ")
                    continue
                }
                let sampleX = Int(crop.minX + (Double(x) + 0.5) * cell)
                let sampleY = Int(crop.minY + (Double(y) + 0.5) * cell)
                let isDark = sampler.luma(atX: sampleX, y: sampleY) < threshold
                row.append(isDark ? "1" : "0")
            }
            rows.append(row)
        }
        return rows
    }

    private static func matrixOrientations(_ matrix: [String]) -> [[String]] {
        let once = rotateClockwise(matrix)
        let twice = rotateClockwise(once)
        let third = rotateClockwise(twice)
        return [matrix, once, twice, third]
    }

    private static func rotateClockwise(_ matrix: [String]) -> [String] {
        let rows = matrix.map(Array.init)
        let size = rows.count
        guard size > 0 else { return matrix }
        return (0..<size).map { x in
            String((0..<size).reversed().map { y in rows[y][x] })
        }
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

    private static func imageOrientations(_ image: CGImage) -> [CGImage] {
        var images = [image]
        var current = image
        for _ in 0..<3 {
            guard let rotated = rotateImageClockwise(current) else { break }
            images.append(rotated)
            current = rotated
        }
        return images
    }

    private static func rotateImageClockwise(_ image: CGImage) -> CGImage? {
        let width = image.width
        let height = image.height
        let bytesPerPixel = 4
        let bytesPerRow = height * bytesPerPixel
        var buffer = [UInt8](repeating: 255, count: width * bytesPerRow)
        let colorSpace = CGColorSpaceCreateDeviceRGB()
        guard let context = CGContext(
            data: &buffer,
            width: height,
            height: width,
            bitsPerComponent: 8,
            bytesPerRow: bytesPerRow,
            space: colorSpace,
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ) else {
            return nil
        }
        context.translateBy(x: CGFloat(height), y: 0)
        context.rotate(by: .pi / 2)
        context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
        return context.makeImage()
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
