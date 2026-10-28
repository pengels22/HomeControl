package com.example.sonicsatilite;

import android.Manifest;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.AudioTrack;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.SystemClock;
import android.provider.Settings;
import android.util.Log;
import android.view.MotionEvent;
import android.widget.Button;

import androidx.core.content.ContextCompat;

import org.eclipse.paho.client.mqttv3.IMqttDeliveryToken;
import org.eclipse.paho.client.mqttv3.MqttAsyncClient;
import org.eclipse.paho.client.mqttv3.MqttCallbackExtended;
import org.eclipse.paho.client.mqttv3.MqttConnectOptions;
import org.eclipse.paho.client.mqttv3.MqttMessage;
import org.eclipse.paho.client.mqttv3.persist.MemoryPersistence;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Audio-only, half-duplex push-to-talk intercom over the existing MQTT broker. */
final class IntercomController implements AudioIntercom {
    private static final String TAG = "Intercom";
    private static final String BASE_TOPIC = "home/tablets/intercom";
    private static final int SAMPLE_RATE = 16000;
    private static final int FRAME_SAMPLES = 320; // 20 ms mono PCM16
    private static final int FRAME_BYTES = FRAME_SAMPLES * 2;
    private static final long SILENCE_HOLD_MS = 2000L;
    private static final double SILENCE_RMS_THRESHOLD = 1100.0;

    private final MainActivity activity;
    private final ExecutorService audioExecutor;
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final Button firstButton;
    private final Button secondButton;
    private final IntercomVolumeController volume;
    private final String tabletId;
    private final String firstTarget;
    private final String secondTarget;
    private final Object playbackLock = new Object();
    private MqttAsyncClient client;
    private AudioTrack playback;
    private volatile boolean connected;
    private volatile boolean transmitting;
    private volatile boolean stopping;
    private volatile String activeTarget;
    private volatile Button activeButton;
    private int publishedFrames;
    private int receivedFrames;

    IntercomController(MainActivity activity, ExecutorService audioExecutor,
                       Button firstButton, Button secondButton) {
        this.activity = activity;
        this.audioExecutor = audioExecutor;
        this.firstButton = firstButton;
        this.secondButton = secondButton;
        volume = new IntercomVolumeController(activity);
        tabletId = tabletId();
        if ("living-room".equals(tabletId)) {
            firstTarget = "office";
            secondTarget = "bedroom";
        } else if ("office".equals(tabletId)) {
            firstTarget = "living-room";
            secondTarget = "bedroom";
        } else {
            firstTarget = "office";
            secondTarget = "living-room";
        }
        firstButton.setText(displayName(firstTarget));
        secondButton.setText(displayName(secondTarget));
        // Keep the controls touchable while MQTT connects. A disabled Android
        // button makes a failed or delayed connection look like a dead UI.
        // handleTouch() gives the user an explicit Unavailable response.
        firstButton.setEnabled(true);
        secondButton.setEnabled(true);
        firstButton.setOnTouchListener((view, event) -> handleTouch(event, firstTarget, firstButton));
        secondButton.setOnTouchListener((view, event) -> handleTouch(event, secondTarget, secondButton));
    }

    public void start() { io.execute(this::connect); }

    public void shutdown() {
        stopping = true;
        transmitting = false;
        volume.end();
        synchronized (playbackLock) {
            if (playback != null) {
                playback.stop();
                playback.release();
                playback = null;
            }
        }
        try {
            if (client != null && client.isConnected()) client.disconnect();
        } catch (Exception ignored) { }
        connected = false;
        io.shutdownNow();
    }

    public void stopTransmitting() {
        transmitting = false;
        String target = activeTarget;
        if (target != null) publishControl(target, "stop");
    }

    private boolean handleTouch(MotionEvent event, String target, Button button) {
        if (event.getAction() == MotionEvent.ACTION_DOWN) {
            if (transmitting) {
                transmitting = false;
                publishControl(activeTarget == null ? target : activeTarget, "stop");
                return true;
            }
            if (!connected || !activity.intercomPolicyGranted()) {
                button.setText("Unavailable");
                button.postDelayed(() -> button.setText(displayName(target)), 1200L);
                return true;
            }
            if (ContextCompat.checkSelfPermission(activity, Manifest.permission.RECORD_AUDIO)
                    != PackageManager.PERMISSION_GRANTED) {
                button.setText("Mic needed");
                button.postDelayed(() -> button.setText(displayName(target)), 1200L);
                return true;
            }
            activity.prepareForIntercom();
            activeTarget = target;
            activeButton = button;
            transmitting = true;
            publishControl(target, "start");
            button.setText("Paging…");
            activity.setIntercomStatus(displayName(target), true);
            audioExecutor.execute(() -> capture(target, button));
            return true;
        }
        // PTT is latched: release happens after one second of microphone silence.
        return true;
    }

