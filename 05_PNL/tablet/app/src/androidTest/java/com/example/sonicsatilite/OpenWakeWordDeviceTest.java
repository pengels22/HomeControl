package com.example.sonicsatilite;

import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.util.Log;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;

import org.junit.Test;
import org.junit.runner.RunWith;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Locale;

import static org.junit.Assert.assertTrue;

@RunWith(AndroidJUnit4.class)
public class OpenWakeWordDeviceTest {
    @Test public void loadsAllModelsAndRunsStreamingPipeline() throws Exception {
        try (OpenWakeWord detector = new OpenWakeWord(
                InstrumentationRegistry.getInstrumentation().getTargetContext())) {
            short[] silence = new short[OpenWakeWord.CHUNK];
            for (int i = 0; i < 20; i++) {
                float score = detector.process(silence);
                if (i >= 15) assertTrue("Invalid score at frame " + i,
                        !Float.isNaN(score) && score >= 0f && score <= 1f);
            }
            assertTrue("Expected every PCM chunk to be counted", detector.getAudioFrames() == 20);
            assertTrue("Expected classifier calls after embedding warmup",
                    detector.getClassifierInferences() == 5);
        }
    }

    @Test public void recordsMicrophoneAndWritesReferenceData() throws Exception {
        int minimum = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT);
        assertTrue(minimum > 0);
        AudioRecord recorder = new AudioRecord(MediaRecorder.AudioSource.MIC, 16000,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
                Math.max(minimum, 4096));
        assertTrue(recorder.getState() == AudioRecord.STATE_INITIALIZED);
        File dir = InstrumentationRegistry.getInstrumentation().getTargetContext().getExternalFilesDir(null);
        File pcmFile = new File(dir, "wake-reference.pcm");
        File scoreFile = new File(dir, "wake-scores.csv");
        float minimumScore = 1f, maximumScore = 0f;
        try (OpenWakeWord detector = new OpenWakeWord(
                InstrumentationRegistry.getInstrumentation().getTargetContext());
             FileOutputStream pcmOut = new FileOutputStream(pcmFile);
             Writer scores = new OutputStreamWriter(new FileOutputStream(scoreFile), "UTF-8")) {
            recorder.startRecording();
            assertTrue(recorder.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING);
            short[] frame = new short[OpenWakeWord.CHUNK];
            ByteBuffer bytes = ByteBuffer.allocate(OpenWakeWord.CHUNK * 2).order(ByteOrder.LITTLE_ENDIAN);
            for (int f = 0; f < 50; f++) {
                int offset = 0;
                while (offset < frame.length) {
                    int read = recorder.read(frame, offset, frame.length - offset);
                    assertTrue("Microphone read failed", read > 0);
                    offset += read;
                }
                bytes.clear();
                for (short sample : frame) bytes.putShort(sample);
                pcmOut.write(bytes.array());
                float score = detector.process(frame);
                scores.write(String.format(Locale.US, "%d,%.9f\n", f, score));
                if (!Float.isNaN(score) && f >= 20) {
                    minimumScore = Math.min(minimumScore, score);
                    maximumScore = Math.max(maximumScore, score);
                }
            }
        } finally {
            if (recorder.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING) recorder.stop();
            recorder.release();
        }
        Log.i("OpenWakeWordTest", String.format(Locale.US,
                "Microphone inference complete: min=%.9f max=%.9f frames=50", minimumScore, maximumScore));
        assertTrue("No finite confidence", minimumScore <= maximumScore);
    }
}
