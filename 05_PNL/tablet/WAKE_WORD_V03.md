# Sonic Satellite v0.3: local “Hey Jarvis” prototype

## Compatibility and provisioning

The app uses `ai.picovoice:porcupine-android:4.0.0`. Picovoice documents Android 5.0 / API 21 or newer. The published 4.0.0 AAR contains `jni/armeabi-v7a/libpv_porcupine.so`, and the APK is restricted to that ABI. This confirms packaging for the Fire 7's Android 5.1.1 / API 22 and 32-bit ARM; real-time accuracy, thermal behavior, and AccessKey activation still require a device test.

The built-in `JARVIS` model detects “Jarvis,” not necessarily the exact phrase “Hey Jarvis.” Create an English **Hey Jarvis** wake word for **Android** in Picovoice Console and download its `.ppn`. Obtain an AccessKey from the same account. Put the key alone in a text file and use **Import Picovoice AccessKey File**. Use **Import Hey Jarvis Android Model** for the `.ppn`. The app copies both into private app storage and never includes either in source or the APK. Delete the transfer copy of the AccessKey from shared storage after import. Android's app sandbox protects the imported file; it is not additionally encrypted at rest. The import buttons do not display the key.

Picovoice requires a valid AccessKey and controls usage through account limits. Its current terms describe a time and usage limited free trial and say there is no dedicated personal or non-commercial plan. Confirm ongoing licensing with Picovoice before relying on this beyond evaluation. The engine processes audio locally, but Picovoice's terms allow usage data to be stored and sent when a connection is available. Thus “no continuous audio streaming” does not mean “no SDK network or telemetry.”

## Behavior

Wake listening is opt-in and starts only while the activity is visible and the last authenticated microphone policy response is UNMUTED. The app checks policy every four seconds during wake listening. On mute, policy failure, disabling wake, or leaving the activity, it stops the AudioRecord. Manual recording and wake listening run on one microphone executor, so only one owns the microphone at a time. The five-second manual recording pauses periodic policy checks; the app refreshes policy before restarting wake listening. Wake detections update only the counter, timestamp, and state, with a 2.5-second duplicate trigger cooldown. They do not save or upload audio or launch command recording.

## Fire 7 test

1. Install `app/build/outputs/apk/debug/app-debug.apk` with `adb install -r`. Confirm Android reports package `com.example.sonicsatilite` and the app opens. The wake toggle must initially be OFF and show **Stopped**.
2. Confirm the existing CA and API credential show **CONNECTED**, **CONFIGURED**, and **UNMUTED**. Import the Picovoice AccessKey file and Android `.ppn`, then delete the key transfer file.
3. Turn on **Enable Wake Word** and grant microphone permission. Confirm **Listening**. Say “Hey Jarvis” several times at different distances; each accepted detection should show **Wake Word Detected** and increment the counter and timestamp. A rapid repeat within 2.5 seconds should not increment it.
4. While listening, set global mute through the existing authorized controller. Within the next policy result, expect **Muted** and microphone capture to stop. Unmute and expect listening to resume after an authenticated policy response. Then disconnect Wi-Fi or make Server1 unavailable: expect **Error** and capture stopped. Restore connectivity and verify recovery.
5. While listening, tap **Record 5 Seconds**. Confirm wake listening stops, a WAV is recorded with no competing AudioRecord, and wake listening resumes only after a fresh policy check. Confirm **Send Recording** still works through the existing server path. Turn the wake toggle OFF and leave/reopen the app; capture should remain stopped and the toggle should return OFF.
6. Observe `adb logcat` for `UnsatisfiedLinkError`, Porcupine initialization failures, microphone errors, or memory pressure. If any occur, leave wake disabled and record the exact device/build and error.

Without a user's valid AccessKey and exact-phrase `.ppn`, the detector cannot be fully exercised. A possible fallback if activation or runtime tests fail is Vosk's small English Android model with a constrained phrase grammar. It is much heavier: its small English model is about 40 MB and the project estimates roughly 300 MB runtime memory, so it needs separate Fire 7 latency and false-positive testing before replacing Porcupine.

## Sources

- Picovoice Android binding: https://github.com/Picovoice/porcupine/blob/master/binding/android/README.md
- Picovoice Android API and built-in words: https://picovoice.ai/docs/api/porcupine-android/
- Picovoice custom model: https://picovoice.ai/docs/model-api/porcupine/
- Picovoice terms and FAQ: https://picovoice.ai/docs/terms-of-use.html and https://picovoice.ai/docs/faq/general/
- Vosk small model sizes: https://alphacephei.com/vosk/models
