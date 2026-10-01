//
//  CircularCodeCameraView.swift
//  Home Control
//

import AVFoundation
import CoreImage
import SwiftUI
import UIKit

struct CircularCodeCameraView: UIViewControllerRepresentable {
    let onImage: (UIImage) -> Void

    func makeUIViewController(context: Context) -> CircularCodeCameraViewController {
        let controller = CircularCodeCameraViewController()
        controller.onImage = onImage
        return controller
    }

    func updateUIViewController(_ uiViewController: CircularCodeCameraViewController, context: Context) {}
}

final class CircularCodeCameraViewController: UIViewController, AVCaptureVideoDataOutputSampleBufferDelegate {
    var onImage: ((UIImage) -> Void)?

    private let session = AVCaptureSession()
    private let videoOutput = AVCaptureVideoDataOutput()
    private let ciContext = CIContext()
    private let scanQueue = DispatchQueue(label: "homecontrol.circular-code.scan")
    private var previewLayer: AVCaptureVideoPreviewLayer?
    private var guideOverlay: CircularCodeGuideOverlay?
    private var latestFrame: CGImage?
    private var didScan = false
    private var lastAttempt = Date.distantPast
    private var lastStatusUpdate = Date.distantPast
    private var attemptCount = 0

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        configureSession()
        addGuideOverlay()
        addScanButton()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        previewLayer?.frame = view.bounds
        guideOverlay?.frame = view.bounds
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        if !session.isRunning {
            DispatchQueue.global(qos: .userInitiated).async { self.session.startRunning() }
        }
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        if session.isRunning {
            DispatchQueue.global(qos: .userInitiated).async { self.session.stopRunning() }
        }
    }

    private func configureSession() {
        session.sessionPreset = .hd1280x720
        guard let device = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device),
              session.canAddInput(input),
              session.canAddOutput(videoOutput) else {
            showMessage("Camera is not available. Use Load Simulator when running in the iOS Simulator.")
            return
        }
        session.addInput(input)
        videoOutput.alwaysDiscardsLateVideoFrames = true
        videoOutput.videoSettings = [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
        ]
        videoOutput.setSampleBufferDelegate(self, queue: scanQueue)
        session.addOutput(videoOutput)

        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspectFill
        view.layer.addSublayer(layer)
        previewLayer = layer
    }

    private func addGuideOverlay() {
        let overlay = CircularCodeGuideOverlay()
        overlay.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(overlay)
        guideOverlay = overlay

        NSLayoutConstraint.activate([
            overlay.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            overlay.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            overlay.topAnchor.constraint(equalTo: view.topAnchor),
            overlay.bottomAnchor.constraint(equalTo: view.bottomAnchor)
        ])
    }

    private func addScanButton() {
        let button = UIButton(type: .system)
        button.setTitle("Scan Now", for: .normal)
        button.setTitleColor(.black, for: .normal)
        button.titleLabel?.font = .preferredFont(forTextStyle: .headline)
        button.backgroundColor = .white
        button.layer.cornerRadius = 22
        button.translatesAutoresizingMaskIntoConstraints = false
        button.addTarget(self, action: #selector(scanCurrentFrame), for: .touchUpInside)
        view.addSubview(button)

        NSLayoutConstraint.activate([
            button.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            button.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -28),
            button.heightAnchor.constraint(equalToConstant: 44),
            button.widthAnchor.constraint(greaterThanOrEqualToConstant: 150)
        ])
    }

    private func showMessage(_ message: String) {
        let label = UILabel()
        label.text = message
        label.textColor = .white
        label.textAlignment = .center
        label.numberOfLines = 0
        label.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(label)

        NSLayoutConstraint.activate([
            label.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 24),
            label.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -24),
            label.centerYAnchor.constraint(equalTo: view.centerYAnchor)
        ])
    }

    @objc private func scanCurrentFrame() {
        guideOverlay?.setManualScanStarted()
        scanQueue.async {
            guard let frame = self.latestFrame else {
                DispatchQueue.main.async {
                    self.guideOverlay?.setNoFrame()
                }
                return
            }

            if !self.tryDecode(cgImage: frame) {
                DispatchQueue.main.async {
                    self.guideOverlay?.setScanFailed()
                }
            }
        }
    }

    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        guard !didScan,
              Date().timeIntervalSince(lastAttempt) > 0.18,
              let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else {
            return
        }
        lastAttempt = Date()

        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)
        guard let cgImage = ciContext.createCGImage(ciImage, from: ciImage.extent) else { return }
        latestFrame = cgImage
        attemptCount += 1

        if Date().timeIntervalSince(lastStatusUpdate) > 0.8 {
            let attempts = attemptCount
            lastStatusUpdate = Date()
            DispatchQueue.main.async {
                self.guideOverlay?.setScanning(attempts: attempts)
            }
        }

        _ = tryDecode(cgImage: cgImage)
    }

    private func tryDecode(cgImage: CGImage) -> Bool {
        guard !didScan else { return true }
        do {
            _ = try CircularGlyphImageDecoder.decode(cgImage: cgImage)
            didScan = true
            let image = UIImage(cgImage: cgImage)
            DispatchQueue.main.async {
                self.guideOverlay?.setScanningComplete()
                self.session.stopRunning()
                self.onImage?(image)
            }
            return true
        } catch {
            return false
        }
    }
}

