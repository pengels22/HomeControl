package com.example.sonicsatilite;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.ImageFormat;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureRequest;
import android.media.Image;
import android.media.ImageReader;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import android.util.Log;
import android.view.Surface;

import java.nio.ByteBuffer;
import java.util.Arrays;
import java.util.Collections;

/** Low-resolution front-camera motion detector used to wake the permanently-powered tablets. */
public final class CameraMotionWakeService extends Service {
    private static final String TAG = "CameraMotionWake";
    private static final String CHANNEL = "camera_motion_wake";
    private static final int NOTIFICATION_ID = 701;
    private static final long WAKE_COOLDOWN_MS = 3500L;
    private CameraDevice camera;
    private CameraCaptureSession session;
    private ImageReader reader;
    private PowerManager.WakeLock cpuWakeLock;
    private byte[] previous;
    private long lastWake;
    private volatile boolean stopping;

    @Override public void onCreate() {
        super.onCreate();
        PowerManager power = (PowerManager) getSystemService(POWER_SERVICE);
        if (power != null) {
            cpuWakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, TAG + ":monitor");
            cpuWakeLock.setReferenceCounted(false);
            cpuWakeLock.acquire();
        }
        createChannel();
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL)
                : new Notification.Builder(this);
        builder.setSmallIcon(com.example.sonicsatilite.R.mipmap.ic_launcher)
                .setContentTitle("Sonic motion wake")
                .setContentText("Front-camera motion detection is active")
                .setOngoing(true);
        startForeground(NOTIFICATION_ID, builder.build());
        openCamera();
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel channel = new NotificationChannel(CHANNEL, "Camera motion wake",
                    NotificationManager.IMPORTANCE_LOW);
            getSystemService(NotificationManager.class).createNotificationChannel(channel);
        }
    }

    private void openCamera() {
        if (Build.VERSION.SDK_INT >= 23 && checkSelfPermission(Manifest.permission.CAMERA)
                != PackageManager.PERMISSION_GRANTED) {
            Log.e(TAG, "Camera permission is not granted");
            stopSelf();
            return;
        }
        try {
            CameraManager manager = (CameraManager) getSystemService(Context.CAMERA_SERVICE);
            String selected = null;
            for (String id : manager.getCameraIdList()) {
                CameraCharacteristics c = manager.getCameraCharacteristics(id);
                Integer facing = c.get(CameraCharacteristics.LENS_FACING);
                if (facing != null && facing == CameraCharacteristics.LENS_FACING_FRONT) {
                    selected = id;
                    break;
                }
            }
            if (selected == null) { Log.e(TAG, "No front camera found"); return; }
            reader = ImageReader.newInstance(320, 240, ImageFormat.YUV_420_888, 2);
            reader.setOnImageAvailableListener(r -> process(r.acquireLatestImage()), null);
            manager.openCamera(selected, new CameraDevice.StateCallback() {
                @Override public void onOpened(CameraDevice device) { camera = device; startCapture(); }
                @Override public void onDisconnected(CameraDevice device) { device.close(); camera = null; }
                @Override public void onError(CameraDevice device, int error) { device.close(); camera = null; Log.e(TAG, "Camera error " + error); }
            }, null);
        } catch (Exception e) { Log.e(TAG, "Unable to open front camera", e); }
    }

    private void startCapture() {
        try {
            Surface surface = reader.getSurface();
            camera.createCaptureSession(Collections.singletonList(surface), new CameraCaptureSession.StateCallback() {
                @Override public void onConfigured(CameraCaptureSession s) {
                    session = s;
                    try {
                        CaptureRequest.Builder request = camera.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
                        request.addTarget(surface);
                        request.set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO);
                        s.setRepeatingRequest(request.build(), null, null);
                        Log.i(TAG, "Front-camera motion detection started");
                    } catch (CameraAccessException e) { Log.e(TAG, "Unable to start camera preview", e); }
                }
                @Override public void onConfigureFailed(CameraCaptureSession s) { Log.e(TAG, "Camera capture configuration failed"); }
            }, null);
        } catch (CameraAccessException e) { Log.e(TAG, "Unable to create camera session", e); }
    }

    private void process(Image image) {
        if (image == null) return;
        try {
            ByteBuffer buffer = image.getPlanes()[0].getBuffer();
            byte[] current = new byte[buffer.remaining()];
            buffer.get(current);
            if (previous != null && current.length == previous.length) {
                int changed = 0, samples = 0;
                for (int i = 0; i < current.length; i += 16) {
                    if (Math.abs((current[i] & 0xff) - (previous[i] & 0xff)) > 28) changed++;
                    samples++;
                }
                if (samples > 0 && changed >= samples * 0.12f && System.currentTimeMillis() - lastWake > WAKE_COOLDOWN_MS) {
                    lastWake = System.currentTimeMillis();
                    wakeScreen();
                    Log.i(TAG, "Motion detected; screen wake requested changed=" + changed + "/" + samples);
                }
            }
            previous = current;
        } finally { image.close(); }
    }

    private void wakeScreen() {
        try {
            PowerManager power = (PowerManager) getSystemService(POWER_SERVICE);
            PowerManager.WakeLock lock = power.newWakeLock(
                    PowerManager.SCREEN_BRIGHT_WAKE_LOCK | PowerManager.ACQUIRE_CAUSES_WAKEUP,
                    TAG + ":motion");
            lock.acquire(1500L);
            lock.release();
        } catch (SecurityException failure) {
            // Older installs may not yet contain WAKE_LOCK in their granted
            // permission set. Motion detection must never crash the app.
            Log.e(TAG, "Wake lock permission unavailable; motion wake skipped", failure);
        }
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) { return START_STICKY; }
    @Override public void onDestroy() {
        stopping = true;
        if (session != null) session.close();
        if (camera != null) camera.close();
        if (reader != null) reader.close();
        if (cpuWakeLock != null && cpuWakeLock.isHeld()) cpuWakeLock.release();
        super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent) { return null; }
}
