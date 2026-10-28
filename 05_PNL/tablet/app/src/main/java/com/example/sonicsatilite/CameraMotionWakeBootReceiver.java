package com.example.sonicsatilite;

import android.Manifest;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;

/** Restarts motion wake after the tablet boots. */
public final class CameraMotionWakeBootReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent received) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                && context.checkSelfPermission(Manifest.permission.CAMERA)
                != PackageManager.PERMISSION_GRANTED) return;
        Intent service = new Intent(context, CameraMotionWakeService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(service);
        else context.startService(service);
    }
}
