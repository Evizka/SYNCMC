package com.cenoteswamp.init;

import com.cenoteswamp.CenoteSwampMod;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.ResourceKey;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.world.level.biome.Biome;

public class ModBiomes {
    public static final ResourceKey<Biome> CENOTE_SWAMP =
            ResourceKey.create(Registries.BIOME,
                    ResourceLocation.fromNamespaceAndPath(CenoteSwampMod.MOD_ID, "cenote_swamp"));
}