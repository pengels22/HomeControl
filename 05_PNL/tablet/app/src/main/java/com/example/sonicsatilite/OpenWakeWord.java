package com.example.sonicsatilite;

import android.content.Context;
import android.util.Log;

import org.tensorflow.lite.DataType;
import org.tensorflow.lite.Interpreter;
import org.tensorflow.lite.Tensor;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/** Streaming openWakeWord v0.5.1 feature pipeline, with one 80 ms prediction per call. */
final class OpenWakeWord implements AutoCloseable {
    private static final String TAG = "OpenWakeWord";
    private static final String MEL_SHA256 = "96fa0adccb6e8cf95cb14465409a1a2898ee4a96a85bb9ed3c7eb0e68bf163e8";
    static final int CHUNK = 1280;
    static final float THRESHOLD = 0.5f;
    private static final int MEL_BINS = 32;
    private static final int MEL_WINDOW = 76;
    private static final int EMBEDDING_BINS = 96;
    private final Interpreter mel;
    private final Interpreter embedding;
    private final Interpreter classifier;
    private final short[] raw = new short[1760]; // 80 ms plus upstream's 30 ms overlap
    private int rawSize;
    private final float[] melHistory = new float[970 * MEL_BINS];
    private int melFrames = MEL_WINDOW;
    private final float[] features = new float[120 * EMBEDDING_BINS];
    private int featureFrames;
    private int audioFrames;
    private int classifierInferences;
    private boolean classifierProcessingLogged;
    private int melInputSize;

    OpenWakeWord(Context context) throws IOException {
        Log.i(TAG, "Initializing melspectrogram.tflite");
        mel = open(context, "melspectrogram.tflite");
        Log.i(TAG, "Initializing embedding_model.tflite");
        embedding = open(context, "embedding_model.tflite");
        Log.i(TAG, "Initializing hey_jarvis_v0.1.tflite");
        classifier = open(context, "hey_jarvis_v0.1.tflite");
        mel.resizeInput(0, new int[]{1, CHUNK}, true);
        mel.allocateTensors();
        melInputSize = CHUNK;
        embedding.allocateTensors();
        classifier.allocateTensors();
        requireFloat(mel.getInputTensor(0));
        requireFloat(mel.getOutputTensor(0));
        requireShape(embedding.getInputTensor(0), 1, MEL_WINDOW, MEL_BINS, 1);
        requireFloat(embedding.getOutputTensor(0));
        requireShape(classifier.getInputTensor(0), 1, 16, EMBEDDING_BINS);
        requireFloat(classifier.getOutputTensor(0));
        if (embedding.getOutputTensor(0).numBytes() != EMBEDDING_BINS * 4
                || classifier.getOutputTensor(0).numBytes() != 4)
            throw new IllegalStateException("Unexpected openWakeWord output tensor shape");
        logTensors("melspectrogram.tflite", mel);
        logTensors("embedding_model.tflite", embedding);
        logTensors("hey_jarvis_v0.1.tflite", classifier);
        // Upstream starts with 76 mel frames of ones. Its random-audio embedding
        // warmup is replaced by a quiet feature buffer; predictions are suppressed
        // until 16 live embeddings and the upstream five-frame guard are available.
        for (int i = 0; i < MEL_WINDOW * MEL_BINS; i++) melHistory[i] = 1f;
        Log.i(TAG, "Streaming buffers configured: PCM chunk=1280 samples, overlap=480 samples, "
                + "mel warmup=76 frames, embedding window=16, feature history=120 embeddings; "
                + "threshold=" + THRESHOLD);
    }

