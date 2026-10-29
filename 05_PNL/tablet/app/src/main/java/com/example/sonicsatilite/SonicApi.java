package com.example.sonicsatilite;

import android.content.Context;
import android.net.Uri;
import android.util.Log;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.SecureRandom;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.util.Collection;
import java.util.UUID;

import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManager;
import javax.net.ssl.TrustManagerFactory;
import javax.net.ssl.X509TrustManager;

/** All methods that do I/O are called from the activity's network executor. */
final class SonicApi {
    private static final String BASE = "https://192.168.1.6:8443";
    private static final String SERVER_IP = "192.168.1.6";
    private static final int CONNECT_TIMEOUT_MS = 4000;
    private static final int READ_TIMEOUT_MS = 60000; // Whisper and HA can take time.
    // Server1 may return the complete Home Assistant entity catalog. Keep this
    // bounded, but large enough for the catalog and its state snapshot.
    private static final int MAX_RESPONSE = 2 * 1024 * 1024;
    private static final int MAX_PANEL_REQUEST = 8192;
    private static final long MAX_WAV = 1000000;
    private static final String TOKEN_FILE = "sonic-api-token";
    private static final String CA_FILE = "sonic-caddy-root.crt";
    private static final String LOCAL_CA_PATH = "/sdcard/Download/sonic-caddy-root.crt";
    private static final String LOCAL_TOKEN_PATH = "/sdcard/Download/sonic-fire7-credential.txt";
    private final Context context;

    SonicApi(Context context) { this.context = context.getApplicationContext(); }

    boolean hasCredential() { return context.getFileStreamPath(TOKEN_FILE).isFile(); }

    boolean hasCa() { return context.getFileStreamPath(CA_FILE).isFile(); }

    String intercomToken() throws IOException { return token(); }

    javax.net.ssl.SSLContext intercomSslContext() throws Exception { return sslContext(); }

    void importToken(Uri uri) throws IOException {
        importTokenBytes(readDocument(uri, 8192));
    }

    void importLocalToken() throws IOException {
        try (FileInputStream in = new FileInputStream(LOCAL_TOKEN_PATH)) {
            importTokenBytes(readBounded(in, 8192));
        }
    }

    boolean removeLocalTokenSource() {
        return new File(LOCAL_TOKEN_PATH).delete();
    }

    private void importTokenBytes(byte[] bytes) throws IOException {
        String value = new String(bytes, StandardCharsets.UTF_8).trim();
        String token = null;
        for (String line : value.split("\\r?\\n")) {
            if (line.startsWith("SONIC_API_TOKEN=")) {
                token = line.substring("SONIC_API_TOKEN=".length()).trim();
                if (token.length() >= 2 && ((token.startsWith("\"") && token.endsWith("\""))
                        || (token.startsWith("'") && token.endsWith("'")))) {
                    token = token.substring(1, token.length() - 1);
                }
                break;
            }
        }
        // A plain single-line token is also accepted for a dedicated transfer file.
        if (token == null && !value.contains("\n") && !value.contains("=")) token = value;
        if (token == null || token.isEmpty())
            throw new IOException("Invalid credential file");
        for (int i = 0; i < token.length(); i++) {
            char c = token.charAt(i);
            if (Character.isWhitespace(c) || Character.isSpaceChar(c) || Character.isISOControl(c))
                throw new IOException("Invalid credential file");
        }
        writePrivate(TOKEN_FILE, token.getBytes(StandardCharsets.UTF_8));
    }

    void importCa(Uri uri) throws Exception {
        importCaBytes(readDocument(uri, 16384));
    }

    void importLocalCa() throws Exception {
        try (FileInputStream in = new FileInputStream(LOCAL_CA_PATH)) {
            importCaBytes(readBounded(in, 16384));
        }
    }

    private void importCaBytes(byte[] bytes) throws Exception {
        X509Certificate ca = parseCa(bytes);
        ca.checkValidity();
        if (ca.getBasicConstraints() < 0) throw new IOException("Certificate is not a CA");
        boolean[] uses = ca.getKeyUsage();
        if (uses != null && (uses.length < 6 || !uses[5]))
            throw new IOException("Certificate cannot sign certificates");
        if (!ca.getSubjectX500Principal().equals(ca.getIssuerX500Principal()))
            throw new IOException("Certificate is not a self-issued root CA");
        ca.verify(ca.getPublicKey());
        writePrivate(CA_FILE, bytes);
    }

