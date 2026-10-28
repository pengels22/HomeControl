package com.example.sonicsatilite;

import android.os.Build;
import android.provider.Settings;
import android.os.Handler;
import android.os.Looper;
import android.view.Window;
import android.view.WindowManager;
import android.util.Log;

import org.eclipse.paho.client.mqttv3.IMqttActionListener;
import org.eclipse.paho.client.mqttv3.IMqttDeliveryToken;
import org.eclipse.paho.client.mqttv3.IMqttToken;
import org.eclipse.paho.client.mqttv3.MqttAsyncClient;
import org.eclipse.paho.client.mqttv3.MqttCallbackExtended;
import org.eclipse.paho.client.mqttv3.MqttConnectOptions;
import org.eclipse.paho.client.mqttv3.MqttMessage;
import org.eclipse.paho.client.mqttv3.persist.MemoryPersistence;

import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** MQTT screen backlight control. A value of 0 blacks the window; it does not lock the tablet. */
final class MqttScreenController {
    private static final String BASE_TOPIC = "home/tablets";
    private final MainActivity activity;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final String tabletId;
    private final String commandTopic;
    private final String stateTopic;
    private final String brightnessCommandTopic;
    private final String brightnessStateTopic;
    private MqttAsyncClient client;
    private volatile boolean stopping;
    private int previousBrightness = 100;

    MqttScreenController(MainActivity activity) {
        this.activity = activity;
        tabletId = tabletId();
        commandTopic = BASE_TOPIC + "/" + tabletId + "/screen/set";
        stateTopic = BASE_TOPIC + "/" + tabletId + "/screen/state";
        brightnessCommandTopic = BASE_TOPIC + "/" + tabletId + "/screen/brightness/set";
        brightnessStateTopic = BASE_TOPIC + "/" + tabletId + "/screen/brightness/state";
    }

    void start() { io.execute(this::connect); }
    void shutdown() {
        stopping = true;
        try {
            io.execute(() -> { try { if (client != null && client.isConnected()) client.disconnect(); } catch (Exception ignored) { } });
        } catch (java.util.concurrent.RejectedExecutionException ignored) {
            // The executor may already be stopping during rapid activity recreation.
        }
        io.shutdown();
    }

