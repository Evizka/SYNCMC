package com.cenoteswamp;

import com.cenoteswamp.init.ModBlocks;
import com.cenoteswamp.init.ModFeatures;
import net.neoforged.bus.api.IEventBus;
import net.neoforged.fml.common.Mod;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

@Mod(CenoteSwampMod.MOD_ID)
public class CenoteSwampMod {
    public static final String MOD_ID = "cenoteswamp";
    public static final Logger LOG = LoggerFactory.getLogger(MOD_ID);

    public CenoteSwampMod(IEventBus modBus) {
        ModBlocks.BLOCKS.register(modBus);
        ModBlocks.ITEMS.register(modBus);
        ModFeatures.FEATURES.register(modBus);
        LOG.info("Cenote Swamp loaded.");
    }
}