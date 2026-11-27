plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
    id("org.jetbrains.kotlin.plugin.compose")
}

// Chaquopy merges all Python source dirs into one flat tree: adding backend/
// and shared/ directly would collide on __init__.py. Sync them into a single
// generated tree with distinct package folders instead.
val generatedPython = layout.buildDirectory.dir("generated/python")
val syncPython by tasks.registering(Copy::class) {
    from("../python") { into("") }
    from("../../proxyhunter") { into("proxyhunter") }
    from("../../backend") { into("backend") }
    from("../../shared") { into("shared") }
    into(generatedPython)
    exclude("**/__pycache__/**", "**/*.pyc")
}
tasks.matching { it.name.startsWith("merge") && it.name.endsWith("PythonSources") }
    .configureEach { dependsOn(syncPython) }

android {
    namespace = "com.proxyhunter.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.proxyhunter.app"
        minSdk = 26          // Android 8.0+
        targetSdk = 35
        versionCode = 300
        versionName = "3.0.0"
        ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a") }
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables { useSupportLibrary = true }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    buildFeatures { compose = true }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

chaquopy {
    defaultConfig {
        version = "3.11"  // supports both ARM64 and ARMv7
        pip {
            install("aiohttp")
            install("aiohttp-socks")
            install("beautifulsoup4")
            install("python-socks")
        }
    }
    sourceSets {
        getByName("main") { srcDirs(generatedPython.get().asFile.absolutePath) }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-compose:1.9.2")
    implementation(platform("androidx.compose:compose-bom:2024.09.02"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.5")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.5")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    debugImplementation("androidx.compose.ui:ui-tooling")
}
