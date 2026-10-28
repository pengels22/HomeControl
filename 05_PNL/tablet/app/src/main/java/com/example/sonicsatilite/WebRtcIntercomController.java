package com.example.sonicsatilite;

import android.Manifest;
import android.content.pm.PackageManager;
import android.os.Build;
import android.provider.Settings;
import android.util.Log;
import android.view.MotionEvent;
import android.widget.Button;

import androidx.core.content.ContextCompat;

import org.java_websocket.client.WebSocketClient;
import org.java_websocket.handshake.ServerHandshake;
import org.json.JSONObject;
import org.webrtc.AudioSource;
import org.webrtc.AudioTrack;
import org.webrtc.Camera2Enumerator;
import org.webrtc.IceCandidate;
import org.webrtc.MediaConstraints;
import org.webrtc.MediaStream;
import org.webrtc.PeerConnection;
import org.webrtc.PeerConnectionFactory;
import org.webrtc.RtpReceiver;
import org.webrtc.SdpObserver;
import org.webrtc.SessionDescription;
import org.webrtc.VideoSink;
import org.webrtc.VideoTrack;

import java.net.URI;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ExecutorService;

/** Audio-only WebRTC intercom. Signaling is a small authenticated WebSocket relay. */
final class WebRtcIntercomController implements AudioIntercom {
    private static final String SIGNAL = "wss://192.168.1.6:8443/intercom";
    private final MainActivity activity;
    private final SonicApi api;
    private final ExecutorService audioExecutor;
    private final Button firstButton;
    private final Button secondButton;
    private final IntercomVolumeController volume;
    private final Map<String, PeerSession> sessions = new HashMap<>();
    private final String tabletId;
    private final String firstTarget;
    private final String secondTarget;
    private volatile boolean stopping;
    private PeerConnectionFactory factory;
    private AudioSource audioSource;
    private AudioTrack localAudio;

    WebRtcIntercomController(MainActivity activity, SonicApi api, ExecutorService audioExecutor,
                             Button firstButton, Button secondButton) {
        this.activity = activity;
        this.api = api;
        this.audioExecutor = audioExecutor;
        this.firstButton = firstButton;
        this.secondButton = secondButton;
        volume = new IntercomVolumeController(activity);
        tabletId = tabletId();
        if ("living-room".equals(tabletId)) { firstTarget = "office"; secondTarget = "bedroom"; }
        else if ("office".equals(tabletId)) { firstTarget = "living-room"; secondTarget = "bedroom"; }
        else { firstTarget = "office"; secondTarget = "living-room"; }
        firstButton.setText(displayName(firstTarget));
        secondButton.setText(displayName(secondTarget));
        firstButton.setOnTouchListener((v, e) -> touch(e, firstTarget, firstButton));
        secondButton.setOnTouchListener((v, e) -> touch(e, secondTarget, secondButton));
    }

    public void start() {
        PeerConnectionFactory.initialize(PeerConnectionFactory.InitializationOptions.builder(activity).createInitializationOptions());
        factory = PeerConnectionFactory.builder().createPeerConnectionFactory();
        audioSource = factory.createAudioSource(new MediaConstraints());
        localAudio = factory.createAudioTrack("sonic-audio-" + tabletId, audioSource);
        localAudio.setEnabled(false);
        open(firstTarget);
        open(secondTarget);
    }

    public void stopTransmitting() { if (localAudio != null) localAudio.setEnabled(false); }

    public void shutdown() {
        stopping = true;
        stopTransmitting();
        volume.end();
        for (PeerSession session : new ArrayList<>(sessions.values())) session.shutdownSession();
        sessions.clear();
        if (audioSource != null) audioSource.dispose();
        if (factory != null) factory.dispose();
    }

