plugins {
    java
    id("net.neoforged.moddev") version "2.0.78-beta"
}

version = project.findProperty("modVersion") as String? ?: "1.0.0"
group = project.findProperty("modGroup") as String? ?: "com.cenoteswamp"

base {
    archivesName.set("cenoteswamp-${project.findProperty("minecraftVersion") ?: "1.21.1"}")
}

java.toolchain.languageVersion = JavaLanguageVersion.of(21)

neoForge {
    version = project.findProperty("neoForgeVersion") as String? ?: "21.1.77"

    runs {
        create("client") {
            client()
            systemProperty("neoforge.enabledGameTestNamespaces", "cenoteswamp")
        }
        create("data") {
            data()
            programArguments.addAll(
                "--mod", "cenoteswamp",
                "--all",
                "--output", file("src/generated/resources/").absolutePath,
                "--existing", file("src/main/resources/").absolutePath
            )
        }
    }

    mods {
        create("cenoteswamp") {
            sourceSet(sourceSets.main.get())
        }
    }
}

repositories {
    mavenCentral()
}

tasks.withType<ProcessResources>().configureEach {
    val props = mapOf(
        "modId" to (project.findProperty("modId") ?: "cenoteswamp"),
        "modName" to (project.findProperty("modName") ?: "Cenote Swamp"),
        "modVersion" to (project.findProperty("modVersion") ?: "1.0.0"),
        "modDescription" to (project.findProperty("modDescription") ?: "Deep cenote pits in a mystical swamp biome."),
        "modAuthor" to (project.findProperty("modAuthor") ?: "Evizka"),
        "neoForgeVersion" to (project.findProperty("neoForgeVersion") ?: "21.1.77"),
        "minecraftVersion" to (project.findProperty("minecraftVersion") ?: "1.21.1")
    )
    inputs.properties(props)
    filesMatching(listOf("META-INF/neoforge.mods.toml")) {
        expand(props)
    }
}