    private void connect() {
        if (stopping) return;
        try {
            String clientId = "sonic-intercom-" + tabletId + "-" + UUID.randomUUID().toString().substring(0, 8);
            client = new MqttAsyncClient("tcp://" + BuildConfig.MQTT_HOST + ":" + BuildConfig.MQTT_PORT,
                    clientId, new MemoryPersistence());
            client.setCallback(new MqttCallbackExtended() {
                @Override public void connectComplete(boolean reconnect, String serverURI) {
                    try {
                        client.subscribe(audioTopic(tabletId), 0);
                        client.subscribe(controlTopic(tabletId), 0);
                        connected = true;
                        Log.i(TAG, "MQTT intercom connected tablet=" + tabletId);
                        activity.runOnUiThread(() -> {
                            firstButton.setEnabled(true);
                            secondButton.setEnabled(true);
                        });
                    } catch (Exception e) { Log.e(TAG, "INTERCOM_SUBSCRIBE_FAILED", e); }
                }
                @Override public void connectionLost(Throwable cause) {
                    connected = false;
                    Log.w(TAG, "INTERCOM_CONNECTION_LOST", cause);
                    activity.runOnUiThread(() -> {
                        firstButton.setEnabled(true);
                        secondButton.setEnabled(true);
                    });
                }
                @Override public void messageArrived(String topic, MqttMessage message) {
                    String value = new String(message.getPayload(), java.nio.charset.StandardCharsets.UTF_8).trim();
                    if (topic.endsWith("/control")) {
                        if ("start".equalsIgnoreCase(value)) volume.begin();
                        else if ("stop".equalsIgnoreCase(value)) volume.end();
                    } else if (!transmitting) play(message.getPayload());
                    if (!topic.endsWith("/control") && (++receivedFrames % 50 == 0))
                        Log.i(TAG, "INTERCOM_AUDIO_RECEIVED frames=" + receivedFrames);
                }
                @Override public void deliveryComplete(IMqttDeliveryToken token) { }
            });
            MqttConnectOptions options = new MqttConnectOptions();
            options.setUserName(BuildConfig.MQTT_USER);
            options.setPassword(BuildConfig.MQTT_PASSWORD.toCharArray());
            options.setAutomaticReconnect(true);
            options.setCleanSession(false);
            options.setConnectionTimeout(10);
            client.connect(options).waitForCompletion();
        } catch (Exception e) { Log.e(TAG, "INTERCOM_CONNECT_FAILED", e); }
    }

