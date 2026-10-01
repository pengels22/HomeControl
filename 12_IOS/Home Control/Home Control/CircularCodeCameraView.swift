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
    private var previewLayer: AVCaptureVideoPreviewLayer?
    private var didScan = false
    private var lastAttempt = Date.distantPast

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        configureSession()
        addGuideLabel()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        previewLayer?.frame = view.bounds
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
        videoOutput.setSampleBufferDelegate(self, queue: DispatchQueue(label: "homecontrol.circular-code.scan"))
        session.addOutput(videoOutput)

        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspectFill
        view.layer.addSublayer(layer)
        previewLayer = layer
    }

    private func addGuideLabel() {
        let label = UILabel()
        label.text = "Center the circular HCM code"
        label.textColor = .black
        label.textAlignment = .center
        label.backgroundColor = .white
        label.layer.cornerRadius = 18
        label.layer.masksToBounds = true
        label.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(label)

        NSLayoutConstraint.activate([
            label.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            label.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -24),
            label.heightAnchor.constraint(equalToConstant: 40),
            label.widthAnchor.constraint(greaterThanOrEqualToConstant: 240)
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

        do {
            _ = try CircularGlyphImageDecoder.decode(cgImage: cgImage)
            didScan = true
            let image = UIImage(cgImage: cgImage)
            DispatchQueue.main.async {
                self.session.stopRunning()
                self.onImage?(image)
            }
        } catch {
            return
        }
    }
}
