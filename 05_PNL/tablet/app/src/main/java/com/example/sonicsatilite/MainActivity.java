package com.example.sonicsatilite;

import android.Manifest;
import android.app.AlertDialog;
import android.app.admin.DevicePolicyManager;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.audiofx.AutomaticGainControl;
import android.media.MediaRecorder;
import android.os.Bundle;
import android.os.Build;
import android.os.SystemClock;
import android.os.Handler;
import android.os.Looper;
import android.content.Intent;
import android.net.Uri;
import android.provider.Settings;
import android.view.WindowManager;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.Space;
import android.widget.TextView;
import android.widget.Switch;
import android.widget.Spinner;
import android.widget.AdapterView;
import android.text.format.DateFormat;

import androidx.activity.EdgeToEdge;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;

import java.io.File;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.net.ConnectException;
import java.net.NoRouteToHostException;
import java.net.SocketTimeoutException;
import java.net.UnknownHostException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.HashMap;
import java.util.Map;
import javax.net.ssl.SSLException;
import org.json.JSONObject;

public class MainActivity extends AppCompatActivity {
    private static final int SAMPLE_RATE = 16000;
    private static final int CHANNELS = 1;
    private static final int BITS_PER_SAMPLE = 16;
    private static final int MAX_AUDIO_BYTES = SAMPLE_RATE * CHANNELS * BITS_PER_SAMPLE / 8 * 5;
    private static final int COMMAND_MAX_MS = 8000;
    private static final int COMMAND_SPEECH_START_TIMEOUT_MS = 3000;
    private static final int COMMAND_SILENCE_MS = 1200;
    private static final int COMMAND_PREROLL_MS = 400;
    private static final int UPLOAD_WATCHDOG_MS = 75000;
    private static final int SPEECH_RMS_THRESHOLD = 700;
    private static final int MICROPHONE_PERMISSION_REQUEST = 1;
    private static final int IMPORT_TOKEN_REQUEST = 2;
    private static final int IMPORT_CA_REQUEST = 3;
    private static final int LOCAL_CA_PERMISSION_REQUEST = 4;
    private static final int LOCAL_TOKEN_PERMISSION_REQUEST = 5;
    private static final int REMOVE_LOCAL_TOKEN_PERMISSION_REQUEST = 6;
    private static final int CAMERA_PERMISSION_REQUEST = 7;
    private static final long WAKE_COOLDOWN_MS = 2500;

