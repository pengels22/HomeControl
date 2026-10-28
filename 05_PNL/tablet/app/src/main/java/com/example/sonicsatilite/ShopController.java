package com.example.sonicsatilite;

import android.os.Handler;
import android.os.Looper;
import android.widget.Button;
import android.widget.TextView;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;

final class ShopController {
    private static final String BASE = "http://192.168.20.34:8080";
    private final ExecutorService network; private final Handler main = new Handler(Looper.getMainLooper());
    private final TextView status; private final Map<String, Button> buttons = new HashMap<>(); private final Map<String, Boolean> state = new HashMap<>();
    private final Runnable poll = new Runnable() { public void run() { fetchState(); main.postDelayed(this, 5000L); } };
    ShopController(ExecutorService network, TextView status, Button allOff, Map<String, Button> controls) {
        this.network = network; this.status = status; buttons.putAll(controls);
        for (String channel : buttons.keySet()) { state.put(channel, false); buttons.get(channel).setOnClickListener(v -> toggle(channel)); }
        allOff.setOnClickListener(v -> post("/api/all_off", null));
    }
    void start() { fetchState(); main.postDelayed(poll, 5000L); }
    void stop() { main.removeCallbacks(poll); }
    private void toggle(String channel) { Map<String, Object> body = new HashMap<>(); body.put("channel", channel); body.put("state", !Boolean.TRUE.equals(state.get(channel))); post("/api/set", body); }
    private void fetchState() { network.execute(() -> { try { JSONObject json = request("/api/state", "GET", null); JSONObject rails = json.getJSONObject("rails"); for (String c : buttons.keySet()) state.put(c, rails.optBoolean(c, false)); main.post(() -> { status.setText("Shop Controller: Online"); updateButtons(); }); } catch (Exception e) { main.post(() -> status.setText("Shop Controller: Offline")); } }); }
    private void post(String path, Map<String, Object> values) { network.execute(() -> { try { JSONObject body = null; if (values != null) { body = new JSONObject(); for (Map.Entry<String, Object> e : values.entrySet()) body.put(e.getKey(), e.getValue()); } request(path, "POST", body); fetchState(); } catch (Exception e) { main.post(() -> status.setText("Shop Controller: Action failed")); } }); }
    private JSONObject request(String path, String method, JSONObject body) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(BASE + path).openConnection(); c.setConnectTimeout(2500); c.setReadTimeout(4000); c.setRequestMethod(method); c.setRequestProperty("Accept", "application/json");
        if (body != null) { c.setDoOutput(true); c.setRequestProperty("Content-Type", "application/json"); try (OutputStream out = c.getOutputStream()) { out.write(body.toString().getBytes(StandardCharsets.UTF_8)); } }
        int code = c.getResponseCode(); if (code < 200 || code >= 300) throw new IllegalStateException("HTTP " + code); StringBuilder text = new StringBuilder();
        try (BufferedReader r = new BufferedReader(new InputStreamReader(c.getInputStream(), StandardCharsets.UTF_8))) { String line; while ((line = r.readLine()) != null) text.append(line); } finally { c.disconnect(); }
        return text.length() == 0 ? new JSONObject() : new JSONObject(text.toString());
    }
    private void updateButtons() { for (Map.Entry<String, Button> e : buttons.entrySet()) e.getValue().setAlpha(Boolean.TRUE.equals(state.get(e.getKey())) ? 1f : 0.65f); }
}
