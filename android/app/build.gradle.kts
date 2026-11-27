plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.proxyhunter.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.proxyhunter.app"
        minSdk = 26          // Android 8.0+
        targetSdk = 35
        versionCode = 300
        versionName = "3.0.0"
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
        version = "3.12"
        pip {
            install("aiohttp")
            install("aiohttp-socks")
            install("beautifulsoup4")
            install("python-socks")
        }
    }
    sourceSets {
        getByName("main") {
            srcDirs(
                "src/main/python",
                "../../backend",   // shared controller
                "../../shared",    // shared export engine
                "../../proxyhunter" // existing v2/v3 engine
            )
        }
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