    private static Interpreter open(Context context, String name) throws IOException {
        try (InputStream stream = context.getAssets().open("openwakeword/" + name)) {
            byte[] bytes = new byte[stream.available()];
            int offset = 0;
            while (offset < bytes.length) {
                int count = stream.read(bytes, offset, bytes.length - offset);
                if (count < 0) throw new IOException("Incomplete model asset: " + name);
                offset += count;
            }
            ByteBuffer model = ByteBuffer.allocateDirect(bytes.length).order(ByteOrder.nativeOrder());
            model.put(bytes).rewind();
            if (name.equals("melspectrogram.tflite")) initializeMelShape(model, bytes);
            Interpreter.Options options = new Interpreter.Options();
            options.setNumThreads(1);
            options.setUseXNNPACK(false);
            try {
                return new Interpreter(model, options);
            } catch (RuntimeException | LinkageError failure) {
                Log.e(TAG, "Initialization failed for " + name + ": "
                        + failure.getClass().getSimpleName());
                throw failure;
            }
        }
    }

    /** Java TFLite allocates in its constructor; upstream Python resizes before allocation. */
    private static void initializeMelShape(ByteBuffer model, byte[] original) throws IOException {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(original);
            StringBuilder hex = new StringBuilder();
            for (byte value : hash) hex.append(String.format(java.util.Locale.US, "%02x", value & 255));
            if (!MEL_SHA256.equals(hex.toString())) throw new IOException("Unknown mel model version");
            if (model.get(4) != 'T' || model.get(5) != 'F' || model.get(6) != 'L' || model.get(7) != '3')
                throw new IOException("Invalid mel model identifier");
            int root = model.getInt(0);
            int subgraphs = vector(model, field(model, root, 2));
            int graph = table(model, subgraphs + 4);
            int tensors = vector(model, field(model, graph, 0));
            int inputs = vector(model, field(model, graph, 1));
            if (model.getInt(inputs) != 1 || model.getInt(subgraphs) != 1)
                throw new IOException("Unexpected mel model graph");
            int inputIndex = model.getInt(inputs + 4);
            int inputTensor = table(model, tensors + 4 + inputIndex * 4);
            int shape = vector(model, field(model, inputTensor, 0));
            int signature = vector(model, field(model, inputTensor, 7));
            if (model.getInt(shape) != 2 || model.getInt(shape + 4) != 1
                    || model.getInt(shape + 8) != 1 || model.getInt(signature) != 2
                    || model.getInt(signature + 4) != -1 || model.getInt(signature + 8) != -1)
                throw new IOException("Unexpected mel input metadata");
            Log.i(TAG, "melspectrogram.tflite input FLOAT32 shape=[1,1] signature=[-1,-1]; "
                    + "initializing shape=[1,1280] before Java allocation");
            model.putInt(shape + 8, CHUNK);
            model.rewind();
        } catch (NoSuchAlgorithmException | IndexOutOfBoundsException e) {
            throw new IOException("Cannot prepare mel model input shape", e);
        }
    }

    private static int field(ByteBuffer buffer, int table, int index) {
        int vtable = table - buffer.getInt(table);
        int entry = 4 + index * 2;
        if (entry >= (buffer.getShort(vtable) & 0xffff)) return 0;
        return table + (buffer.getShort(vtable + entry) & 0xffff);
    }

    private static int vector(ByteBuffer buffer, int offset) { return offset + buffer.getInt(offset); }
    private static int table(ByteBuffer buffer, int offset) { return offset + buffer.getInt(offset); }

    private static void logTensors(String name, Interpreter interpreter) {
        Tensor input = interpreter.getInputTensor(0);
        Tensor output = interpreter.getOutputTensor(0);
        Log.i(TAG, name + " input=" + input.dataType() + " "
                + java.util.Arrays.toString(input.shape()) + " signature="
                + java.util.Arrays.toString(input.shapeSignature()) + " output="
                + output.dataType() + " " + java.util.Arrays.toString(output.shape())
                + " signature=" + java.util.Arrays.toString(output.shapeSignature()));
    }

    private static void requireFloat(Tensor tensor) {
        if (tensor.dataType() != DataType.FLOAT32)
            throw new IllegalStateException("Unexpected openWakeWord tensor type");
    }

    private static void requireShape(Tensor tensor, int... expected) {
        requireFloat(tensor);
        int[] actual = tensor.shape();
        if (actual.length != expected.length) throw new IllegalStateException("Unexpected openWakeWord tensor rank");
        for (int i = 0; i < actual.length; i++)
            if (actual[i] != expected[i]) throw new IllegalStateException("Unexpected openWakeWord tensor shape");
    }

    /** Returns a UI-only probability, or NaN while the live feature window fills. */
    float process(short[] pcm) {
        if (pcm.length != CHUNK) throw new IllegalArgumentException("Expected 80 ms PCM16");
        audioFrames++;
        int keep = Math.min(rawSize, 480);
        if (keep > 0) System.arraycopy(raw, rawSize - keep, raw, 0, keep);
        System.arraycopy(pcm, 0, raw, keep, CHUNK);
        rawSize = keep + CHUNK;
        if (melInputSize != rawSize) {
            mel.resizeInput(0, new int[]{1, rawSize}, true);
            mel.allocateTensors();
            melInputSize = rawSize;
        }
        float[][] input = new float[1][rawSize];
        for (int i = 0; i < rawSize; i++) input[0][i] = raw[i];
        int frames = mel.getOutputTensor(0).shape()[2];
        float[][][][] output = new float[1][1][frames][MEL_BINS];
        mel.run(input, output);
        int expectedFrames = rawSize == CHUNK ? 5 : 8;
        if (frames != expectedFrames)
            throw new IllegalStateException("Unexpected mel frame count: " + frames);
        int limit = melHistory.length / MEL_BINS;
        if (melFrames + frames > limit) {
            int shift = melFrames + frames - limit;
            System.arraycopy(melHistory, shift * MEL_BINS, melHistory, 0,
                    (melFrames - shift) * MEL_BINS);
            melFrames -= shift;
        }
        for (int frame = 0; frame < frames; frame++)
            for (int bin = 0; bin < MEL_BINS; bin++)
                melHistory[melFrames * MEL_BINS + frame * MEL_BINS + bin]
                        = output[0][0][frame][bin] / 10f + 2f;
        melFrames += frames;

        float[][][][] embeddingInput = new float[1][MEL_WINDOW][MEL_BINS][1];
        int start = (melFrames - MEL_WINDOW) * MEL_BINS;
        for (int frame = 0; frame < MEL_WINDOW; frame++)
            for (int bin = 0; bin < MEL_BINS; bin++)
                embeddingInput[0][frame][bin][0] = melHistory[start + frame * MEL_BINS + bin];
        float[][][][] embeddingOutput = new float[1][1][1][EMBEDDING_BINS];
        embedding.run(embeddingInput, embeddingOutput);
        if (featureFrames == 120) {
            System.arraycopy(features, EMBEDDING_BINS, features, 0, 119 * EMBEDDING_BINS);
            featureFrames--;
        }
        for (int i = 0; i < EMBEDDING_BINS; i++)
            features[featureFrames * EMBEDDING_BINS + i] = embeddingOutput[0][0][0][i];
        featureFrames++;
        if (featureFrames < 16) return Float.NaN;
        float[][][] classifierInput = new float[1][16][EMBEDDING_BINS];
        start = (featureFrames - 16) * EMBEDDING_BINS;
        for (int frame = 0; frame < 16; frame++)
            for (int i = 0; i < EMBEDDING_BINS; i++)
                classifierInput[0][frame][i] = features[start + frame * EMBEDDING_BINS + i];
        float[][] classifierOutput = new float[1][1];
        if (!classifierProcessingLogged) {
            classifierProcessingLogged = true;
            Log.i(TAG, "Classifier actively processing rolling 16x96 embedding window");
        }
        classifier.run(classifierInput, classifierOutput);
        float score = classifierOutput[0][0];
        if (!Float.isFinite(score) || score < 0 || score > 1)
            throw new IllegalStateException("Invalid wake-word confidence");
        classifierInferences++;
        return classifierInferences <= 5 ? 0f : score;
    }

    int getAudioFrames() { return audioFrames; }

    int getClassifierInferences() { return classifierInferences; }

    private static ByteBuffer floats(int count) {
        return ByteBuffer.allocateDirect(count * 4).order(ByteOrder.nativeOrder());
    }

    @Override public void close() {
        classifier.close();
        embedding.close();
        mel.close();
    }
}
