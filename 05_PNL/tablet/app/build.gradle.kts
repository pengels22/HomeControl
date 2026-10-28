plugins {
    alias(libs.plugins.android.application)
}

android {
    namespace = "com.example.sonicsatilite"
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "com.example.sonicsatilite"
        minSdk = 22
        targetSdk = 37
        versionCode = 4
        versionName = "0.4"
        ndk { abiFilters += "armeabi-v7a" }

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            optimization {
                enable = true
                packageScope = setOf("androidx.**", "kotlin.**", "kotlinx.**")
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    androidResources { noCompress += "tflite" }
    buildFeatures { buildConfig = true }
    buildTypes.all {
        buildConfigField("String", "MQTT_HOST", "\"192.168.1.8\"")
        buildConfigField("int", "MQTT_PORT", "1883")
        buildConfigField("String", "MQTT_USER", "\"mqtt\"")
        buildConfigField("String", "MQTT_PASSWORD", "\"${System.getenv("SONIC_MQTT_PASSWORD") ?: ""}\"")
    }
}

dependencies {
    implementation(libs.activity.ktx)
    implementation(libs.appcompat)
    implementation(libs.constraintlayout)
    implementation(libs.material)
    implementation("com.mikepenz:iconics-typeface-api:5.6.0")
    implementation("com.mikepenz:community-material-typeface:7.0.96.2-kotlin@aar")
    implementation("com.mikepenz:phosphor-typeface:1.0.0.1-kotlin@aar")
    implementation("org.tensorflow:tensorflow-lite:2.10.0") {
        exclude(group = "org.tensorflow", module = "tensorflow-lite-api")
    }
    implementation(files("libs/tensorflow-lite-api-2.10.0.jar"))
    implementation("org.eclipse.paho:org.eclipse.paho.client.mqttv3:1.2.5")
    implementation("io.github.webrtc-sdk:android:150.7871.04")
    implementation("org.java-websocket:Java-WebSocket:1.5.6")
    testImplementation(libs.junit)
    androidTestImplementation(libs.espresso.core)
    androidTestImplementation(libs.ext.junit)
}
