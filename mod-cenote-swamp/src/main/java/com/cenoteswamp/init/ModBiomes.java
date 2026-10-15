package com.cenoteswamp.init;

import com.cenoteswamp.CenoteSwampMod;
import net.minecraft.core.Holder;
import net.minecraft.core.registries.Registries;
import net.minecraft.data.worldgen.BiomeDefaultFeatures;
import net.minecraft.data.worldgen.placement.AquaticPlacements;
import net.minecraft.data.worldgen.placement.VegetationPlacements;
import net.minecraft.resources.ResourceKey;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.sounds.Music;
import net.minecraft.sounds.Musics;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.util.Mth;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.MobCategory;
import net.minecraft.world.level.biome.*;
import net.minecraft.world.level.levelgen.GenerationStep;

import javax.annotation.Nullable;

/**
 * Регистрация и определение биома «Затопленные сеноты».
 *
 * Атмосфера:
 * - Тёмная болотная вода (зеленовато-чёрная)
 * - Густой туман (маленькая даль видимости)
 * - Тёмная трава и листва
 * - Тяжёлая атмосфера — тихая музыка с каплями воды
 *
 * Генерация:
 * - Равнинный рельеф с локальными понижениями
 * - Сеноты разбросаны по биому
 * - Гигантские деревья
 * - Много воды и грязи
 * - Кувшинки, камыш, грибы
 */
public class ModBiomes {

    public static final ResourceKey<Biome> CENOTE_SWAMP =
            ResourceKey.create(Registries.BIOME,
                    ResourceLocation.fromNamespaceAndPath(CenoteSwampMod.MOD_ID, "cenote_swamp"));

    public static void init() {
        // Биом регистрируется через JSON (data/cenoteswamp/worldgen/biome/cenote_swamp.json)
        // Этот класс хелперы и ключ
    }

    /**
     * Создаёт параметры биома для data-gen или программного использования.
     */
    public static Biome cenoteSwamp(HolderGetter<net.minecraft.world.level.levelgen.placement.PlacedFeature> features,
                                     HolderGetter<net.minecraft.world.level.levelgen.feature.ConfiguredFeature<?, ?>> configured) {

        BiomeGenerationSettings.Builder gen = new BiomeGenerationSettings.Builder(features, configured);

        // === Поверхность ===
        // Стандартные озёра и руды
        BiomeDefaultFeatures.addDefaultCarvers(gen);
        BiomeDefaultFeatures.addDefaultMonsterRoom(gen);
        BiomeDefaultFeatures.addDefaultUndergroundVariety(gen);
        BiomeDefaultFeatures.addDefaultSprings(gen);

        // === Растительность ===
        // Тростник (камыш)
        gen.addFeature(GenerationStep.Decoration.VEGETAL_DECORATION, AquaticPlacements.PATCH_SUGAR_CANE_SWAMP);
        // Кувшинки
        gen.addFeature(GenerationStep.Decoration.VEGETAL_DECORATION, AquaticPlacements.PATCH_WATERLILY);
        // Грибы
        gen.addFeature(GenerationStep.Decoration.VEGETAL_DECORATION, VegetationPlacements.PATCH_BROWN_MUSHROOM);
        gen.addFeature(GenerationStep.Decoration.VEGETAL_DECORATION, VegetationPlacements.PATCH_RED_MUSHROOM);
        // Трава
        gen.addFeature(GenerationStep.Decoration.VEGETAL_DECORATION, VegetationPlacements.PATCH_GRASS_SWAMP);

        // === Кастомные фичи ===
        // Сеноты (через placed feature JSON)
        // Гигантские деревья (через placed feature JSON)

        // === Мобы ===
        MobSpawnSettings.Builder spawn = new MobSpawnSettings.Builder();

        // Болотные мобы
        spawn.addSpawn(MobCategory.CREATURE,
                new MobSpawnSettings.SpawnerData(EntityType.FROG, 10, 2, 5));

        // Слизни — фирменные мобы болота
        spawn.addSpawn(MobCategory.MONSTER,
                new MobSpawnSettings.SpawnerData(EntityType.SLIME, 100, 4, 6));

        // Обычные болотные мобы
        spawn.addSpawn(MobCategory.MONSTER,
                new MobSpawnSettings.SpawnerData(EntityType.ZOMBIE, 95, 4, 4));
        spawn.addSpawn(MobCategory.MONSTER,
                new MobSpawnSettings.SpawnerData(EntityType.DROWNED, 80, 2, 4));
        spawn.addSpawn(MobCategory.MONSTER,
                new MobSpawnSettings.SpawnerData(EntityType.WITCH, 5, 1, 1));

        // Рыбы в сенотах
        spawn.addSpawn(MobCategory.WATER_CREATURE,
                new MobSpawnSettings.SpawnerData(EntityType.TROPICAL_FISH, 20, 3, 6));
        spawn.addSpawn(MobCategory.WATER_CREATURE,
                new MobSpawnSettings.SpawnerData(EntityType.PUFFERFISH, 10, 1, 3));
        spawn.addSpawn(MobCategory.WATER_AMBIENT,
                new MobSpawnSettings.SpawnerData(EntityType.COD, 15, 2, 4));

        // Аксолотли — жители сенот!
        spawn.addSpawn(MobCategory.UNDERGROUND_WATER_CREATURE,
                new MobSpawnSettings.SpawnerData(EntityType.AXOLOTL, 8, 1, 3));

        // Ambient
        spawn.addSpawn(MobCategory.AMBIENT,
                new MobSpawnSettings.SpawnerData(EntityType.BAT, 10, 8, 8));

        // === Климат ===
        // Темно, влажно, прохладно
        return new Biome.BiomeBuilder()
                .temperature(0.7f)     // Тёплый (болото)
                .downfall(0.9f)        // Очень влажный
                .hasPrecipitation(true)
                // Тёмная атмосфера
                .specialEffects(new BiomeSpecialEffects.Builder()
                        .waterColor(0x1a3320)           // Тёмно-зелёная вода
                        .waterFogColor(0x0d1a10)        // Ещё темнее туман воды
                        .fogColor(0x4a5a3a)             // Болотный туман
                        .skyColor(0x5a6a4a)             // Мутное небо
                        .grassColorOverride(0x3a4a2a)   // Тёмная трава
                        .foliageColorOverride(0x2a3a1a) // Тёмная листва
                        .ambientMoodSound(new AmbientMoodSettings(
                                SoundEvents.AMBIENT_CAVE.value(), 6000, 8, 0.5))
                        .backgroundMusic(Musics.createGameMusic(
                                Holder.direct(net.minecraft.sounds.SoundEvents.MUSIC_UNDER_WATER.value())))
                        .build())
                .mobSpawnSettings(spawn.build())
                .generationSettings(gen.build())
                .build();
    }

    /** Цвет неба по высоте (имитация густого тумана) */
    private static int calculateSkyColor(float temperature) {
        float clampedTemp = Mth.clamp(temperature / 3.0f, -1.0f, 1.0f);
        // Более тёмный, болотный цвет неба
        return Mth.color(0.35f, 0.4f + clampedTemp * 0.1f, 0.3f);
    }
}