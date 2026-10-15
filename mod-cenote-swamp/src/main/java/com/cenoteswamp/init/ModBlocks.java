package com.cenoteswamp.init;

import com.cenoteswamp.CenoteSwampMod;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.Item;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.SoundType;
import net.minecraft.world.level.block.state.BlockBehaviour;
import net.minecraft.world.level.material.MapColor;
import net.neoforged.neoforge.registries.DeferredBlock;
import net.neoforged.neoforge.registries.DeferredItem;
import net.neoforged.neoforge.registries.DeferredRegister;

import java.util.function.Supplier;

public class ModBlocks {
    public static final DeferredRegister.Blocks BLOCKS =
            DeferredRegister.createBlocks(CenoteSwampMod.MOD_ID);
    public static final DeferredRegister.Items ITEMS =
            DeferredRegister.createItems(CenoteSwampMod.MOD_ID);

    // Торфяной грунт — основа биома
    public static final DeferredBlock<Block> PEAT = register("peat",
            () -> new Block(BlockBehaviour.Properties.of()
                    .mapColor(MapColor.COLOR_BROWN)
                    .strength(0.8F)
                    .sound(SoundType.MUD)
                    .ignitedByLava()));

    // Тёмная болотная вода (блок декора, не жидкость)
    public static final DeferredBlock<Block> DARK_PEAT = register("dark_peat",
            () -> new Block(BlockBehaviour.Properties.of()
                    .mapColor(MapColor.COLOR_BROWN)
                    .strength(1.0F)
                    .sound(SoundType.MUD)
                    .ignitedByLava()));

    // Светящийся мох для стенок сенот
    public static final DeferredBlock<Block> CENOTE_MOSS = register("cenote_moss",
            () -> new Block(BlockBehaviour.Properties.of()
                    .mapColor(MapColor.COLOR_GREEN)
                    .strength(0.2F)
                    .sound(SoundType.MOSS)
                    .lightLevel(state -> 5)
                    .noCollission()));

    // Корни гигантского дерева
    public static final DeferredBlock<Block> MANGROVE_ROOTS = register("mangrove_roots_block",
            () -> new Block(BlockBehaviour.Properties.of()
                    .mapColor(MapColor.COLOR_BROWN)
                    .strength(2.0F)
                    .sound(SoundType.WOOD)
                    .ignitedByLava()));

    // Грязевой камень (для стенок сенот)
    public static final DeferredBlock<Block> MUDDY_STONE = register("muddy_stone",
            () -> new Block(BlockBehaviour.Properties.of()
                    .mapColor(MapColor.COLOR_GRAY)
                    .strength(1.5F, 6.0F)
                    .sound(SoundType.STONE)));

    private static DeferredBlock<Block> register(String name, Supplier<Block> block) {
        DeferredBlock<Block> registered = BLOCKS.register(name, block);
        ITEMS.register(name, () -> new BlockItem(registered.get(), new Item.Properties()));
        return registered;
    }
}