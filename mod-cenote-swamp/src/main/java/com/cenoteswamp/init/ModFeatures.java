package com.cenoteswamp.init;

import com.cenoteswamp.CenoteSwampMod;
import net.minecraft.core.registries.Registries;
import net.minecraft.world.level.levelgen.feature.Feature;
import net.neoforged.neoforge.registries.DeferredHolder;
import net.neoforged.neoforge.registries.DeferredRegister;
import com.cenoteswamp.feature.CenoteFeature;
import com.cenoteswamp.feature.GiantSwampTreeFeature;

public class ModFeatures {
    public static final DeferredRegister<Feature<?>> FEATURES =
            DeferredRegister.create(Registries.FEATURE, CenoteSwampMod.MOD_ID);

    public static final DeferredHolder<Feature<?>, Feature<CenoteFeature.Config>> CENOTE =
            FEATURES.register("cenote",
                    () -> new CenoteFeature(CenoteFeature.Config.CODEC));

    public static final DeferredHolder<Feature<?>, Feature<GiantSwampTreeFeature.Config>> GIANT_SWAMP_TREE =
            FEATURES.register("giant_swamp_tree",
                    () -> new GiantSwampTreeFeature(GiantSwampTreeFeature.Config.CODEC));
}