    private void connect() {
        if (stopping) return;
        try {
            String clientId = "sonic-" + tabletId + "-" + UUID.randomUUID().toString().substring(0, 8);
            client = new MqttAsyncClient("tcp://" + BuildConfig.MQTT_HOST + ":" + BuildConfig.MQTT_PORT, clientId, new MemoryPersistence());
            client.setCallback(new MqttCallbackExtended() {
                @Override public void connectComplete(boolean reconnect, String serverURI) {
                    try {
                        io.execute(() -> finishConnection(reconnect));
                    } catch (java.util.concurrent.RejectedExecutionException ignored) {
                        Log.w("MqttScreen", "MQTT callback arrived after shutdown");
                    }
                }
                @Override public void connectionLost(Throwable cause) { Log.w("MqttScreen", "MQTT_CONNECTION_LOST tablet=" + tabletId, cause); }
                @Override public void messageArrived(String topic, MqttMessage message) {
                    String value = new String(message.getPayload(), StandardCharsets.UTF_8).trim();
                    main.post(() -> apply(value));
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
        } catch (Exception e) { Log.e("MqttScreen", "MQTT_CONNECT_FAILED tablet=" + tabletId, e); }
    }

    private void finishConnection(boolean reconnect) {
        try {
            for (int i = 0; i < 20 && !client.isConnected(); i++) Thread.sleep(100L);
            if (!client.isConnected()) throw new IllegalStateException("MQTT connection not ready");
            client.subscribe(commandTopic, 1);
            client.subscribe(brightnessCommandTopic, 1);
            publishDiscovery();
            publishState();
            Log.i("MqttScreen", "MQTT_CONNECTED tablet=" + tabletId + " reconnect=" + reconnect);
        } catch (Exception e) { Log.e("MqttScreen", "MQTT_SETUP_FAILED tablet=" + tabletId, e); }
    }

    private void publishDiscovery() throws Exception {
        String discoveryTopic = "homeassistant/light/sonic_" + tabletId + "_screen/config";
        String deviceJson = "\"device\":{\"identifiers\":[\"sonic_" + tabletId + "\"],\"name\":\"" + titleCaseTablet() + " Tablet\",\"manufacturer\":\"Sonic\",\"model\":\"Fire 7\"}";
        String payload = "{" +
                "\"name\":\"" + titleCaseTablet() + " Tablet Screen\"," +
                "\"unique_id\":\"sonic_" + tabletId + "_screen\"," +
                "\"command_topic\":\"" + commandTopic + "\"," +
                "\"state_topic\":\"" + stateTopic + "\"," +
                "\"brightness_command_topic\":\"" + brightnessCommandTopic + "\"," +
                "\"brightness_state_topic\":\"" + brightnessStateTopic + "\"," +
                "\"payload_on\":\"ON\",\"payload_off\":\"OFF\",\"brightness_scale\":100," +
                deviceJson + "}";
        MqttMessage message = new MqttMessage(payload.getBytes(StandardCharsets.UTF_8));
        message.setQos(1); message.setRetained(true);
        client.publish(discoveryTopic, message);
        Log.i("MqttScreen", "MQTT_DISCOVERY_PUBLISHED topic=" + discoveryTopic);
    }

    private String titleCaseTablet() {
        if ("living-room".equals(tabletId)) return "Living Room";
        if ("bedroom".equals(tabletId)) return "Bedroom";
        if ("office".equals(tabletId)) return "Office";
        return tabletId;
    }

    private void apply(String raw) {
        if (raw.equalsIgnoreCase("ON")) setBrightness(previousBrightness <= 0 ? 100 : previousBrightness);
        else if (raw.equalsIgnoreCase("OFF")) {
            float current = activity.getWindow().getAttributes().screenBrightness;
            previousBrightness = Math.max(1, Math.min(100, Math.round((current < 0 ? 1f : current) * 100f)));
            setBrightness(0);
        } else {
            try { setBrightness(Integer.parseInt(raw)); } catch (NumberFormatException ignored) { }
        }
    }

    private void setBrightness(int value) {
        int bounded = Math.max(0, Math.min(100, value));
        if (bounded > 0) previousBrightness = bounded;
        Window window = activity.getWindow();
        WindowManager.LayoutParams lp = window.getAttributes();
        lp.screenBrightness = bounded / 100f;
        window.setAttributes(lp);
        publishState(bounded);
    }

    private void publishState() { publishState(currentBrightness()); }
    private void publishState(int value) {
        io.execute(() -> {
            try {
                if (client == null || !client.isConnected()) return;
                MqttMessage state = new MqttMessage((value > 0 ? "ON" : "OFF").getBytes(StandardCharsets.UTF_8)); state.setQos(1); state.setRetained(true);
                MqttMessage brightness = new MqttMessage(Integer.toString(value).getBytes(StandardCharsets.UTF_8)); brightness.setQos(1); brightness.setRetained(true);
                client.publish(stateTopic, state); client.publish(brightnessStateTopic, brightness);
            } catch (Exception ignored) { }
        });
    }
    private int currentBrightness() {
        float value = activity.getWindow().getAttributes().screenBrightness;
        return Math.max(0, Math.min(100, Math.round((value < 0 ? 1f : value) * 100f)));
    }
    private String tabletId() {
        String serial = Build.SERIAL;
        if ("G0W0MB068265F06A".equals(serial)) return "bedroom";
        if ("G0W0MB068265F04A".equals(serial)) return "living-room";
        if ("G0W0T9059434F6JG".equals(serial)) return "office";
        String androidId = Settings.Secure.getString(activity.getContentResolver(), Settings.Secure.ANDROID_ID);
        Log.i("MqttScreen", "DEVICE_ID serial=" + serial + " androidId=" + androidId);
        if ("293601fcb83c4e73".equals(androidId)) return "bedroom";
        if ("70071a26b3ce6ab1".equals(androidId)) return "living-room";
        if ("c27a72a92885f103".equals(androidId)) return "office";
        if ("5707e40ae6bc7748".equals(androidId)) return "office";
        return "tablet-" + serial.toLowerCase(Locale.US).replaceAll("[^a-z0-9_-]", "");
    }
}
