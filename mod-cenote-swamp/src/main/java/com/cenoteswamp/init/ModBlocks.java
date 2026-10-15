package com.cenoteswamp.init;

import com.cenoteswamp.CenoteSwampMod;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.Item;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.SoundType;
import net.minecraft.world.level.block.state.BlockBehaviour;
import net.minecraft.world.level.material.MapColor;
import net.neoforged.neoforge.registries.DeferredBlock;
import net.neoforged.neoforge.registries.DeferredItem;
import net.neoforged.neoforge.registries.DeferredRegister;

public class ModBlocks {
    public static final DeferredRegister.Blocks BLOCKS =
            DeferredRegister.createBlocks(CenoteSwampMod.MOD_ID);
    public static final DeferredRegister.Items ITEMS =
            DeferredRegister.createItems(CenoteSwampMod.MOD_ID);

    public static final DeferredBlock<Block> PEAT = BLOCKS.registerSimpleBlock("peat",
            BlockBehaviour.Properties.of()
                    .mapColor(MapColor.COLOR_BROWN)
                    .strength(0.8F)
                    .sound(SoundType.MUD));

    public static final DeferredBlock<Block> DARK_PEAT = BLOCKS.registerSimpleBlock("dark_peat",
            BlockBehaviour.Properties.of()
                    .mapColor(MapColor.COLOR_BROWN)
                    .strength(1.0F)
                    .sound(SoundType.MUD));

    public static final DeferredBlock<Block> CENOTE_MOSS = BLOCKS.registerSimpleBlock("cenote_moss",
            BlockBehaviour.Properties.of()
                    .mapColor(MapColor.COLOR_GREEN)
                    .strength(0.2F)
                    .sound(SoundType.MOSS)
                    .lightLevel(state -> 5));

    public static final DeferredBlock<Block> MUDDY_STONE = BLOCKS.registerSimpleBlock("muddy_stone",
            BlockBehaviour.Properties.of()
                    .mapColor(MapColor.COLOR_GRAY)
                    .strength(1.5F, 6.0F)
                    .sound(SoundType.STONE));

    public static final DeferredItem<BlockItem> PEAT_ITEM = ITEMS.registerSimpleBlockItem(PEAT);
    public static final DeferredItem<BlockItem> DARK_PEAT_ITEM = ITEMS.registerSimpleBlockItem(DARK_PEAT);
    public static final DeferredItem<BlockItem> CENOTE_MOSS_ITEM = ITEMS.registerSimpleBlockItem(CENOTE_MOSS);
    public static final DeferredItem<BlockItem> MUDDY_STONE_ITEM = ITEMS.registerSimpleBlockItem(MUDDY_STONE);
}