final class CircularCodeGuideOverlay: UIView {
    private let instructionLabel = UILabel()
    private let detailLabel = UILabel()

    override init(frame: CGRect) {
        super.init(frame: frame)
        isUserInteractionEnabled = false
        backgroundColor = .clear
        setupLabels()
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
        isUserInteractionEnabled = false
        backgroundColor = .clear
        setupLabels()
    }

    override func draw(_ rect: CGRect) {
        guard let context = UIGraphicsGetCurrentContext() else { return }

        let side = min(bounds.width, bounds.height) * 0.66
        let center = CGPoint(x: bounds.midX, y: bounds.midY - 18)
        let guideRect = CGRect(x: center.x - side / 2, y: center.y - side / 2, width: side, height: side)

        context.setFillColor(UIColor.black.withAlphaComponent(0.34).cgColor)
        context.fill(bounds)
        context.setBlendMode(.clear)
        context.fillEllipse(in: guideRect.insetBy(dx: -8, dy: -8))
        context.setBlendMode(.normal)

        let ring = UIBezierPath(ovalIn: guideRect)
        UIColor.white.withAlphaComponent(0.95).setStroke()
        ring.lineWidth = 3
        ring.stroke()

        let innerRing = UIBezierPath(ovalIn: guideRect.insetBy(dx: side * 0.12, dy: side * 0.12))
        UIColor.systemGreen.withAlphaComponent(0.78).setStroke()
        innerRing.lineWidth = 1.5
        innerRing.stroke()

        drawTick(from: CGPoint(x: guideRect.midX, y: guideRect.minY - 22), to: CGPoint(x: guideRect.midX, y: guideRect.minY + 18))
        drawTick(from: CGPoint(x: guideRect.midX, y: guideRect.maxY + 22), to: CGPoint(x: guideRect.midX, y: guideRect.maxY - 18))
        drawTick(from: CGPoint(x: guideRect.minX - 22, y: guideRect.midY), to: CGPoint(x: guideRect.minX + 18, y: guideRect.midY))
        drawTick(from: CGPoint(x: guideRect.maxX + 22, y: guideRect.midY), to: CGPoint(x: guideRect.maxX - 18, y: guideRect.midY))
    }

    func setScanningComplete() {
        instructionLabel.text = "Code found"
        detailLabel.text = "Opening HCM"
    }

    func setScanning(attempts: Int) {
        instructionLabel.text = "Scanning circular code"
        detailLabel.text = "Trying frame \(attempts). Fill the ring and hold steady."
    }

    func setManualScanStarted() {
        instructionLabel.text = "Scanning current frame"
        detailLabel.text = "Hold steady"
    }

    func setScanFailed() {
        instructionLabel.text = "Still searching"
        detailLabel.text = "Move closer until the white circle fills the ring"
    }

    func setNoFrame() {
        instructionLabel.text = "Waiting for camera"
        detailLabel.text = "Point at the HCM code"
    }

    private func setupLabels() {
        instructionLabel.text = "Align circular HCM code"
        instructionLabel.textColor = .white
        instructionLabel.font = .preferredFont(forTextStyle: .headline)
        instructionLabel.textAlignment = .center

        detailLabel.text = "Fill the ring and hold steady"
        detailLabel.textColor = UIColor.white.withAlphaComponent(0.82)
        detailLabel.font = .preferredFont(forTextStyle: .subheadline)
        detailLabel.textAlignment = .center

        let stack = UIStackView(arrangedSubviews: [instructionLabel, detailLabel])
        stack.axis = .vertical
        stack.spacing = 4
        stack.alignment = .center
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)

        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(greaterThanOrEqualTo: leadingAnchor, constant: 24),
            stack.trailingAnchor.constraint(lessThanOrEqualTo: trailingAnchor, constant: -24),
            stack.centerXAnchor.constraint(equalTo: centerXAnchor),
            stack.bottomAnchor.constraint(equalTo: safeAreaLayoutGuide.bottomAnchor, constant: -88)
        ])
    }

    private func drawTick(from start: CGPoint, to end: CGPoint) {
        let path = UIBezierPath()
        path.move(to: start)
        path.addLine(to: end)
        UIColor.white.withAlphaComponent(0.9).setStroke()
        path.lineWidth = 3
        path.lineCapStyle = .round
        path.stroke()
    }
}
