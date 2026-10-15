package com.cenoteswamp.feature;

import com.mojang.serialization.Codec;
import com.mojang.serialization.codecs.RecordCodecBuilder;
import net.minecraft.core.BlockPos;
import net.minecraft.util.Mth;
import net.minecraft.util.RandomSource;
import net.minecraft.world.level.WorldGenLevel;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.levelgen.feature.Feature;
import net.minecraft.world.level.levelgen.feature.FeaturePlaceContext;
import net.minecraft.world.level.levelgen.feature.configurations.FeatureConfiguration;

public class CenoteFeature extends Feature<CenoteFeature.Config> {

    public CenoteFeature(Codec<Config> codec) {
        super(codec);
    }

    public record Config(int minRadius, int maxRadius, int minDepth, int maxDepth)
            implements FeatureConfiguration {
        public static final Codec<Config> CODEC = RecordCodecBuilder.create(instance ->
                instance.group(
                        Codec.intRange(3, 20).fieldOf("min_radius").forGetter(Config::minRadius),
                        Codec.intRange(5, 40).fieldOf("max_radius").forGetter(Config::maxRadius),
                        Codec.intRange(10, 80).fieldOf("min_depth").forGetter(Config::minDepth),
                        Codec.intRange(20, 120).fieldOf("max_depth").forGetter(Config::maxDepth)
                ).apply(instance, Config::new)
        );
    }

    @Override
    public boolean place(FeaturePlaceContext<Config> ctx) {
        WorldGenLevel level = ctx.level();
        BlockPos origin = ctx.origin();
        RandomSource random = ctx.random();
        Config config = ctx.config();

        int depth = Mth.randomBetweenInclusive(random, config.minDepth(), config.maxDepth());
        int radius = Mth.randomBetweenInclusive(random, config.minRadius(), config.maxRadius());

        // Dig the cenote
        for (int y = 0; y < depth; y++) {
            float progress = (float) y / depth;
            float r = radius * (1.0f - progress * 0.4f);
            r += random.nextFloat() - 0.5f;
            int ri = Math.max(1, (int) r);

            for (int x = -ri; x <= ri; x++) {
                for (int z = -ri; z <= ri; z++) {
                    if (x * x + z * z <= ri * ri) {
                        BlockPos pos = origin.below(y).offset(x, 0, z);
                        if (y < depth - 3) {
                            level.setBlock(pos, Blocks.AIR.defaultBlockState(), 2);
                        } else {
                            level.setBlock(pos, Blocks.WATER.defaultBlockState(), 2);
                        }
                    }
                }
            }

            // Walls
            if (random.nextFloat() < 0.3f) {
                for (int x = -ri - 1; x <= ri + 1; x++) {
                    for (int z = -ri - 1; z <= ri + 1; z++) {
                        double dist = Math.sqrt(x * x + z * z);
                        if (dist > ri - 0.5 && dist <= ri + 1.5) {
                            BlockPos wall = origin.below(y).offset(x, 0, z);
                            if (random.nextFloat() < 0.5f) {
                                level.setBlock(wall, Blocks.MOSSY_COBBLESTONE.defaultBlockState(), 2);
                            }
                        }
                    }
                }
            }
        }

        // Floor
        for (int x = -radius / 2; x <= radius / 2; x++) {
            for (int z = -radius / 2; z <= radius / 2; z++) {
                if (x * x + z * z <= (radius / 2) * (radius / 2)) {
                    BlockPos floor = origin.below(depth).offset(x, 0, z);
                    level.setBlock(floor, Blocks.CLAY.defaultBlockState(), 2);
                }
            }
        }

        // Hanging roots from top
        for (int i = 0; i < radius; i++) {
            double angle = random.nextDouble() * Math.PI * 2;
            double dist = random.nextDouble() * radius * 0.8;
            int x = (int) (Math.cos(angle) * dist);
            int z = (int) (Math.sin(angle) * dist);
            int rootLen = 2 + random.nextInt(4);
            for (int y = 0; y < rootLen; y++) {
                BlockPos rp = origin.offset(x, -y, z);
                if (level.getBlockState(rp).isAir()) {
                    level.setBlock(rp, Blocks.OAK_FENCE.defaultBlockState(), 2);
                }
            }
        }

        return true;
    }
}