//
//  ContentView.swift
//  Home Control
//

import SwiftUI

struct ContentView: View {
    @State private var model = HomeControlViewModel()
    @State private var showingScanner = false
    @State private var showingCircularCamera = false
    @State private var manualCode = ""

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    header
                    hcmConnection
                    scanActions

                    if let target = model.selectedTarget {
                        targetSummary(target)
                    }

                    if let state = model.simulatorState, let target = model.selectedTarget {
                        DeviceConfigView(target: target, device: model.selectedDevice, state: state)
                    }

                    if let error = model.errorMessage {
                        Text(error)
                            .foregroundStyle(.red)
                            .padding()
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
                    }
                }
                .padding()
            }
            .navigationTitle("Home Control")
            .toolbar {
                Button {
                    Task { await model.refresh() }
                } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
                .disabled(model.isLoading)
            }
            .sheet(isPresented: $showingScanner) {
                NavigationStack {
                    CodeScannerView { rawCode in
                        showingScanner = false
                        Task { await model.scan(rawCode: rawCode) }
                    }
                    .ignoresSafeArea()
                    .navigationTitle("Scan Code")
                    .toolbar {
                        Button("Cancel") { showingScanner = false }
                    }
                }
            }
            .sheet(isPresented: $showingCircularCamera) {
                NavigationStack {
                    CircularCodeCameraView { image in
                        showingCircularCamera = false
                        Task { await model.captureCircularCode(image: image) }
                    }
                    .ignoresSafeArea()
                    .navigationTitle("Circular Code")
                    .toolbar {
                        Button("Cancel") { showingCircularCamera = false }
                    }
                }
            }
            .sheet(isPresented: $model.needsSignIn) {
                SignInView(model: model)
                    .presentationDetents([.medium])
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Scan a module or HCM code")
                .font(.largeTitle.bold())
            Text("The app checks the HCM session first. If there is no valid token, it asks you to sign in before showing configuration.")
                .foregroundStyle(.secondary)
        }
    }

    private var hcmConnection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("HCM")
                .font(.headline)
            TextField("HCM URL", text: $model.hcmURL)
                .textInputAutocapitalization(.never)
                .keyboardType(.URL)
                .textFieldStyle(.roundedBorder)
            HStack {
                Label(model.session?.user ?? "Not signed in", systemImage: model.session == nil ? "lock" : "checkmark.seal")
                    .foregroundStyle(model.session == nil ? Color.secondary : Color.green)
                Spacer()
                if let role = model.session?.role {
                    Text(role)
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }

    private var scanActions: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Code")
                .font(.headline)
            Button {
                showingScanner = true
            } label: {
                Label("Scan Standard Code", systemImage: "viewfinder")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)

            Button {
                showingCircularCamera = true
            } label: {
                Label("Capture Circular Code", systemImage: "camera.metering.center.weighted")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)

            TextField("Paste HC1:HCM01:482913 or a module id", text: $manualCode)
                .textInputAutocapitalization(.characters)
                .textFieldStyle(.roundedBorder)
            HStack {
                Button {
                    Task { await model.scan(rawCode: manualCode) }
                } label: {
                    Label("Open Code", systemImage: "arrow.forward.circle")
                }
                .disabled(manualCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

                Button {
                    Task { await model.loadSimulatorPairingGlyph() }
                } label: {
                    Label("Load Simulator", systemImage: "dot.viewfinder")
                }
            }
            .buttonStyle(.bordered)
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }

    private func targetSummary(_ target: ScannedTarget) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Scanned Target")
                .font(.headline)
            DetailRow(label: "Target", value: target.targetId)
            if let hcmId = target.hcmId {
                DetailRow(label: "HCM", value: hcmId)
            }
            if let code = target.pairingCode {
                DetailRow(label: "Pairing code", value: code.chunkedCode)
            }
            if let ok = model.circularCompareOK {
                DetailRow(label: "HCM token match", value: ok ? "Matched" : "Rejected")
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }
}

private struct SignInView: View {
    @Bindable var model: HomeControlViewModel

