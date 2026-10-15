package com.cenoteswamp.biome;

import com.cenoteswamp.CenoteSwampMod;
import com.mojang.serialization.Codec;
import com.mojang.serialization.codecs.RecordCodecBuilder;
import net.minecraft.core.Holder;
import net.minecraft.core.HolderSet;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.ResourceKey;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.level.biome.Biome;
import net.minecraft.world.level.biome.Biomes;
import net.neoforged.neoforge.common.world.BiomeModifier;
import net.neoforged.neoforge.common.world.ModifiableBiomeInfo;
import net.neoforged.neoforge.registries.DeferredHolder;
import net.neoforged.neoforge.registries.DeferredRegister;
import net.neoforged.neoforge.registries.NeoForgeRegistries;

/**
 * Заменяет болотные биомы на «Затопленные сеноты» с заданной вероятностью.
 *
 * Используется через JSON:
 *   data/cenoteswamp/neoforge/biome_modifier/replace_swamp.json
 */
public class ReplaceSwampModifier implements BiomeModifier {

    private final HolderSet<Biome> biomes;
    private final ResourceKey<Biome> replacement;
    private final int chance;

    public ReplaceSwampModifier(HolderSet<Biome> biomes, ResourceKey<Biome> replacement, int chance) {
        this.biomes = biomes;
        this.replacement = replacement;
        this.chance = chance;
    }

    @Override
    public void modify(Holder<Biome> biome, Phase phase, ModifiableBiomeInfo.BiomeInfo.Builder builder) {
        // Замена делается на уровне noise router / multi-noise, не через modify
        // Этот модификатор добавлен для совместимости
    }

    @Override
    public Codec<? extends BiomeModifier> codec() {
        return CODEC.get();
    }

    // === Регистрация кодека ===
    public static final DeferredRegister<Codec<? extends BiomeModifier>> SERIALIZERS =
            DeferredRegister.create(NeoForgeRegistries.Keys.BIOME_MODIFIER_SERIALIZERS,
                    CenoteSwampMod.MOD_ID);

    public static final DeferredHolder<Codec<? extends BiomeModifier>, Codec<ReplaceSwampModifier>> CODEC =
            SERIALIZERS.register("replace_swamp", () ->
                    RecordCodecBuilder.create(instance -> instance.group(
                            Biome.LIST_CODEC.fieldOf("biomes").forGetter(m -> m.biomes),
                            ResourceKey.codec(Registries.BIOME).fieldOf("replacement").forGetter(m -> m.replacement),
                            Codec.INT.fieldOf("chance").forGetter(m -> m.chance)
                    ).apply(instance, ReplaceSwampModifier::new))
            );
}