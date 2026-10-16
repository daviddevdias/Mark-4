import com.android.build.api.dsl.ApplicationExtension

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

extensions.configure<ApplicationExtension>("android") {
    namespace = "com.mark2.remoto"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.mark2.remoto"
        minSdk = 26
        targetSdk = 34
        versionCode = 6
        versionName = "1.5"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    buildFeatures {
        compose = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    sourceSets.named("main") {
        kotlin.directories += "src/main/java"
    }
}

dependencies {
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.foundation)
    implementation(libs.compose.material3)
    implementation(libs.compose.material.icons.extended)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.okhttp)
    implementation(libs.vosk.android)

    debugImplementation(libs.compose.ui.tooling)
}

// Valida avisos sem precisar celular
tasks.register<JavaExec>("verificarAvisos") {
    dependsOn("compileDebugUnitTestKotlin")
    classpath = files("build/tmp/kotlin-classes/debugUnitTest", "build/tmp/kotlin-classes/debug") + configurations.getByName("debugUnitTestRuntimeClasspath")
    mainClass.set("com.mark2.remoto.VerificarAvisos")
}
