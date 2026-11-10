plugins {
    id("com.android.application")
    id("com.chaquo.python")
    id("org.jetbrains.kotlin.plugin.compose")
}
android {
    namespace = "local.werewolf.probe"
    compileSdk = 36
    defaultConfig {
        applicationId = "local.werewolf.probe"
        minSdk = 34
        targetSdk = 36
        versionCode = 2
        versionName = "mobile-local-0.1"
        ndk { abiFilters += "arm64-v8a" }
    }
    buildFeatures { compose = true; buildConfig = true }
    bundle { language { enableSplit = false } }
}
dependencies {
    implementation(platform("androidx.compose:compose-bom:2026.05.00"))
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.10.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.10.0")
}
chaquopy {
    defaultConfig {
        version = "3.12"
        buildPython(providers.gradleProperty("probe.python").getOrElse("python3.12"))
    }
    sourceSets { getByName("main") { srcDir("build/staged-python") } }
}

val stageEngine by tasks.registering(Exec::class) {
    workingDir(rootProject.projectDir)
    commandLine(providers.gradleProperty("probe.python").getOrElse("python3.12"), "stage_engine.py")
}
tasks.configureEach {
    if (name == "preBuild" || name.endsWith("PythonSources")) dependsOn(stageEngine)
}
