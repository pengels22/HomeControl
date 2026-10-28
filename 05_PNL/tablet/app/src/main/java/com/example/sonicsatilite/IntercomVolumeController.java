package com.example.sonicsatilite;

import android.content.Context;
import android.media.AudioManager;

/** Temporarily raises incoming intercom audio, then restores the prior volume. */
final class IntercomVolumeController {
    private static final int LOUD_PERCENT = 90;
    private final AudioManager audio;
    private int previous = -1;

    IntercomVolumeController(Context context) {
        audio = (AudioManager) context.getApplicationContext().getSystemService(Context.AUDIO_SERVICE);
    }

    synchronized void begin() {
        if (audio == null || previous >= 0) return;
        previous = audio.getStreamVolume(AudioManager.STREAM_MUSIC);
        int max = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
        audio.setStreamVolume(AudioManager.STREAM_MUSIC, Math.max(1, Math.round(max * LOUD_PERCENT / 100f)), 0);
    }

    synchronized void end() {
        if (audio == null || previous < 0) return;
        int restore = previous;
        previous = -1;
        audio.setStreamVolume(AudioManager.STREAM_MUSIC, restore, 0);
    }
}