    private Button recordButton;
    private TextView headerClock;
    private TextView statusText;
    private TextView elapsedText;
    private TextView sizeText;
    private TextView fileText;
    private TextView errorText;
    private TextView importStatusText;
    private TextView connectionText;
    private TextView credentialText;
    private TextView muteText;
    private TextView transcriptionText;
    private TextView haText;
    private TextView diagnosticEvents;
    private TextView inputLevelText, inputAgcText, inputClipText;
    private Spinner gainSpinner;
    private android.view.View settingsPage;
    private Button sendButton;
    private Button removeLocalTokenButton;
    private Switch wakeToggle;
    private TextView wakeStateText, wakeModelText, wakeConfidenceText, wakeCountText, wakeLastText,
            wakeInferenceText;
    private final ExecutorService microphone = Executors.newSingleThreadExecutor();
    private volatile AudioRecord wakeRecorder;
    private final Object wakeAudioLock = new Object();
    private volatile boolean wakeRequested;
    private volatile boolean policyGranted;
    private volatile int wakeSession;
    private long lastWakeElapsed;
    private int wakeCount;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable clockTick = new Runnable() {
        @Override public void run() {
            if (headerClock != null) headerClock.setText(DateFormat.format("EEE, MMM d   h:mm a", new java.util.Date()));
            handler.postDelayed(this, 30000L);
        }
    };
    private final ExecutorService network = Executors.newFixedThreadPool(2);
    private SonicApi api;
    private PanelController panel;
    private MqttScreenController mqttScreen;
    private AudioIntercom intercom;
    private ShopController shopController;
    private android.app.KeyguardManager.KeyguardLock keyguardLock;
    private File latestWav;
    private volatile boolean allowed;
    private boolean checking;
    private volatile boolean uploading;
    private boolean visible;
    private boolean recordAttemptPending;
    private boolean awaitingMicrophonePermission;
    private boolean wakePermissionRequested;
    private boolean localTokenImported;
    private boolean removeLocalTokenConfirmed;
    private final Runnable poll = new Runnable() {
        @Override public void run() {
            checkConnection(false);
            if (visible || wakeRequested || recording || commandRecording) handler.postDelayed(this, 4000);
        }
    };
    private boolean recording;
    private volatile boolean cancelled;
    private volatile boolean destroyed;
    private volatile boolean commandRecording;
    private volatile boolean uploadFromWake;
    private boolean diagnosticTranscriptionLogging;
    private android.content.SharedPreferences preferences;
    private final StringBuilder eventLog = new StringBuilder();
    private long previousStageElapsed = -1;
    private final int voiceOwnerIdentity = System.identityHashCode(this);
    private volatile float softwareGain = 1.0f;
    private volatile boolean hardwareAgcActive;
    private long lastMeterUiElapsed;
    private enum CaptureState { IDLE, LISTENING, WAKE_DETECTED, WAITING_FOR_SPEECH,
        RECORDING_SPEECH, UPLOADING, PROCESSING_COMMAND, MUTED, DISCONNECTED, ERROR }
    private volatile CaptureState captureState = CaptureState.IDLE;
    private volatile long activeCommandGeneration;
    private long nextCommandGeneration;
    private Runnable uploadWatchdog;
    private String lastPublishedWakeState;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // This is a wall-mounted tablet: keep the dashboard awake and remove
        // the swipe-through keyguard when the display is woken.
        getWindow().addFlags((isLivingRoomTablet() ? 0 : WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                | WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD
                | WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
            android.app.KeyguardManager keyguard =
                    (android.app.KeyguardManager) getSystemService(KEYGUARD_SERVICE);
            if (keyguard != null) {
                keyguard.requestDismissKeyguard(this, null);
            }
        }
        // Fire OS 5 can leave a swipe layer after a screen-off wake; this
        // legacy API is required there even with lockscreen.disabled=1.
        android.app.KeyguardManager legacyKeyguard =
                (android.app.KeyguardManager) getSystemService(KEYGUARD_SERVICE);
        if (legacyKeyguard != null) {
            try {
                keyguardLock = legacyKeyguard.newKeyguardLock("SonicSatilite");
                keyguardLock.disableKeyguard();
            }
            catch (RuntimeException ignored) { }
        }
        // Keep production screens protected; debug builds remain capturable for
        // tablet layout tuning and visual verification.
        if (!BuildConfig.DEBUG) {
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        }
        EdgeToEdge.enable(this);
        setContentView(R.layout.activity_main);
        hideSystemChrome();
        headerClock = findViewById(R.id.header_clock);
        clockTick.run();
        settingsPage = findViewById(R.id.settings_page);
        preferences = getSharedPreferences("sonic-settings", MODE_PRIVATE);
        if (isLivingRoomTablet()) {
            // Wake word is explicitly enabled on the living-room tablet after
            // switching to the Fire OS-compatible TensorFlow Lite runtime.
            preferences.edit().putBoolean("wake_enabled", true).apply();
        }
        android.util.Log.i("SonicSatellite", "Voice controller created; instance=" + voiceOwnerIdentity);
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main), (view, insets) -> {
            Insets bars = insets.getInsets(WindowInsetsCompat.Type.systemBars());
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return insets;
        });
        recordButton = findViewById(R.id.record_button);
        statusText = findViewById(R.id.status_text);
        elapsedText = findViewById(R.id.elapsed_text);
        sizeText = findViewById(R.id.size_text);
        fileText = findViewById(R.id.file_text);
        errorText = findViewById(R.id.error_text);
        importStatusText = findViewById(R.id.import_status_text);
        connectionText = findViewById(R.id.connection_text);
        credentialText = findViewById(R.id.credential_text);
        muteText = findViewById(R.id.mute_text);
        transcriptionText = findViewById(R.id.transcription_text);
        haText = findViewById(R.id.ha_text);
        diagnosticEvents = findViewById(R.id.diagnostic_events);
        inputLevelText = findViewById(R.id.input_level_text);
        inputAgcText = findViewById(R.id.input_agc_text);
        inputClipText = findViewById(R.id.input_clip_text);
        gainSpinner = findViewById(R.id.gain_spinner);
        sendButton = findViewById(R.id.settings_send_button);
        removeLocalTokenButton = findViewById(R.id.remove_local_token_button);
        wakeToggle = findViewById(R.id.wake_toggle);
        Switch transcriptionLogging = findViewById(R.id.transcription_logging);
        diagnosticTranscriptionLogging = preferences.getBoolean("diagnostic_transcription_logging", false);
        transcriptionLogging.setChecked(diagnosticTranscriptionLogging);
        transcriptionLogging.setOnCheckedChangeListener((button, enabled) -> {
            diagnosticTranscriptionLogging = enabled;
            preferences.edit().putBoolean("diagnostic_transcription_logging", enabled).apply();
        });
        final float[] gainOptions = {1.0f, 1.5f, 2.0f, 3.0f};
        softwareGain = preferences.getFloat("microphone_gain", 1.0f);
        int selectedGain = 0;
        for (int i = 0; i < gainOptions.length; i++) {
            if (Math.abs(gainOptions[i] - softwareGain) < 0.01f) selectedGain = i;
        }
        gainSpinner.setSelection(selectedGain);
        softwareGain = gainOptions[selectedGain];
        gainSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, android.view.View view,
                                                  int position, long id) {
                softwareGain = gainOptions[Math.max(0, Math.min(position, gainOptions.length - 1))];
                preferences.edit().putFloat("microphone_gain", softwareGain).apply();
                diagnosticEvent(String.format(java.util.Locale.US,
                        "Software microphone gain set to %.1fx", softwareGain));
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });
        findViewById(R.id.gain_reset_button).setOnClickListener(view -> gainSpinner.setSelection(0));
        wakeStateText = findViewById(R.id.wake_state_text);
        wakeModelText = findViewById(R.id.wake_model_text);
        wakeConfidenceText = findViewById(R.id.wake_confidence_text);
        wakeCountText = findViewById(R.id.wake_count_text);
        wakeLastText = findViewById(R.id.wake_last_text);
        wakeInferenceText = findViewById(R.id.wake_inference_text);
        wakeToggle.setChecked(preferences.getBoolean("wake_enabled", false));
        wakeToggle.setOnCheckedChangeListener((button, enabled) -> {
            preferences.edit().putBoolean("wake_enabled", enabled).apply();
            diagnosticEvent("Wake listener " + (enabled ? "enabled" : "disabled"));
            if (!enabled) {
                stopWakeListening("disabled by user");
                setWakeState("Stopped");
            } else {
                setWakeState("Stopped");
                checkConnection(false);
            }
        });
        if (savedInstanceState != null)
            localTokenImported = savedInstanceState.getBoolean("localTokenImported");
        removeLocalTokenButton.setEnabled(localTokenImported);
        api = new SonicApi(this);
        panel = new PanelController(this, api, network);
        configureResponsiveLayout();
        if (isLivingRoomTablet()) {
            getWindow().getDecorView().post(this::hideLivingRoomCardChrome);
        }
        enterKioskModeIfProvisioned();
        // Use the shared MQTT audio path across both tablet generations so
        // newer office hardware can interoperate with Fire OS 5 tablets.
        // WebRTC remains staged for a future server media bridge.
        intercom = new IntercomController(this, microphone,
                findViewById(R.id.intercom_target_one), findViewById(R.id.intercom_target_two));
        intercom.start();
        Map<String, Button> shopButtons = new HashMap<>();
        shopButtons.put("bench1_5v", findViewById(R.id.shop_bench1_5v));
        shopButtons.put("bench1_12v", findViewById(R.id.shop_bench1_12v));
        shopButtons.put("bench2_5v", findViewById(R.id.shop_bench2_5v));
        shopButtons.put("bench2_12v", findViewById(R.id.shop_bench2_12v));
        shopButtons.put("bench3_5v", findViewById(R.id.shop_bench3_5v));
        shopButtons.put("bench3_12v", findViewById(R.id.shop_bench3_12v));
        View shopCard = findViewById(R.id.shop_card);
        if (isLivingRoomTablet() || isBedroomTablet()) {
            shopCard.setVisibility(View.GONE);
        } else {
            shopController = new ShopController(network, findViewById(R.id.shop_status), findViewById(R.id.shop_all_off), shopButtons);
            shopController.start();
        }
        // These are optional integrations. Do not let a Fire OS camera/MQTT
        // implementation failure prevent the dashboard from opening.
        try {
            mqttScreen = new MqttScreenController(this);
            mqttScreen.start();
        } catch (RuntimeException failure) {
            android.util.Log.e("SonicSatellite", "Optional MQTT startup failed", failure);
        }
        try {
            startCameraMotionWakeIfPermitted();
        } catch (RuntimeException failure) {
            android.util.Log.e("SonicSatellite", "Optional camera wake startup failed", failure);
        }
        recordButton.setOnClickListener(view -> startWhenPermitted());
        sendButton.setOnClickListener(view -> sendRecording());
        findViewById(R.id.settings_record_button).setOnClickListener(view -> startWhenPermitted());
        findViewById(R.id.settings_send_button).setOnClickListener(view -> sendRecording());
        findViewById(R.id.settings_menu_button).setOnClickListener(this::showSettingsMenu);
        findViewById(R.id.homecontrol_header).setOnLongClickListener(view -> {
            showSettingsPage();
            diagnosticEvent("Settings opened by HomeControl header long-press");
            return true;
        });
        findViewById(R.id.settings_return_button).setOnClickListener(view -> hideSettingsPage());
        findViewById(R.id.test_button).setOnClickListener(view -> checkConnection(true));
        findViewById(R.id.import_token_button).setOnClickListener(view -> chooseFile(IMPORT_TOKEN_REQUEST));
        findViewById(R.id.import_local_token_button).setOnClickListener(view -> importLocalTokenWhenPermitted());
        removeLocalTokenButton.setOnClickListener(view -> confirmRemoveLocalToken());
        findViewById(R.id.import_ca_button).setOnClickListener(view -> chooseFile(IMPORT_CA_REQUEST));
        findViewById(R.id.import_local_ca_button).setOnClickListener(view -> importLocalCaWhenPermitted());
        updateButtons();
        diagnosticEvent("Dashboard ready; settings available from overflow menu or header long-press");
    }

    private void hideSystemChrome() {
        getWindow().getDecorView().setSystemUiVisibility(
                android.view.View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                        | android.view.View.SYSTEM_UI_FLAG_FULLSCREEN
                        | android.view.View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | android.view.View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                        | android.view.View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                        | android.view.View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
    }

    @Override public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) hideSystemChrome();
    }

    private void showSettingsMenu(android.view.View anchor) {
        android.widget.PopupMenu menu = new android.widget.PopupMenu(this, anchor);
        menu.getMenu().add("Sonic Settings");
        menu.getMenu().add("Panel Configuration");
        menu.setOnMenuItemClickListener(item -> {
            if ("Panel Configuration".contentEquals(item.getTitle())) {
                showPanelConfiguration();
            } else {
                showSettingsPage();
                diagnosticEvent("Settings opened from overflow menu");
            }
            return true;
        });
        menu.show();
    }

    private void showPanelConfiguration() {
        if (panel != null) panel.stop();
        new AlertDialog.Builder(this)
                .setTitle("Panel Configuration")
                .setMessage("Panel definitions are server-authoritative. The Android client accepts only configured entities and fixed actions from Server1.\n\nVerified entity in this project: light.living_room_glow_all\n\nServer1 must expose /panel/config and the reviewed authenticated configuration-update endpoint before editing is enabled.")
                .setNegativeButton("Cancel", (d, w) -> { if (panel != null && settingsPage.getVisibility() != android.view.View.VISIBLE) panel.start(); })
                .setPositiveButton("Sonic Settings", (d, w) -> showSettingsPage())
                .show();
    }

    private void showSettingsPage() {
        if (panel != null) panel.stop();
        settingsPage.setVisibility(android.view.View.VISIBLE);
        settingsPage.bringToFront();
        android.util.Log.i("SonicSatellite", "Activity screen transition: Dashboard -> Settings"
                + "; voiceInstance=" + voiceOwnerIdentity + "; state=" + captureState);
    }

    private void hideSettingsPage() {
        settingsPage.setVisibility(android.view.View.GONE);
        if (panel != null) panel.start();
        diagnosticEvent("Returned to Dashboard; audio owner retained");
        android.util.Log.i("SonicSatellite", "Activity screen transition: Settings -> Dashboard"
                + "; voiceInstance=" + voiceOwnerIdentity + "; state=" + captureState);
    }

    @Override public void onBackPressed() {
        if (settingsPage != null && settingsPage.getVisibility() == android.view.View.VISIBLE) {
            hideSettingsPage();
            return;
        }
        super.onBackPressed();
    }

    @Override protected void onSaveInstanceState(Bundle outState) {
        outState.putBoolean("localTokenImported", localTokenImported);
        super.onSaveInstanceState(outState);
    }

    @Override protected void onResume() {
        super.onResume();
        enterKioskModeIfProvisioned();
        if (keyguardLock != null) {
            try { keyguardLock.disableKeyguard(); } catch (RuntimeException ignored) { }
        }
        visible = true;
        if (panel != null && settingsPage.getVisibility() != android.view.View.VISIBLE) panel.start();
        android.util.Log.i("SonicSatellite", "Activity onResume; screen="
                + (settingsPage != null && settingsPage.getVisibility() == android.view.View.VISIBLE
                ? "Settings" : "Dashboard") + "; wakeEnabled=" + wakeToggle.isChecked()
                + "; policyGranted=" + policyGranted + "; wakeRequested=" + wakeRequested);
        handler.removeCallbacks(poll);
        handler.post(poll);
        if (recordAttemptPending && !awaitingMicrophonePermission) checkConnection(false);
    }

    private void enterKioskModeIfProvisioned() {
        try {
            DevicePolicyManager policy = (DevicePolicyManager) getSystemService(DEVICE_POLICY_SERVICE);
            android.content.ComponentName admin = new android.content.ComponentName(this, SonicDeviceAdminReceiver.class);
            if (policy != null && policy.isDeviceOwnerApp(getPackageName())) {
                policy.setLockTaskPackages(admin, new String[]{getPackageName()});
                if (Build.VERSION.SDK_INT >= 21) startLockTask();
            }
        } catch (RuntimeException failure) {
            android.util.Log.w("SonicSatellite", "Kiosk mode unavailable", failure);
        }
    }

    @Override protected void onPause() {
        visible = false;
        if (intercom != null) intercom.stopTransmitting();
        if (panel != null) panel.stop();
        android.util.Log.i("SonicSatellite", "Activity onPause; wakeRequested=" + wakeRequested
                + "; state=" + captureState);
        if (!awaitingMicrophonePermission) {
            boolean wasPending = recordAttemptPending;
            recordAttemptPending = false;
            if (wasPending && !recording) statusText.setText(R.string.status_idle);
        }
        // The dashboard and settings are one activity, and the wake owner is
        // intentionally independent of the visible panel. Do not release the
        // authoritative AudioRecord merely because a panel loses focus.
        updateButtons();
        super.onPause();
    }

    private void chooseFile(int requestCode) {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("*/*");
        startActivityForResult(intent, requestCode);
    }

    private void importLocalCaWhenPermitted() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                && ContextCompat.checkSelfPermission(this, Manifest.permission.READ_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED) {
            importStatusText.setText("CA import: Requesting storage permission");
            ActivityCompat.requestPermissions(this,
                    new String[]{Manifest.permission.READ_EXTERNAL_STORAGE}, LOCAL_CA_PERMISSION_REQUEST);
            return;
        }
        importStatusText.setText("CA import: Reading local certificate…");
        allowed = false;
        updateButtons();
        network.execute(() -> {
            String result;
            try {
                api.importLocalCa();
                result = "CA import: Local root CA imported successfully";
            } catch (java.io.FileNotFoundException e) {
                result = "CA import failed: /sdcard/Download/sonic-caddy-root.crt was not found or cannot be read";
            } catch (SecurityException e) {
                result = "CA import failed: Storage permission is required to read Downloads";
            } catch (Exception e) {
                result = "CA import failed: Invalid CA certificate or unreadable file";
            }
            final String message = result;
            runOnUiThread(() -> {
                if (destroyed) return;
                importStatusText.setText(message);
                checkConnection(false);
            });
        });
    }

    private void importLocalTokenWhenPermitted() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                && ContextCompat.checkSelfPermission(this, Manifest.permission.READ_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED) {
            importStatusText.setText("Credential import: Requesting storage permission");
            ActivityCompat.requestPermissions(this,
                    new String[]{Manifest.permission.READ_EXTERNAL_STORAGE}, LOCAL_TOKEN_PERMISSION_REQUEST);
            return;
        }
        importStatusText.setText("Credential import: Reading local file…");
        allowed = false;
        updateButtons();
        network.execute(() -> {
            boolean imported;
            try {
                api.importLocalToken();
                imported = true;
            } catch (Exception e) {
                imported = false;
            }
            final boolean success = imported;
            runOnUiThread(() -> {
                if (destroyed) return;
                localTokenImported = success;
                removeLocalTokenButton.setEnabled(success);
                importStatusText.setText(success ? "API Credential Imported Successfully"
                        : "Credential import failed: File missing, unreadable, or invalid");
                checkConnection(false);
                if (success) confirmRemoveLocalToken();
            });
        });
    }

    private void confirmRemoveLocalToken() {
        if (!localTokenImported) return;
        new AlertDialog.Builder(this)
                .setTitle("Remove source credential file?")
                .setMessage("Delete /sdcard/Download/sonic-fire7-credential.txt? The imported private credential will remain available.")
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Delete source file", (dialog, which) -> {
                    removeLocalTokenConfirmed = true;
                    removeLocalTokenWhenPermitted();
                })
                .show();
    }

    private void removeLocalTokenWhenPermitted() {
        if (!localTokenImported || !removeLocalTokenConfirmed) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                && ContextCompat.checkSelfPermission(this, Manifest.permission.WRITE_EXTERNAL_STORAGE)
                != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this,
                    new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE}, REMOVE_LOCAL_TOKEN_PERMISSION_REQUEST);
            return;
        }
        removeLocalTokenConfirmed = false;
        network.execute(() -> {
            boolean removed;
            try {
                removed = api.removeLocalTokenSource();
            } catch (SecurityException e) {
                removed = false;
            }
            final boolean success = removed;
            runOnUiThread(() -> {
                if (destroyed) return;
                if (success) {
                    localTokenImported = false;
                    removeLocalTokenButton.setEnabled(false);
                }
                importStatusText.setText(success ? "Source credential file removed; private credential retained"
                        : "Source credential file could not be removed");
            });
        });
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK || data == null || data.getData() == null) return;
        if (requestCode != IMPORT_TOKEN_REQUEST && requestCode != IMPORT_CA_REQUEST) return;
        Uri uri = data.getData();
        allowed = false;
        updateButtons();
        network.execute(() -> {
            String message;
            try {
                if (requestCode == IMPORT_TOKEN_REQUEST) {
                    api.importToken(uri);
                    message = "Credential imported";
                } else {
                    api.importCa(uri);
                    message = "Root CA imported";
                }
            } catch (Exception e) {
                message = "Import failed: invalid or unreadable file";
            }
            final String result = message;
            runOnUiThread(() -> {
                if (destroyed) return;
                if (requestCode == IMPORT_CA_REQUEST) importStatusText.setText(result);
                else errorText.setText(result);
                checkConnection(requestCode == IMPORT_TOKEN_REQUEST);
            });
        });
    }

    private void updateButtons() {
        recordButton.setEnabled(visible && allowed && !recording && !uploading && !recordAttemptPending);
        sendButton.setEnabled(visible && allowed && !recording && !uploading
                && !recordAttemptPending && latestWav != null);
    }

    private void checkConnection(boolean explicit) {
        if (checking) {
            if (explicit) connectionText.setText("Server Connection: CHECKING");
            return;
        }
        checking = true;
        allowed = false;
        updateButtons();
        connectionText.setText("Server Connection: CHECKING");
        muteText.setText("Global Mute: CHECKING");
        network.execute(() -> {
            boolean healthy = false;
            boolean muted = true;
            String connectionStatus;
            String policyStatus = "UNAVAILABLE";
            String detail = null;
            boolean credential = api.hasCredential();
            try {
                if (!api.hasCa()) {
                    connectionStatus = "CA NOT CONFIGURED";
                    detail = "Import the Caddy root CA";
                } else {
                    int status = api.health();
                    if (status >= 200 && status < 300) {
                        healthy = true;
                        connectionStatus = "CONNECTED (HTTP " + status + ")";
                        if (!credential) {
                            policyStatus = "CREDENTIAL NOT CONFIGURED";
                        } else {
                            try {
                                muted = api.globalMute();
                                policyStatus = muted ? "MUTED" : "UNMUTED";
                            } catch (Exception e) {
                                String reason = safeError(e);
                                policyStatus = reason.contains("HTTP 401") || reason.contains("HTTP 403")
                                        ? "AUTHENTICATION REQUIRED" : "UNAVAILABLE";
                                detail = "Microphone policy: " + safeError(e);
                            }
                        }
                    } else if (status == 401 || status == 403) {
                        connectionStatus = "AUTHENTICATION REQUIRED (HTTP " + status + ")";
                        detail = "Health endpoint requires authentication";
                    } else {
                        connectionStatus = "HTTP ERROR " + status;
                        detail = "Health endpoint returned HTTP " + status;
                    }
                }
            } catch (Exception e) {
                connectionStatus = healthError(e);
                detail = connectionStatus;
            }
            final boolean policyOk = healthy && credential && detail == null;
            final boolean isMuted = muted;
            policyGranted = policyOk && !isMuted;
            if (!policyGranted) {
                cancelled = true;
                stopWakeListening("global policy unavailable or muted");
                captureState = policyOk && isMuted ? CaptureState.MUTED : CaptureState.DISCONNECTED;
            }
            final String info = detail;
            final String healthStatus = connectionStatus;
            final String muteStatus = policyStatus;
            final boolean hasCredential = credential;
            android.util.Log.i("SonicSatellite", "Policy result: health=" + healthStatus
                    + "; policy=" + muteStatus + "; credentialConfigured=" + hasCredential
                    + "; policyGranted=" + policyGranted + "; screen="
                    + (settingsPage != null && settingsPage.getVisibility() == android.view.View.VISIBLE
                    ? "Settings" : "Dashboard"));
            runOnUiThread(() -> {
                if (destroyed) return;
                checking = false;
                allowed = policyOk && !isMuted;
                if (!allowed) cancelled = true;
                connectionText.setText("Server Connection: " + healthStatus);
                credentialText.setText(hasCredential ? "Credential: CONFIGURED"
                        : "Credential: CREDENTIAL NOT CONFIGURED");
                muteText.setText("Global Mute: " + muteStatus);
                if (!wakeToggle.isChecked()) setWakeState("Stopped");
                else if (!policyGranted) setWakeState(policyOk && isMuted ? "Muted" : "Disconnected");
                if (explicit || info != null) errorText.setText(info == null ? "Error: None" : "Error: " + info);
                boolean startRequested = recordAttemptPending && !awaitingMicrophonePermission;
                if (startRequested) {
                    recordAttemptPending = false;
                    if (allowed) {
                        startRecording();
                    } else {
                        statusText.setText(R.string.status_recording_blocked);
                        if (policyOk && isMuted) errorText.setText(R.string.error_global_mute);
                    }
                }
                updateButtons();
                syncWakeListening();
            });
        });
    }

    private static String healthError(Exception e) {
        if (e instanceof SSLException || e instanceof java.security.GeneralSecurityException)
            return "CERTIFICATE ERROR";
        if (e instanceof SocketTimeoutException) return "TIMEOUT";
        if (e instanceof ConnectException || e instanceof NoRouteToHostException
                || e instanceof UnknownHostException) return "CONNECTION FAILED";
        if (e instanceof java.io.FileNotFoundException) return "CA NOT CONFIGURED";
        return "CONNECTION FAILED";
    }

    private static String safeError(Exception e) {
        if (e instanceof java.io.FileNotFoundException) return "Import credential and CA first";
        if (e instanceof javax.net.ssl.SSLException || e instanceof java.security.GeneralSecurityException)
            return "TLS certificate or Server1 IP verification failed";
        String msg = e.getMessage();
        if (msg != null && (msg.startsWith("Credential rejected") || msg.startsWith("Global mute")
                || msg.startsWith("Server returned HTTP") || msg.startsWith("Invalid microphone policy")
                || msg.startsWith("Import credential"))) return msg;
        return "Server unavailable or response invalid";
    }

    private void sendRecording() {
        if (!allowed || latestWav == null || uploading) return;
        File wav = latestWav;
        final boolean fromWake = uploadFromWake;
        if (activeCommandGeneration == 0) activeCommandGeneration = ++nextCommandGeneration;
        final long generation = activeCommandGeneration;
        uploading = true;
        captureState = CaptureState.PROCESSING_COMMAND;
        logStage("Upload started generation=" + generation, SystemClock.elapsedRealtime());
        if (fromWake) runOnUiThread(() -> { if (!destroyed) setWakeState("Processing"); });
        updateButtons();
        transcriptionText.setText("Whisper: Waiting…");
        haText.setText("Home Assistant: Waiting…");
        if (uploadWatchdog != null) handler.removeCallbacks(uploadWatchdog);
        uploadWatchdog = () -> {
            if (activeCommandGeneration != generation || !uploading) return;
            android.util.Log.e("SonicSatellite", "Command watchdog expired generation=" + generation);
            uploading = false;
            activeCommandGeneration = 0;
            uploadFromWake = false;
            captureState = CaptureState.ERROR;
            statusText.setText("Status: Command upload timed out");
            errorText.setText("Error: Command upload timed out; no automatic retry");
            setWakeState("Error — command upload timeout");
            updateButtons();
            if (policyGranted && wakeToggle.isChecked()) {
                captureState = CaptureState.LISTENING;
                setWakeState("Listening");
            }
            checkConnection(false);
        };
        handler.postDelayed(uploadWatchdog, UPLOAD_WATCHDOG_MS);
        network.execute(() -> {
            String transcript = null;
            String response = null;
            String failure = null;
            try {
                if (!policyGranted) throw new IOException("Global mute policy is unavailable");
                int healthStatus = api.health();
                if (healthStatus < 200 || healthStatus >= 300)
                    throw new IOException("Server returned HTTP " + healthStatus);
                if (api.globalMute()) {
                    policyGranted = false;
                    throw new IOException("Global mute is active");
                }
                if (!policyGranted) throw new IOException("Global mute policy changed");
                JSONObject result = api.upload(wav);
                logStage("Server response received generation=" + generation,
                        SystemClock.elapsedRealtime());
                transcript = SonicApi.transcript(result);
                response = SonicApi.haResult(result);
            } catch (Exception e) {
                failure = safeError(e);
            }
            final String t = transcript, r = response, f = failure;
            runOnUiThread(() -> {
                if (activeCommandGeneration != generation) {
                    android.util.Log.w("SonicSatellite", "Ignoring stale upload callback generation="
                            + generation + "; active=" + activeCommandGeneration);
                    return;
                }
                if (uploadWatchdog != null) handler.removeCallbacks(uploadWatchdog);
                activeCommandGeneration = 0;
                uploading = false;
                if (f == null) {
                    statusText.setText("Status: Command complete");
                    transcriptionText.setText("Whisper: " + t);
                    haText.setText("Home Assistant: " + r);
                    if (diagnosticTranscriptionLogging)
                        android.util.Log.i("SonicSatellite", "Whisper transcription=" + t);
                    android.util.Log.i("SonicSatellite", "Home Assistant result received");
                    diagnosticEvent("Whisper transcription and Home Assistant response received");
                } else {
                    statusText.setText("Status: Command failed");
                    transcriptionText.setText("Whisper: —");
                    haText.setText("Home Assistant: —");
                    errorText.setText("Error: " + f);
                }
                updateButtons();
                if (fromWake) {
                    uploadFromWake = false;
                    captureState = f == null ? CaptureState.LISTENING : CaptureState.ERROR;
                    setWakeState(f == null ? "Listening" : "Error — command upload failed");
                    android.util.Log.i("SonicSatellite", "Return to listening generation="
                            + generation + " result=" + (f == null ? "success" : "error"));
                    diagnosticEvent("Wake listener ready again");
                } else {
                    captureState = f == null ? CaptureState.IDLE : CaptureState.ERROR;
                }
                checkConnection(false);
            });
        });
    }

    private void startWhenPermitted() {
        if (recording || uploading || recordAttemptPending || !allowed) return;
        // A new attempt must never leave the prior command available to send.
        latestWav = null;
        fileText.setText(R.string.file_none);
        recordAttemptPending = true;
        updateButtons();
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            awaitingMicrophonePermission = true;
            statusText.setText(R.string.status_permission);
            ActivityCompat.requestPermissions(this,
                    new String[]{Manifest.permission.RECORD_AUDIO}, MICROPHONE_PERMISSION_REQUEST);
            return;
        }
        statusText.setText(R.string.status_checking_policy);
        checkConnection(false);
    }

    private void startCameraMotionWakeIfPermitted() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                && ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, new String[]{Manifest.permission.CAMERA},
                    CAMERA_PERMISSION_REQUEST);
            return;
        }
        Intent intent = new Intent(this, CameraMotionWakeService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent);
        else startService(intent);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == CAMERA_PERMISSION_REQUEST) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                try {
                    startCameraMotionWakeIfPermitted();
                } catch (RuntimeException failure) {
                    android.util.Log.e("SonicSatellite", "Optional camera wake startup failed", failure);
                }
            } else {
                android.util.Log.w("CameraMotionWake", "Camera permission denied; motion wake disabled");
            }
            return;
        }
        if (requestCode == LOCAL_TOKEN_PERMISSION_REQUEST) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED)
                importLocalTokenWhenPermitted();
            else importStatusText.setText("Credential import failed: Storage permission denied");
            return;
        }
        if (requestCode == REMOVE_LOCAL_TOKEN_PERMISSION_REQUEST) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED)
                removeLocalTokenWhenPermitted();
            else {
                removeLocalTokenConfirmed = false;
                importStatusText.setText("Source removal failed: Storage permission denied");
            }
            return;
        }
        if (requestCode == LOCAL_CA_PERMISSION_REQUEST) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                importLocalCaWhenPermitted();
            } else {
                importStatusText.setText("CA import failed: Storage permission denied");
            }
            return;
        }
        if (requestCode != MICROPHONE_PERMISSION_REQUEST) return;
        awaitingMicrophonePermission = false;
        if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            wakePermissionRequested = false;
            statusText.setText(R.string.status_checking_policy);
            if (visible) checkConnection(false);
        } else {
            wakePermissionRequested = true;
            recordAttemptPending = false;
            statusText.setText(R.string.status_idle);
            errorText.setText(R.string.error_permission);
            if (wakeToggle.isChecked()) setWakeState("Error — microphone permission denied");
            updateButtons();
        }
    }

    private void startRecording() {
        if (!allowed || recording) return;
        recording = true;
        captureState = CaptureState.IDLE;
        stopWakeListening("manual recording requested");
        setWakeState("Stopped");
        cancelled = false;
        updateButtons();
        statusText.setText(R.string.status_recording);
        elapsedText.setText(getString(R.string.elapsed_value, 0.0));
        sizeText.setText(getString(R.string.size_value, 0));
        fileText.setText(R.string.file_none);
        errorText.setText(R.string.error_none);
        microphone.execute(this::recordFiveSeconds);
    }

    private void recordFiveSeconds() {
        AudioRecord recorder = null;
        AgcSession agc = null;
        File wavFile = null;
        long audioBytes = 0;
        long elapsedMs = 0;
        String failure = null;
        try {
            int minimumBuffer = AudioRecord.getMinBufferSize(SAMPLE_RATE,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
            android.util.Log.i("OpenWakeWord", "Microphone initialization: manual recording minBuffer="
                    + minimumBuffer);
            if (minimumBuffer <= 0) {
                throw new IOException("16 kHz mono recording is unavailable (code " + minimumBuffer + ")");
            }
            recorder = new AudioRecord(MediaRecorder.AudioSource.MIC, SAMPLE_RATE,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
                    Math.max(minimumBuffer, 3200));
            if (recorder.getState() != AudioRecord.STATE_INITIALIZED) {
                throw new IOException("Microphone could not be initialized");
            }
            agc = inspectAgc(recorder);
            File recordings = new File(getFilesDir(), "recordings");
            if (!recordings.isDirectory() && !recordings.mkdirs()) {
                throw new IOException("Could not create the recordings directory");
            }
            wavFile = new File(recordings, "sonic-" + System.currentTimeMillis() + ".wav");
            try (RandomAccessFile output = new RandomAccessFile(wavFile, "rw")) {
                output.setLength(0);
                writeWavHeader(output, 0);
                recorder.startRecording();
                if (recorder.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) {
                    throw new IOException("Microphone did not start recording");
                }
                android.util.Log.i("OpenWakeWord", "Microphone recording started; manual recording");
                long startMs = SystemClock.elapsedRealtime();
                short[] raw = new short[1600];
                short[] conditioned = new short[1600];
                while (!cancelled && audioBytes < MAX_AUDIO_BYTES) {
                    elapsedMs = SystemClock.elapsedRealtime() - startMs;
                    if (elapsedMs >= 5000) break;
                    int remainingSamples = (int) ((MAX_AUDIO_BYTES - audioBytes) / 2);
                    int count = recorder.read(raw, 0, Math.min(raw.length, remainingSamples));
                    if (count < 0) {
                        android.util.Log.e("OpenWakeWord", "Audio read error during manual recording code=" + count);
                        throw new IOException("Microphone read failed (code " + count + ")");
                    }
                    if (count == 0) continue;
                    int clipped = conditionPcm(raw, conditioned, count);
                    reportInputLevels(raw, conditioned, count, clipped);
                    for (int i = 0; i < count; i++) writeLittleEndian(output, conditioned[i] & 0xffff, 2);
                    audioBytes += count * 2L;
                    final long progressBytes = audioBytes;
                    final double progressSeconds = Math.min(5.0,
                            (SystemClock.elapsedRealtime() - startMs) / 1000.0);
                    runOnUiThread(() -> {
                        if (!destroyed) {
                            elapsedText.setText(getString(R.string.elapsed_value, progressSeconds));
                            sizeText.setText(getString(R.string.size_value, 44 + progressBytes));
                        }
                    });
                }
                elapsedMs = Math.min(5000, SystemClock.elapsedRealtime() - startMs);
                if (cancelled) throw new IOException("Recording cancelled");
                if (audioBytes == 0) throw new IOException("Microphone returned no audio");
                output.seek(0);
                writeWavHeader(output, audioBytes);
            }
        } catch (IOException | RuntimeException exception) {
            failure = exception.getMessage();
            if (failure == null || failure.isEmpty()) failure = exception.getClass().getSimpleName();
            if (wavFile != null && wavFile.exists() && !wavFile.delete()) {
                failure += "; could not remove incomplete WAV";
            }
        } finally {
            if (agc != null) agc.close();
            hardwareAgcActive = false;
            if (recorder != null) {
                try {
                    if (recorder.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING) recorder.stop();
                    android.util.Log.i("OpenWakeWord", "Microphone recording stopped; manual recording");
                } catch (IllegalStateException ignored) {
                    // Release the microphone even if the device refuses to stop cleanly.
                }
                recorder.release();
            }
        }
        final String resultError = failure;
        final File resultFile = wavFile;
        final long resultBytes = audioBytes;
        final double resultSeconds = elapsedMs / 1000.0;
        runOnUiThread(() -> {
            if (destroyed) return;
            recording = false;
            updateButtons();
            if (resultError == null) {
                latestWav = resultFile;
                statusText.setText(R.string.status_saved);
                elapsedText.setText(getString(R.string.elapsed_value, resultSeconds));
                sizeText.setText(getString(R.string.size_value, 44 + resultBytes));
                fileText.setText(getString(R.string.file_value, resultFile.getAbsolutePath()));
            } else {
                statusText.setText(R.string.status_failed);
                errorText.setText(getString(R.string.error_value, resultError));
            }
            updateButtons();
            policyGranted = false;
            checkConnection(false);
        });
    }

    private void setWakeState(String state) {
        if (state.equals(lastPublishedWakeState)) return;
        lastPublishedWakeState = state;
        wakeStateText.setText("Wake Word: " + state);
        if (recordButton != null) {
            String label;
            if (state.startsWith("Listening")) label = "JARVIS\nLISTENING";
            else if (state.startsWith("Wake Word")) label = "JARVIS\nDETECTED";
            else if (state.startsWith("Recording")) label = "JARVIS\nRECORDING";
            else if (state.startsWith("Processing")) label = "JARVIS\nPROCESSING";
            else if (state.startsWith("Muted")) label = "JARVIS\nMUTED";
            else if (state.startsWith("Disconnected")) label = "JARVIS\nOFFLINE";
            else if (state.startsWith("Error")) label = "JARVIS\nERROR";
            else label = "JARVIS\n" + state.toUpperCase(java.util.Locale.US);
            recordButton.setText(label);
            recordButton.setContentDescription("Jarvis " + state);
            recordButton.setBackgroundResource(state.startsWith("Listening")
                    ? R.drawable.jarvis_active_button : R.drawable.jarvis_listening_button);
        }
        diagnosticEvent("Wake state: " + state);
    }

    private void diagnosticEvent(String event) {
        String line = DateFormat.format("HH:mm:ss", System.currentTimeMillis()) + "  " + event;
        android.util.Log.i("SonicSatellite", event);
        if (diagnosticEvents == null) return;
        eventLog.insert(0, line + "\n");
        while (eventLog.length() > 2400) eventLog.setLength(2400);
        diagnosticEvents.setText("Diagnostic events:\n" + eventLog.toString());
    }

    private void syncWakeListening() {
        if (!wakeToggle.isChecked()) {
            android.util.Log.i("SonicSatellite", "Wake listener not started: wake enabled=false");
            return;
        }
        if (!policyGranted) {
            android.util.Log.i("SonicSatellite", "Wake listener not started: policyGranted=false");
            return;
        }
        if (recording || destroyed) return;
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            setWakeState("Error — microphone permission required");
            if (!wakePermissionRequested) {
                wakePermissionRequested = true;
                ActivityCompat.requestPermissions(this,
                        new String[]{Manifest.permission.RECORD_AUDIO}, MICROPHONE_PERMISSION_REQUEST);
            }
            return;
        }
        int session;
        synchronized (wakeAudioLock) {
            if (wakeRequested) return;
            cancelled = false;
            wakeRequested = true;
            session = ++wakeSession;
            microphone.execute(() -> listenForWakeWord(session));
        }
        android.util.Log.i("SonicSatellite", "Wake listener requested; instance="
                + voiceOwnerIdentity + "; session=" + session + "; state=" + captureState);
        setWakeState("Initializing");
    }

    private boolean isLivingRoomTablet() {
        String serial = Build.SERIAL;
        String androidId = Settings.Secure.getString(getContentResolver(), Settings.Secure.ANDROID_ID);
        return "G0W0MB068265F04A".equals(serial) || "70071a26b3ce6ab1".equals(androidId);
    }

    private boolean isBedroomTablet() {
        String serial = Build.SERIAL;
        String androidId = Settings.Secure.getString(getContentResolver(), Settings.Secure.ANDROID_ID);
        return "G0W0MB068265F06A".equals(serial) || "293601fcb83c4e73".equals(androidId);
    }

    private boolean isOfficeTablet() {
        String serial = Build.SERIAL;
        String androidId = Settings.Secure.getString(getContentResolver(), Settings.Secure.ANDROID_ID);
        return "G0W0T9059434F6JG".equals(serial) || "c27a72a92885f103".equals(androidId);
    }

    private boolean isPortraitTablet() {
        return getResources().getConfiguration().orientation
                == android.content.res.Configuration.ORIENTATION_PORTRAIT;
    }

    private void hideLivingRoomCardChrome() {
        LinearLayout lights = findViewById(R.id.lights_card);
        if (lights != null && lights.getChildAt(0) instanceof LinearLayout) {
            ((LinearLayout) lights.getChildAt(0)).setVisibility(View.GONE);
        }
        LinearLayout climate = findViewById(R.id.climate_card);
        if (climate != null && climate.getChildAt(0) != null) climate.getChildAt(0).setVisibility(View.GONE);
        LinearLayout media = findViewById(R.id.media_card);
        if (media != null && media.getChildAt(0) instanceof LinearLayout) {
            // The media title and power control live together in the content
            // row; remove the decorative card header to keep the card compact.
            media.getChildAt(0).setVisibility(View.GONE);
        }
        View sourcesTitle = findViewById(R.id.sources_title);
        View sourcesDivider = findViewById(R.id.sources_divider);
        if (sourcesTitle != null) sourcesTitle.setVisibility(View.GONE);
        if (sourcesDivider != null) sourcesDivider.setVisibility(View.GONE);
        View lightsState = findViewById(R.id.lights_state);
        View sourceStatus = findViewById(R.id.source_status);
        View shopStatus = findViewById(R.id.shop_status);
        if (lightsState != null) lightsState.setVisibility(View.GONE);
        if (sourceStatus != null) sourceStatus.setVisibility(View.GONE);
        if (shopStatus != null) shopStatus.setVisibility(View.GONE);
    }

    private void configureResponsiveLayout() {
        boolean portrait = isPortraitTablet();
        LinearLayout topCards = findViewById(R.id.dashboard_top_cards);
        LinearLayout bottomCards = findViewById(R.id.dashboard_bottom_cards);
        topCards.setOrientation(portrait ? LinearLayout.VERTICAL : LinearLayout.HORIZONTAL);
        bottomCards.setOrientation(portrait ? LinearLayout.VERTICAL : LinearLayout.HORIZONTAL);
        if (!isBedroomTablet()) {
            configureCardChildren(topCards, portrait);
            configureCardChildren(bottomCards, portrait);
        }
        if (isLivingRoomTablet()) {
            addLivingRoomCardSpacing(topCards);
            addLivingRoomCardSpacing(bottomCards);
            hideLivingRoomCardChrome();
        }

        LinearLayout content = findViewById(R.id.dashboard_content);
        LinearLayout.LayoutParams contentParams = (LinearLayout.LayoutParams) content.getLayoutParams();
        contentParams.height = 0;
        contentParams.weight = 1f;
        content.setLayoutParams(contentParams);

        if (portrait) {
            // Keep the final Shop row above the bottom intercom overlay.
            content.setPadding(content.getPaddingLeft(), content.getPaddingTop(),
                    content.getPaddingRight(), isLivingRoomTablet() ? dp(76) : dp(50));
            configurePortraitShopCard();
            configurePortraitFooter();
        } else {
            content.setPadding(content.getPaddingLeft(), content.getPaddingTop(),
                    content.getPaddingRight(), isLivingRoomTablet() ? dp(76) : 0);
        }
    }

    private void configureCardChildren(LinearLayout container, boolean portrait) {
        for (int i = 0; i < container.getChildCount(); i++) {
            View child = container.getChildAt(i);
            LinearLayout.LayoutParams params = (LinearLayout.LayoutParams) child.getLayoutParams();
            if (portrait) {
                params.width = LinearLayout.LayoutParams.MATCH_PARENT;
                params.height = 0;
            } else {
                params.width = 0;
                params.height = LinearLayout.LayoutParams.MATCH_PARENT;
            }
            params.weight = 1f;
            child.setLayoutParams(params);
        }
    }

    private void addLivingRoomCardSpacing(LinearLayout container) {
        int margin = dp(14);
        for (int i = 0; i < container.getChildCount(); i++) {
            View child = container.getChildAt(i);
            LinearLayout.LayoutParams params = (LinearLayout.LayoutParams) child.getLayoutParams();
            params.setMargins(margin, margin, margin, margin);
            child.setLayoutParams(params);
            child.setPadding(dp(7), dp(7), dp(7), dp(7));
        }
    }

    private void configurePortraitFooter() {
        LinearLayout controls = findViewById(R.id.intercom_controls);
        Space spacer = new Space(this);
        controls.addView(spacer, 1, new LinearLayout.LayoutParams(0, 1, 1f));
        FrameLayout.LayoutParams bubble = (FrameLayout.LayoutParams) recordButton.getLayoutParams();
        bubble.width = dp(190);
        bubble.height = dp(28);
        bubble.gravity = Gravity.CENTER;
        recordButton.setLayoutParams(bubble);
        recordButton.setTextSize(9f);
    }

    private void configurePortraitShopCard() {
        if (isOfficeTablet()) return;
        int[] ids = {
                R.id.shop_bench1_5v, R.id.shop_bench1_12v,
                R.id.shop_bench2_5v, R.id.shop_bench2_12v,
                R.id.shop_bench3_5v, R.id.shop_bench3_12v,
                R.id.shop_all_off
        };
        for (int id : ids) {
            Button button = findViewById(id);
            button.setTextSize(12f);
            button.setPadding(0, 0, 0, 0);
            button.setMinHeight(0);
            button.setMinWidth(0);
        }
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private void stopWakeListening(String reason) {
        synchronized (wakeAudioLock) {
            wakeRequested = false;
            ++wakeSession;
            cancelled = true;
            if (wakeRecorder != null) {
                android.util.Log.i("OpenWakeWord", "Listener stop requested; reason=" + reason);
                try { wakeRecorder.stop(); } catch (IllegalStateException ignored) { }
            }
        }
    }

    void prepareForIntercom() {
        stopWakeListening("intercom transmission");
    }

    void setIntercomStatus(String target, boolean active) {
        if (destroyed || recordButton == null) return;
        recordButton.setText(active ? "PTT ACTIVE  •  " + target : "JARVIS  •  LISTENING");
        View ring = findViewById(R.id.ptt_active_ring);
        if (ring != null) ring.setVisibility(active ? View.VISIBLE : View.GONE);
    }

    boolean intercomPolicyGranted() {
        // Intercom has its own MQTT connection and microphone permission. It
        // must remain usable even while Jarvis policy/entity sync is offline.
        return !destroyed;
    }

    private boolean mayListen(int session) {
        return wakeRequested && wakeSession == session && policyGranted && !destroyed;
    }

    private boolean commandMayContinue(int session) {
        return mayListen(session) && !cancelled && commandRecording && !destroyed;
    }

    private static int rms(short[] samples, int count) {
        long sum = 0;
        for (int i = 0; i < count; i++) {
            long value = samples[i];
            sum += value * value;
        }
        return count == 0 ? 0 : (int) Math.sqrt((double) sum / count);
    }

    private static float dbfs(int amplitude) {
        return amplitude <= 0 ? -127f : 20f * (float) Math.log10(amplitude / 32768.0f);
    }

    private static int peak(short[] samples, int count) {
        int maximum = 0;
        for (int i = 0; i < count; i++) maximum = Math.max(maximum, Math.abs((int) samples[i]));
        return maximum;
    }

    private static final class AgcSession implements AutoCloseable {
        final AutomaticGainControl effect;
        final boolean enabled;
        AgcSession(AutomaticGainControl effect, boolean enabled) {
            this.effect = effect;
            this.enabled = enabled;
        }
        @Override public void close() {
            if (effect != null) effect.release();
        }
    }

    private AgcSession inspectAgc(AudioRecord recorder) {
        AutomaticGainControl effect = null;
        boolean enabled = false;
        String status;
        if (!AutomaticGainControl.isAvailable()) {
            status = "unavailable on this device/build";
        } else {
            try {
                effect = AutomaticGainControl.create(recorder.getAudioSessionId());
                enabled = effect != null && effect.getEnabled();
                status = effect == null ? "available, session effect unavailable"
                        : (enabled ? "available and already enabled" : "available, disabled");
            } catch (RuntimeException failure) {
                status = "available, session inspection failed";
                android.util.Log.w("SonicSatellite", "AutomaticGainControl inspection failed: "
                        + failure.getClass().getSimpleName());
            }
        }
        hardwareAgcActive = enabled;
        final String agcStatus = status;
        final boolean agcEnabled = enabled;
        android.util.Log.i("SonicSatellite", "AutomaticGainControl=" + agcStatus
                + "; softwareGain=" + softwareGain
                + (agcEnabled ? "; software gain bypassed to avoid fighting AGC" : ""));
        runOnUiThread(() -> inputAgcText.setText("AutomaticGainControl: " + agcStatus
                + (agcEnabled ? " (software gain bypassed)" : "")));
        return new AgcSession(effect, enabled);
    }

    /** Applies gain once, with saturation. If hardware AGC is already active, raw PCM is retained. */
    private int conditionPcm(short[] raw, short[] conditioned, int count) {
        float factor = hardwareAgcActive ? 1.0f : softwareGain;
        int clipped = 0;
        for (int i = 0; i < count; i++) {
            int value = Math.round(raw[i] * factor);
            if (value > Short.MAX_VALUE) { value = Short.MAX_VALUE; clipped++; }
            else if (value < Short.MIN_VALUE) { value = Short.MIN_VALUE; clipped++; }
            conditioned[i] = (short) value;
        }
        return clipped;
    }

    private void reportInputLevels(short[] raw, short[] conditioned, int count, int clipped) {
        long now = SystemClock.elapsedRealtime();
        if (now - lastMeterUiElapsed < 1000) return;
        lastMeterUiElapsed = now;
        float rawRms = dbfs(rms(raw, count));
        float rawPeak = dbfs(peak(raw, count));
        float conditionedRms = dbfs(rms(conditioned, count));
        float conditionedPeak = dbfs(peak(conditioned, count));
        float clipPercent = count == 0 ? 0f : clipped * 100f / count;
        String levels = String.format(java.util.Locale.US,
                "Input raw: RMS %.1f dBFS  Peak %.1f dBFS | conditioned: RMS %.1f dBFS  Peak %.1f dBFS",
                rawRms, rawPeak, conditionedRms, conditionedPeak);
        String clipping = String.format(java.util.Locale.US,
                clipPercent > 0.1f ? "WARNING: conditioned clipping %.2f%% (%s gain)"
                        : "Clipping: %.2f%% (%s gain)", clipPercent,
                hardwareAgcActive ? "AGC" : String.format(java.util.Locale.US, "%.1fx", softwareGain));
        String phase = captureState == CaptureState.LISTENING ? "LISTENING" : captureState.name();
        android.util.Log.i("SonicSatellite", "phase=" + phase + "; " + levels + "; " + clipping);
        runOnUiThread(() -> {
            if (destroyed) return;
            inputLevelText.setText(levels);
            inputClipText.setText(clipping);
        });
    }

    private File writeCommandWav(short[] samples, int count) throws IOException {
        File recordings = new File(getFilesDir(), "recordings");
        if (!recordings.isDirectory() && !recordings.mkdirs())
            throw new IOException("Could not create the recordings directory");
        File wav = new File(recordings, "sonic-command-" + System.currentTimeMillis() + ".wav");
        try (RandomAccessFile output = new RandomAccessFile(wav, "rw")) {
            writeWavHeader(output, count * 2L);
            for (int i = 0; i < count; i++) writeLittleEndian(output, samples[i] & 0xffff, 2);
        }
        return wav;
    }

    /** Captures on the already-running wake AudioRecord; model and recorder stay owned by the listener. */
    private File recordCommand(AudioRecord recorder, int session, short[] preRoll) throws IOException {
        commandRecording = true;
        captureState = CaptureState.WAITING_FOR_SPEECH;
        final long commandStart = SystemClock.elapsedRealtime();
        logStage("Command recording started", commandStart);
        runOnUiThread(() -> { if (commandMayContinue(session)) setWakeState("Listening for command"); });
        int maxSamples = SAMPLE_RATE * COMMAND_MAX_MS / 1000;
        short[] samples = new short[maxSamples + preRoll.length];
        System.arraycopy(preRoll, 0, samples, 0, preRoll.length);
        int total = preRoll.length;
        short[] frame = new short[OpenWakeWord.CHUNK];
        short[] rawFrame = new short[OpenWakeWord.CHUNK];
        long speechStart = -1;
        long lastSpeech = -1;
        boolean loggedSpeech = false;
        int baselineRms = 0;
        int baselineSamples = 0;
        int speechThreshold = SPEECH_RMS_THRESHOLD;
        try {
            while (commandMayContinue(session)) {
                long now = SystemClock.elapsedRealtime();
                if (now - commandStart >= COMMAND_MAX_MS) break;
                int offset = 0;
                while (offset < frame.length && commandMayContinue(session)) {
                    int n = recorder.read(rawFrame, offset, frame.length - offset);
                    if (n < 0) throw new IOException("Microphone read failed (code " + n + ")");
                    if (n == 0) continue;
                    offset += n;
                }
                if (offset != frame.length) break;
                int clipped = conditionPcm(rawFrame, frame, offset);
                reportInputLevels(rawFrame, frame, offset, clipped);
                if (total + offset > samples.length) break;
                System.arraycopy(frame, 0, samples, total, offset);
                total += offset;
                int level = rms(frame, offset);
                now = SystemClock.elapsedRealtime();
                if (speechStart < 0 && baselineSamples < 12) {
                    baselineRms = baselineSamples == 0 ? level
                            : (baselineRms * baselineSamples + level) / (baselineSamples + 1);
                    baselineSamples++;
                    speechThreshold = Math.max(SPEECH_RMS_THRESHOLD, (int) (baselineRms * 2.2f));
                }
                if (level >= speechThreshold) {
                    if (speechStart < 0) {
                        speechStart = now;
                        captureState = CaptureState.RECORDING_SPEECH;
                        logStage("Speech onset; backgroundRms=" + baselineRms
                                + " threshold=" + speechThreshold, now);
                        runOnUiThread(() -> { if (commandMayContinue(session)) setWakeState("Recording speech"); });
                        loggedSpeech = true;
                    }
                    lastSpeech = now;
                } else if (speechStart >= 0 && now - lastSpeech >= COMMAND_SILENCE_MS) {
                    logStage("Recording finalized after silence", now);
                    break;
                } else if (speechStart < 0 && now - commandStart >= COMMAND_SPEECH_START_TIMEOUT_MS) {
                    logStage("Speech-start timeout", now);
                    break;
                }
            }
            if (!commandMayContinue(session)) throw new IOException("Recording cancelled by microphone policy");
            if (!loggedSpeech) logStage("No speech detected before timeout", SystemClock.elapsedRealtime());
            if (speechStart < 0) return null;
            if (total <= preRoll.length) throw new IOException("Microphone returned no command audio");
            return writeCommandWav(samples, total);
        } finally {
            commandRecording = false;
        }
    }

    private void logStage(String stage, long elapsed) {
        long delta = previousStageElapsed < 0 ? -1 : elapsed - previousStageElapsed;
        previousStageElapsed = elapsed;
        android.util.Log.i("SonicSatellite", stage + " atElapsedMs=" + elapsed
                + (delta < 0 ? "" : " deltaMs=" + delta));
        runOnUiThread(() -> diagnosticEvent(stage));
    }

    private void listenForWakeWord(int session) {
        OpenWakeWord engine = null;
        AudioRecord recorder = null;
        AgcSession agc = null;
        boolean commandSession = false;
        String failure = null;
        float maximumConfidence = 0f;
        float currentConfidence = Float.NaN;
        long lastConfidenceLogElapsed = 0;
        try {
            if (!mayListen(session)) return;
            engine = new OpenWakeWord(getApplicationContext());
            android.util.Log.i("OpenWakeWord", "Model loading succeeded; microphone not yet listening (session "
                    + session + ")");
            runOnUiThread(() -> diagnosticEvent("Three wake-word models loaded"));
            runOnUiThread(() -> {
                if (mayListen(session)) wakeModelText.setText("Model: Ready (openWakeWord Hey Jarvis)");
            });
            int frameLength = OpenWakeWord.CHUNK;
            int minimum = AudioRecord.getMinBufferSize(SAMPLE_RATE,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
            android.util.Log.i("OpenWakeWord", "Microphone initialization: sampleRate=" + SAMPLE_RATE
                    + " channels=1 encoding=PCM_16BIT minBuffer=" + minimum);
            if (minimum <= 0) throw new IOException("16 kHz microphone unavailable");
            recorder = new AudioRecord(MediaRecorder.AudioSource.MIC, SAMPLE_RATE,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
                    Math.max(minimum, frameLength * 4));
            if (recorder.getState() != AudioRecord.STATE_INITIALIZED)
                throw new IOException("Wake microphone could not initialize");
            agc = inspectAgc(recorder);
            synchronized (wakeAudioLock) {
                if (!mayListen(session)) return;
                wakeRecorder = recorder;
                recorder.startRecording();
            }
            android.util.Log.i("OpenWakeWord", "AudioRecord initialized; wake listening started (session "
                    + session + ")");
            runOnUiThread(() -> diagnosticEvent("AudioRecord initialized; wake listening started"));
            captureState = CaptureState.LISTENING;
            runOnUiThread(() -> { if (mayListen(session)) setWakeState("Listening"); });
            short[] rawFrame = new short[frameLength];
            short[] frame = new short[frameLength];
            short[] rolling = new short[SAMPLE_RATE * COMMAND_PREROLL_MS / 1000];
            int rollingSize = 0;
            while (mayListen(session)) {
                int offset = 0;
                while (offset < frameLength && mayListen(session)) {
                    int count = recorder.read(rawFrame, offset, frameLength - offset);
                    if (count < 0) {
                        android.util.Log.e("OpenWakeWord", "Audio read error code=" + count
                                + " offset=" + offset + " requested=" + (frameLength - offset));
                        if (!mayListen(session)) break;
                        throw new IOException("Wake microphone read failed (code " + count + ")");
                    }
                    if (count == 0) {
                        android.util.Log.w("OpenWakeWord", "Audio read returned 0 samples");
                        continue;
                    }
                    offset += count;
                }
                if (!mayListen(session) || offset != frameLength) break;
                int clipped = conditionPcm(rawFrame, frame, frameLength);
                reportInputLevels(rawFrame, frame, frameLength, clipped);
                if (rollingSize + frameLength > rolling.length) {
                    int remove = rollingSize + frameLength - rolling.length;
                    System.arraycopy(rolling, remove, rolling, 0, rollingSize - remove);
                    rollingSize -= remove;
                }
                System.arraycopy(frame, 0, rolling, rollingSize, frameLength);
                rollingSize += frameLength;
                float confidence = engine.process(frame);
                currentConfidence = confidence;
                if (!Float.isNaN(confidence)) maximumConfidence = Math.max(maximumConfidence, confidence);
                long uiNow = SystemClock.elapsedRealtime();
                if (!Float.isNaN(confidence) && uiNow - lastConfidenceLogElapsed >= 1000) {
                    lastConfidenceLogElapsed = uiNow;
                    android.util.Log.i("OpenWakeWord", String.format(java.util.Locale.US,
                            "confidence=%.6f max=%.6f audioFrames=%d classifierInferences=%d",
                            currentConfidence, maximumConfidence, engine.getAudioFrames(),
                            engine.getClassifierInferences()));
                    final float score = confidence;
                    final float maxScore = maximumConfidence;
                    final int audioFrames = engine.getAudioFrames();
                    final int classifierInferences = engine.getClassifierInferences();
                    runOnUiThread(() -> {
                        if (mayListen(session)) wakeConfidenceText.setText(
                                String.format(java.util.Locale.US, "Confidence: %.6f  Max: %.6f",
                                        score, maxScore));
                        if (mayListen(session)) wakeInferenceText.setText("Audio frames: " + audioFrames
                                + "  Classifier inferences: " + classifierInferences);
                    });
                }
                if (confidence >= OpenWakeWord.THRESHOLD) {
                    if (uploading || uploadFromWake) {
                        // Keep the same AudioRecord/model pipeline alive, but
                        // never start a second command while an upload is in flight.
                        continue;
                    }
                    long now = SystemClock.elapsedRealtime();
                    if (now - lastWakeElapsed >= WAKE_COOLDOWN_MS) {
                        lastWakeElapsed = now;
                        long detectedAt = System.currentTimeMillis();
                        android.util.Log.i("OpenWakeWord", String.format(java.util.Locale.US,
                                "Hey Jarvis detected confidence=%.6f timestamp=%d", confidence,
                                detectedAt));
                        captureState = CaptureState.WAKE_DETECTED;
                        logStage("Wake detected", SystemClock.elapsedRealtime());
                        runOnUiThread(() -> {
                            if (!mayListen(session)) return;
                            wakeCount++;
                            wakeCountText.setText("Detections: " + wakeCount);
                            wakeLastText.setText("Last detection: " + DateFormat.format(
                                    "yyyy-MM-dd HH:mm:ss", detectedAt));
                            setWakeState("Wake Word Detected");
                        });
                        short[] preRoll = new short[rollingSize];
                        System.arraycopy(rolling, 0, preRoll, 0, rollingSize);
                        recording = true;
                        commandSession = true;
                        File command = recordCommand(recorder, session, preRoll);
                        recording = false;
                        if (command != null && policyGranted && !cancelled) {
                            activeCommandGeneration = ++nextCommandGeneration;
                            latestWav = command;
                            uploadFromWake = true;
                            captureState = CaptureState.UPLOADING;
                            runOnUiThread(() -> {
                                if (!destroyed) {
                                    statusText.setText("Status: Uploading command…");
                                    transcriptionText.setText("Whisper: Waiting…");
                                    haText.setText("Home Assistant: Waiting…");
                                }
                            });
                            runOnUiThread(this::sendRecording);
                        } else {
                            captureState = CaptureState.LISTENING;
                            runOnUiThread(() -> { if (mayListen(session)) setWakeState("Listening"); });
                        }
                        android.util.Log.i("SonicSatellite", "Wake inference ready; commandState="
                                + captureState + "; AudioRecord/model retained");
                        continue;
                    }
                }
            }
        } catch (Exception | LinkageError e) {
            if (mayListen(session)) {
                failure = e.getClass().getSimpleName() + ": " + e.getMessage();
                android.util.Log.e("OpenWakeWord", "Wake listener failed: " + e.getClass().getSimpleName());
                final String diagnosticFailure = failure;
                runOnUiThread(() -> diagnosticEvent("Wake listener failed: " + diagnosticFailure));
            }
        } finally {
            android.util.Log.i("OpenWakeWord", "Listener stopped; reason="
                    + (failure == null ? "requested" : failure) + " session=" + session
                    + " audioFrames=" + (engine == null ? 0 : engine.getAudioFrames())
                    + " classifierInferences=" + (engine == null ? 0 : engine.getClassifierInferences())
                    + (failure == null ? "" : " error=" + failure));
            synchronized (wakeAudioLock) {
                if (wakeRecorder == recorder) wakeRecorder = null;
                if (agc != null) agc.close();
                hardwareAgcActive = false;
                if (recorder != null) {
                    try {
                        if (recorder.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING) recorder.stop();
                    } catch (IllegalStateException ignored) { }
                    recorder.release();
                }
            }
            if (commandSession) recording = false;
            if (engine != null) engine.close();
            final String error = failure;
            runOnUiThread(() -> {
                if (destroyed || wakeSession != session) return;
                wakeRequested = false;
                if (error != null) {
                    wakeModelText.setText("Model: Error");
                    setWakeState("Error — " + error);
                }
                else if (captureState != CaptureState.UPLOADING
                        && captureState != CaptureState.PROCESSING_COMMAND) setWakeState("Stopped");
            });
        }
    }

    private static void writeWavHeader(RandomAccessFile output, long audioBytes) throws IOException {
        output.writeBytes("RIFF");
        writeLittleEndian(output, 36 + audioBytes, 4);
        output.writeBytes("WAVEfmt ");
        writeLittleEndian(output, 16, 4);
        writeLittleEndian(output, 1, 2);
        writeLittleEndian(output, CHANNELS, 2);
        writeLittleEndian(output, SAMPLE_RATE, 4);
        writeLittleEndian(output, SAMPLE_RATE * CHANNELS * BITS_PER_SAMPLE / 8, 4);
        writeLittleEndian(output, CHANNELS * BITS_PER_SAMPLE / 8, 2);
        writeLittleEndian(output, BITS_PER_SAMPLE, 2);
        output.writeBytes("data");
        writeLittleEndian(output, audioBytes, 4);
    }

    private static void writeLittleEndian(RandomAccessFile output, long value, int bytes)
            throws IOException {
        for (int index = 0; index < bytes; index++) output.write((int) (value >> (8 * index)) & 0xff);
    }

    @Override
    protected void onDestroy() {
        destroyed = true;
        cancelled = true;
        policyGranted = false;
        activeCommandGeneration = 0;
        if (uploadWatchdog != null) handler.removeCallbacks(uploadWatchdog);
        stopWakeListening("activity destroyed");
        if (intercom != null) intercom.shutdown();
        if (shopController != null) shopController.stop();
        if (mqttScreen != null) mqttScreen.shutdown();
        handler.removeCallbacks(poll);
        network.shutdownNow();
        microphone.shutdownNow();
        super.onDestroy();
    }
}