    var body: some View {
        NavigationStack {
            Form {
                Section("HCM Sign In") {
                    TextField("Username", text: $model.username)
                        .textInputAutocapitalization(.never)
                    SecureField("Password", text: $model.password)
                    Button("Sign In") {
                        Task { await model.signIn() }
                    }
                    .disabled(model.username.isEmpty || model.password.isEmpty || model.isLoading)
                    Button("Use Dev Session") {
                        Task { await model.useDevSession() }
                    }
                    .disabled(model.isLoading)
                }

                if let error = model.errorMessage {
                    Section {
                        Text(error)
                            .foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("Sign In")
        }
    }
}

private struct DeviceConfigView: View {
    let target: ScannedTarget
    let device: HCMDevice?
    let state: SimulatorState

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(device?.label ?? target.targetId)
                    .font(.headline)
                Spacer()
                Text(device?.type ?? "UNKNOWN")
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            }

            switch device?.type ?? target.targetId.prefix(3).uppercased() {
            case "HCM":
                hcmConfig
            case "RCM":
                rcmConfig
            case "LCM":
                lcmConfig
            case "SIM":
                simConfig
            case "PNL":
                pnlConfig
            default:
                Text("No HCM-backed configuration page is available for this code yet.")
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }

    private var hcmConfig: some View {
        VStack(alignment: .leading, spacing: 8) {
            DetailRow(label: "Mode", value: state.hcm.hvac.mode)
            DetailRow(label: "Setpoint", value: "\(state.hcm.hvac.setpointF.formatted()) F")
            DetailRow(label: "Average", value: state.hcm.hvac.averageF.map { "\($0.formatted()) F" } ?? "-")
            DetailRow(label: "Calls", value: ["fan": state.hcm.hvac.fan, "cool": state.hcm.hvac.cool, "heat": state.hcm.hvac.heat].filter(\.value).map(\.key).joined(separator: ", ").nilIfEmpty ?? "Idle")
        }
    }

    private var rcmConfig: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 86), spacing: 8)], spacing: 8) {
            ForEach((state.rcm?.relays.keys.naturalSorted() ?? []), id: \.self) { channel in
                let on = state.rcm?.relays[channel] ?? false
                VStack(spacing: 4) {
                    Text(channel)
                        .font(.caption.monospaced())
                    Text(on ? "ON" : "OFF")
                        .font(.headline)
                .foregroundStyle(on ? Color.green : Color.secondary)
                    Text(state.rcm?.names?[channel] ?? "")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                .frame(maxWidth: .infinity)
                .padding(8)
                .background(.background, in: RoundedRectangle(cornerRadius: 8))
            }
        }
    }

    private var lcmConfig: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Relays")
                .font(.subheadline.bold())
            rcmLikeGrid(relays: state.lcm?.relays ?? [:], names: state.lcm?.names ?? [:])
            Text("Dimmers")
                .font(.subheadline.bold())
            ForEach((state.lcm?.hvDimmers.keys.naturalSorted() ?? []), id: \.self) { channel in
                dimmerRow(channel: channel, dimmer: state.lcm?.hvDimmers[channel], name: state.lcm?.names?[channel])
            }
            ForEach((state.lcm?.lvDimmers.keys.naturalSorted() ?? []), id: \.self) { channel in
                dimmerRow(channel: channel, dimmer: state.lcm?.lvDimmers[channel], name: state.lcm?.names?[channel])
            }
        }
    }

    private func rcmLikeGrid(relays: [String: Bool], names: [String: String]) -> some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 86), spacing: 8)], spacing: 8) {
            ForEach(relays.keys.naturalSorted(), id: \.self) { channel in
                Text("\(channel) \(relays[channel] == true ? "ON" : "OFF")")
                    .frame(maxWidth: .infinity)
                    .padding(8)
                    .background(.background, in: RoundedRectangle(cornerRadius: 8))
            }
        }
    }

    private func dimmerRow(channel: String, dimmer: DimmerState?, name: String?) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(channel)
                    .font(.caption.monospaced())
                Text(name ?? "")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                Text("\((dimmer?.percent ?? 0).formatted())%")
            }
            ProgressView(value: dimmer?.percent ?? 0, total: 100)
        }
    }

    private var simConfig: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach((state.sim?.rmcNodes.keys.sorted() ?? []), id: \.self) { key in
                let node = state.sim?.rmcNodes[key]
                DetailRow(label: "RMC \(key)", value: "\(node?.temperatureF?.formatted() ?? "-") F / \(node?.humidityPct?.formatted() ?? "-")% RH")
            }
        }
    }

    private var pnlConfig: some View {
        VStack(alignment: .leading, spacing: 8) {
            DetailRow(label: "Room", value: state.pnl?.room ?? "Unassigned")
            DetailRow(label: "Dashboard", value: state.pnl?.dashboardURL ?? "-")
        }
    }
}

private struct DetailRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label)
                .foregroundStyle(.secondary)
            Spacer()
            Text(value)
                .multilineTextAlignment(.trailing)
        }
    }
}

private extension String {
    var chunkedCode: String {
        guard count == 6 else { return self }
        let midpoint = index(startIndex, offsetBy: 3)
        return "\(self[..<midpoint]) \(self[midpoint...])"
    }

    var nilIfEmpty: String? {
        isEmpty ? nil : self
    }
}

private extension Collection where Element == String {
    func naturalSorted() -> [String] {
        sorted { $0.localizedStandardCompare($1) == .orderedAscending }
    }
}

#Preview {
    ContentView()
}