    private boolean touch(MotionEvent event, String target, Button button) {
        if (event.getAction() == MotionEvent.ACTION_DOWN) {
            if (ContextCompat.checkSelfPermission(activity, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                button.setText("Mic needed");
                return true;
            }
            PeerSession session = sessions.get(target);
            if (session == null || session.pc == null) { button.setText("Connecting…"); return true; }
            activity.prepareForIntercom();
            localAudio.setEnabled(true);
            button.setText("Paging…");
            activity.setIntercomStatus(displayName(target), true);
            session.control("start");
            session.offer();
            return true;
        }
        if (event.getAction() == MotionEvent.ACTION_UP || event.getAction() == MotionEvent.ACTION_CANCEL) {
            stopTransmitting();
            PeerSession session = sessions.get(target);
            if (session != null) session.control("stop");
            button.setText(displayName(target));
            activity.setIntercomStatus(displayName(target), false);
            return true;
        }
        return true;
    }

    private void open(String target) {
        try {
            String token = api.intercomToken();
            URI uri = new URI(SIGNAL + "?tablet=" + tabletId + "&target=" + target);
            Map<String, String> headers = new HashMap<>();
            headers.put("Authorization", "Bearer " + token);
            PeerSession session = new PeerSession(target, uri, headers);
            session.setSocketFactory(api.intercomSslContext().getSocketFactory());
            sessions.put(target, session);
            session.connect();
        } catch (Exception e) { Log.e("WebRtcIntercom", "SIGNAL_SETUP_FAILED target=" + target, e); }
    }

    private PeerConnection makePeer(PeerSession session) {
        PeerConnection.RTCConfiguration config = new PeerConnection.RTCConfiguration(
                Collections.singletonList(PeerConnection.IceServer.builder("stun:stun.l.google.com:19302").createIceServer()));
        PeerConnection pc = factory.createPeerConnection(config, session);
        if (pc != null && localAudio != null) pc.addTrack(localAudio);
        return pc;
    }

    private final class PeerSession extends WebSocketClient implements PeerConnection.Observer {
        final String target;
        PeerConnection pc;
        boolean remoteDescription;
        PeerSession(String target, URI uri, Map<String, String> headers) { super(uri, headers); this.target = target; }
        void shutdownSession() { try { if (pc != null) pc.close(); } catch (Exception ignored) {} try { closeBlocking(); } catch (Exception ignored) {} }
        void offer() {
            if (pc == null) pc = makePeer(this);
            pc.createOffer(new SdpObserver() {
                public void onCreateSuccess(SessionDescription s) { pc.setLocalDescription(this, s); sendSdp("offer", s); }
                public void onSetSuccess() {} public void onCreateFailure(String s) {} public void onSetFailure(String s) {}
            }, new MediaConstraints());
        }
        void sendSdp(String type, SessionDescription s) { try { send(new JSONObject().put("type", type).put("sdp", s.description).toString()); } catch (Exception ignored) {} }
        void control(String value) { try { send(new JSONObject().put("type", value).toString()); } catch (Exception ignored) {} }
        public void onOpen(ServerHandshake h) { Log.i("WebRtcIntercom", "SIGNAL_OPEN target=" + target); }
        public void onMessage(String raw) {
            try {
                JSONObject m = new JSONObject(raw);
                String type = m.optString("type");
                if ("offer".equals(type)) {
                    if (pc == null) pc = makePeer(this);
                    pc.setRemoteDescription(new SimpleSdp() { public void onSetSuccess() { remoteDescription = true; answer(); } }, new SessionDescription(SessionDescription.Type.OFFER, m.getString("sdp")));
                } else if ("start".equals(type)) {
                    volume.begin();
                } else if ("stop".equals(type)) {
                    volume.end();
                } else if ("answer".equals(type) && pc != null) {
                    pc.setRemoteDescription(new SimpleSdp(), new SessionDescription(SessionDescription.Type.ANSWER, m.getString("sdp")));
                } else if ("candidate".equals(type) && pc != null) {
                    pc.addIceCandidate(new IceCandidate(m.getString("sdpMid"), m.getInt("sdpMLineIndex"), m.getString("candidate")));
                }
            } catch (Exception ignored) {}
        }
        void answer() { pc.createAnswer(new SdpObserver() { public void onCreateSuccess(SessionDescription s) { pc.setLocalDescription(this, s); sendSdp("answer", s); } public void onSetSuccess() {} public void onCreateFailure(String s) {} public void onSetFailure(String s) {} }, new MediaConstraints()); }
        public void onClose(int code, String reason, boolean remote) { volume.end(); }
        public void onError(Exception e) { Log.e("WebRtcIntercom", "SIGNAL_ERROR target=" + target, e); }
        public void onSignalingChange(PeerConnection.SignalingState s) {}
        public void onIceConnectionChange(PeerConnection.IceConnectionState s) {}
        public void onIceConnectionReceivingChange(boolean b) {}
        public void onIceGatheringChange(PeerConnection.IceGatheringState s) {}
        public void onIceCandidate(IceCandidate c) { try { send(new JSONObject().put("type", "candidate").put("sdpMid", c.sdpMid).put("sdpMLineIndex", c.sdpMLineIndex).put("candidate", c.sdp).toString()); } catch (Exception ignored) {} }
        public void onIceCandidatesRemoved(IceCandidate[] c) {}
        public void onAddStream(MediaStream s) {}
        public void onRemoveStream(MediaStream s) {}
        public void onDataChannel(org.webrtc.DataChannel c) {}
        public void onRenegotiationNeeded() {}
        public void onAddTrack(RtpReceiver r, MediaStream[] s) {}
    }

    private static class SimpleSdp implements SdpObserver {
        public void onCreateSuccess(SessionDescription s) {} public void onCreateFailure(String s) {}
        public void onSetFailure(String s) {} public void onSetSuccess() {}
    }

    private String tabletId() {
        String serial = Build.SERIAL;
        if ("G0W0MB068265F06A".equals(serial)) return "bedroom";
        if ("G0W0MB068265F04A".equals(serial)) return "living-room";
        if ("G0W0T9059434F6JG".equals(serial)) return "office";
        String id = Settings.Secure.getString(activity.getContentResolver(), Settings.Secure.ANDROID_ID);
        if ("293601fcb83c4e73".equals(id)) return "bedroom";
        if ("70071a26b3ce6ab1".equals(id)) return "living-room";
        if ("c27a72a92885f103".equals(id) || "5707e40ae6bc7748".equals(id)) return "office";
        return "tablet-" + id;
    }
    private static String displayName(String id) { return "living-room".equals(id) ? "Living Room" : ("office".equals(id) ? "Office" : "Bedroom"); }
}