    private X509Certificate parseCa(byte[] bytes) throws Exception {
        CertificateFactory factory = CertificateFactory.getInstance("X.509");
        return (X509Certificate) factory.generateCertificate(new java.io.ByteArrayInputStream(bytes));
    }

    private byte[] readDocument(Uri uri, int limit) throws IOException {
        try (InputStream in = context.getContentResolver().openInputStream(uri)) {
            if (in == null) throw new IOException("Cannot open selected file");
            return readBounded(in, limit);
        }
    }

    private static byte[] readBounded(InputStream in, int limit) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        int n;
        while ((n = in.read(buf)) != -1) {
            if (out.size() + n > limit) throw new IOException("File or response is too large");
            out.write(buf, 0, n);
        }
        return out.toByteArray();
    }

    private void writePrivate(String name, byte[] data) throws IOException {
        try (FileOutputStream out = context.openFileOutput(name, Context.MODE_PRIVATE)) {
            out.write(data);
        }
    }

    private String token() throws IOException {
        try (FileInputStream in = context.openFileInput(TOKEN_FILE)) {
            return new String(readBounded(in, 8192), StandardCharsets.UTF_8);
        }
    }

    private SSLContext sslContext() throws Exception {
        byte[] bytes;
        try (FileInputStream in = context.openFileInput(CA_FILE)) {
            bytes = readBounded(in, 16384);
        }
        X509Certificate ca = parseCa(bytes);
        ca.checkValidity();
        KeyStore store = KeyStore.getInstance(KeyStore.getDefaultType());
        store.load(null);
        store.setCertificateEntry("sonic-root", ca);
        TrustManagerFactory factory = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
        factory.init(store);
        SSLContext ssl = SSLContext.getInstance("TLS");
        ssl.init(null, factory.getTrustManagers(), new SecureRandom());
        return ssl;
    }

    private HttpsURLConnection open(String path, String method, int readTimeout,
                                     boolean authenticated) throws Exception {
        HttpsURLConnection conn = (HttpsURLConnection) new URL(BASE + path).openConnection();
        conn.setSSLSocketFactory(sslContext().getSocketFactory());
        // Keep HttpsURLConnection's default hostname verifier. The URL host is the literal Server1 IP.
        conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
        conn.setReadTimeout(readTimeout);
        conn.setUseCaches(false);
        conn.setInstanceFollowRedirects(false);
        conn.setRequestMethod(method);
        if (authenticated) conn.setRequestProperty("Authorization", "Bearer " + token());
        conn.setRequestProperty("Accept", "application/json");
        conn.setRequestProperty("Cache-Control", "no-cache");
        return conn;
    }

    private static void verifyIpSan(HttpsURLConnection conn) throws Exception {
        X509Certificate leaf = (X509Certificate) conn.getServerCertificates()[0];
        Collection<java.util.List<?>> sans = leaf.getSubjectAlternativeNames();
        if (sans != null) for (java.util.List<?> san : sans) {
            if (Integer.valueOf(7).equals(san.get(0)) && SERVER_IP.equals(san.get(1))) return;
        }
        throw new javax.net.ssl.SSLPeerUnverifiedException("Server certificate lacks Server1 IP SAN");
    }

    private JSONObject get(String path) throws Exception {
        HttpsURLConnection conn = open(path, "GET", 8000, true);
        try {
            conn.connect();
            verifyIpSan(conn);
            int responseCode = conn.getResponseCode();
            Log.i("SonicApi", "Upload HTTP status=" + responseCode);
            checkStatus(responseCode);
            return new JSONObject(new String(readBounded(conn.getInputStream(), MAX_RESPONSE), StandardCharsets.UTF_8));
        } finally { conn.disconnect(); }
    }

    int health() throws Exception {
        HttpsURLConnection conn = open("/health", "GET", 8000, false);
        try {
            conn.connect();
            verifyIpSan(conn);
            return conn.getResponseCode();
        } finally { conn.disconnect(); }
    }

    boolean globalMute() throws Exception {
        JSONObject json = get("/mic-policy");
        Object mute = json.opt("global_mute");
        Object version = json.opt("version");
        if (!(mute instanceof Boolean) || !(version instanceof Integer))
            throw new IOException("Invalid microphone policy response");
        return (Boolean) mute;
    }

    JSONObject upload(File wav) throws Exception {
        if (!wav.isFile() || wav.length() < 44 || wav.length() > MAX_WAV)
            throw new IOException("Recording is missing or exceeds upload limit");
        String boundary = "sonic-" + UUID.randomUUID().toString().replace("-", "");
        byte[] prefix = ("--" + boundary + "\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"audio.wav\"\r\n"
                + "Content-Type: audio/wav\r\n\r\n").getBytes(StandardCharsets.US_ASCII);
        byte[] suffix = ("\r\n--" + boundary + "--\r\n").getBytes(StandardCharsets.US_ASCII);
        HttpsURLConnection conn = open("/voice-command", "POST", READ_TIMEOUT_MS, true);
        try {
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
            conn.setFixedLengthStreamingMode(prefix.length + wav.length() + suffix.length);
            conn.connect();
            verifyIpSan(conn);
            try (OutputStream out = conn.getOutputStream(); FileInputStream in = new FileInputStream(wav)) {
                out.write(prefix);
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) != -1) out.write(buf, 0, n);
                out.write(suffix);
            }
            checkStatus(conn);
            return new JSONObject(new String(readBounded(conn.getInputStream(), MAX_RESPONSE), StandardCharsets.UTF_8));
        } finally { conn.disconnect(); }
    }

    JSONObject panelConfig() throws Exception { return get("/panel/config"); }

    JSONObject panelStates() throws Exception { return get("/panel/states"); }

    JSONObject panelHealth() throws Exception { return get("/panel/health"); }

    JSONObject panelAction(JSONObject action) throws Exception {
        if (action == null || action.toString().getBytes(StandardCharsets.UTF_8).length > MAX_PANEL_REQUEST)
            throw new IOException("Panel action is too large");
        HttpsURLConnection conn = open("/panel/action", "POST", 8000, true);
        try {
            byte[] body = action.toString().getBytes(StandardCharsets.UTF_8);
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setFixedLengthStreamingMode(body.length);
            conn.connect();
            verifyIpSan(conn);
            try (OutputStream out = conn.getOutputStream()) { out.write(body); }
            checkStatus(conn);
            return new JSONObject(new String(readBounded(conn.getInputStream(), MAX_RESPONSE), StandardCharsets.UTF_8));
        } finally { conn.disconnect(); }
    }

    static String transcript(JSONObject json) throws JSONException {
        Object text = json.opt("text");
        if (!(text instanceof String)) throw new JSONException("Missing transcription text");
        return (String) text;
    }

    static String haResponse(JSONObject json) throws JSONException {
        Object ha = json.opt("ha");
        if (ha == JSONObject.NULL && "empty_transcript".equals(json.optString("result")))
            return "No speech detected";
        if (!(ha instanceof JSONObject)) throw new JSONException("Missing Home Assistant response");
        Object speech = ((JSONObject) ha).opt("speech");
        if (!(speech instanceof String)) throw new JSONException("Missing Home Assistant speech text");
        return (String) speech;
    }

    static String haResult(JSONObject json) throws JSONException {
        if (json.opt("ha") == JSONObject.NULL && "empty_transcript".equals(json.optString("result")))
            return "response_type=empty_transcript; text=No speech detected";
        Object ha = json.opt("ha");
        if (!(ha instanceof JSONObject)) throw new JSONException("Missing Home Assistant response");
        JSONObject object = (JSONObject) ha;
        Object speech = object.opt("speech");
        if (!(speech instanceof String)) throw new JSONException("Missing Home Assistant speech text");
        return "response_type=" + object.optString("response_type", "unknown") + "; text=" + speech;
    }

    private static void checkStatus(HttpURLConnection conn) throws IOException {
        checkStatus(conn.getResponseCode());
    }

    private static void checkStatus(int code) throws IOException {
        if (code == 401) throw new IOException("Credential rejected or expired (HTTP 401)");
        if (code == 403) throw new IOException("Credential rejected or access denied (HTTP 403)");
        if (code < 200 || code >= 300) throw new IOException("Server returned HTTP " + code);
    }
}