    private void capture(String target, Button button) {
        AudioRecord recorder = null;
        try {
            int minimum = AudioRecord.getMinBufferSize(SAMPLE_RATE,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
            if (minimum <= 0) throw new IllegalStateException("microphone unavailable");
            recorder = new AudioRecord(MediaRecorder.AudioSource.MIC, SAMPLE_RATE,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
                    Math.max(minimum, FRAME_BYTES * 4));
            if (recorder.getState() != AudioRecord.STATE_INITIALIZED)
                throw new IllegalStateException("microphone could not initialize");
            recorder.startRecording();
            Log.i(TAG, "INTERCOM_CAPTURE_STARTED target=" + target);
            short[] samples = new short[FRAME_SAMPLES];
            long silenceStartedAt = -1L;
            double noiseFloorRms = Double.POSITIVE_INFINITY;
            while (transmitting && connected && activity.intercomPolicyGranted()) {
                int count = recorder.read(samples, 0, samples.length);
                if (count != samples.length) break;
                ByteBuffer bytes = ByteBuffer.allocate(FRAME_BYTES).order(ByteOrder.LITTLE_ENDIAN);
                for (short sample : samples) bytes.putShort(sample);
                MqttMessage message = new MqttMessage(bytes.array());
                message.setQos(0);
                message.setRetained(false);
                client.publish(audioTopic(target), message);
                if (++publishedFrames % 50 == 0)
                    Log.i(TAG, "INTERCOM_AUDIO_PUBLISHED target=" + target + " frames=" + publishedFrames);

                double sumSquares = 0.0;
                int peak = 0;
                for (short sample : samples) {
                    int magnitude = Math.abs((int) sample);
                    peak = Math.max(peak, magnitude);
                    sumSquares += (double) sample * sample;
                }
                double rms = Math.sqrt(sumSquares / samples.length);
                // Calibrate against the quietest level seen on this tablet.
                // Fire tablet microphones can have a higher idle floor than
                // the fixed threshold, which otherwise prevents unlatching.
                noiseFloorRms = Math.min(noiseFloorRms, rms);
                double silenceThreshold = Math.max(SILENCE_RMS_THRESHOLD, noiseFloorRms * 1.8);
                boolean silent = rms < silenceThreshold;
                if (silent) {
                    if (silenceStartedAt < 0L) silenceStartedAt = SystemClock.elapsedRealtime();
                    if (SystemClock.elapsedRealtime() - silenceStartedAt >= SILENCE_HOLD_MS) {
                        Log.i(TAG, "INTERCOM_SILENCE_RELEASE target=" + target + " rms=" + rms);
                        transmitting = false;
                    }
                } else {
                    silenceStartedAt = -1L;
                }
            }
        } catch (Exception e) {
            Log.e(TAG, "INTERCOM_CAPTURE_FAILED", e);
        } finally {
            transmitting = false;
            publishControl(target, "stop");
            if (recorder != null) {
                try { recorder.stop(); } catch (Exception ignored) { }
                recorder.release();
            }
            activity.runOnUiThread(() -> button.setText(displayName(target)));
            activity.runOnUiThread(() -> activity.setIntercomStatus(displayName(target), false));
            if (target.equals(activeTarget)) {
                activeTarget = null;
                activeButton = null;
            }
            Log.i(TAG, "INTERCOM_CAPTURE_STOPPED target=" + target + " frames=" + publishedFrames);
        }
    }

    private void play(byte[] bytes) {
        if (bytes.length == 0) return;
        synchronized (playbackLock) {
            try {
                if (playback == null) {
                    int minimum = AudioTrack.getMinBufferSize(SAMPLE_RATE,
                            AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT);
                    playback = new AudioTrack(AudioManager.STREAM_MUSIC, SAMPLE_RATE,
                            AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT,
                            Math.max(minimum, FRAME_BYTES * 4), AudioTrack.MODE_STREAM);
                    playback.play();
                }
                playback.write(bytes, 0, bytes.length);
            } catch (Exception e) { Log.e(TAG, "INTERCOM_PLAYBACK_FAILED", e); }
        }
    }

    private static String audioTopic(String tablet) { return BASE_TOPIC + "/" + tablet + "/audio"; }
    private static String controlTopic(String tablet) { return BASE_TOPIC + "/" + tablet + "/control"; }

    private void publishControl(String target, String value) {
        try {
            if (client == null || !client.isConnected()) return;
            MqttMessage message = new MqttMessage(value.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            message.setQos(0);
            client.publish(controlTopic(target), message);
        } catch (Exception e) { Log.w(TAG, "INTERCOM_CONTROL_FAILED", e); }
    }

    private String tabletId() {
        String serial = Build.SERIAL;
        if ("G0W0MB068265F06A".equals(serial)) return "bedroom";
        if ("G0W0MB068265F04A".equals(serial)) return "living-room";
        if ("G0W0T9059434F6JG".equals(serial)) return "office";
        String androidId = Settings.Secure.getString(activity.getContentResolver(), Settings.Secure.ANDROID_ID);
        if ("293601fcb83c4e73".equals(androidId)) return "bedroom";
        if ("70071a26b3ce6ab1".equals(androidId)) return "living-room";
        if ("c27a72a92885f103".equals(androidId) || "5707e40ae6bc7748".equals(androidId)) return "office";
        return "tablet-" + serial.toLowerCase(Locale.US).replaceAll("[^a-z0-9_-]", "");
    }

    private static String displayName(String id) {
        if ("living-room".equals(id)) return "Living Room";
        if ("office".equals(id)) return "Office";
        if ("bedroom".equals(id)) return "Bedroom";
        return id;
    }
}
