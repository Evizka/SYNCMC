package com.cenoteswamp.feature;

import com.mojang.serialization.Codec;
import com.mojang.serialization.codecs.RecordCodecBuilder;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.util.RandomSource;
import net.minecraft.world.level.WorldGenLevel;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.levelgen.feature.Feature;
import net.minecraft.world.level.levelgen.feature.FeaturePlaceContext;
import net.minecraft.world.level.levelgen.feature.configurations.FeatureConfiguration;

public class GiantSwampTreeFeature extends Feature<GiantSwampTreeFeature.Config> {

    public GiantSwampTreeFeature(Codec<Config> codec) {
        super(codec);
    }

    public record Config(int minHeight, int maxHeight, int canopyRadius)
            implements FeatureConfiguration {
        public static final Codec<Config> CODEC = RecordCodecBuilder.create(instance ->
                instance.group(
                        Codec.intRange(10, 40).fieldOf("min_height").forGetter(Config::minHeight),
                        Codec.intRange(15, 60).fieldOf("max_height").forGetter(Config::maxHeight),
                        Codec.intRange(5, 15).fieldOf("canopy_radius").forGetter(Config::canopyRadius)
                ).apply(instance, Config::new)
        );
    }

    private static final BlockState OAK_LOG = Blocks.OAK_LOG.defaultBlockState();
    private static final BlockState DARK_OAK_LOG = Blocks.DARK_OAK_LOG.defaultBlockState();
    private static final BlockState LEAVES = Blocks.OAK_LEAVES.defaultBlockState();
    private static final BlockState DARK_LEAVES = Blocks.DARK_OAK_LEAVES.defaultBlockState();

    @Override
    public boolean place(FeaturePlaceContext<Config> ctx) {
        WorldGenLevel level = ctx.level();
        BlockPos origin = ctx.origin();
        RandomSource random = ctx.random();
        Config config = ctx.config();

        if (!level.getBlockState(origin.below()).isSolidRender()) return false;

        int height = config.minHeight() + random.nextInt(config.maxHeight() - config.minHeight() + 1);
        int canopyRadius = config.canopyRadius();

        // Trunk (2x2)
        for (int y = 0; y < height; y++) {
            BlockState log = y < height / 3 ? DARK_OAK_LOG : OAK_LOG;
            for (int dx = 0; dx <= 1; dx++) {
                for (int dz = 0; dz <= 1; dz++) {
                    BlockPos pos = origin.above(y).offset(dx, 0, dz);
                    if (level.getBlockState(pos).canBeReplaced()) {
                        level.setBlock(pos, log, 2);
                    }
                }
            }
        }

        // Branches (4 horizontal directions)
        for (int i = 0; i < 4 + random.nextInt(3); i++) {
            Direction dir = Direction.from2DDataValue(random.nextInt(4));
            int branchY = height / 3 + random.nextInt(height * 2 / 3);
            int branchLen = 4 + random.nextInt(canopyRadius);
            BlockPos.MutableBlockPos mPos = origin.above(branchY).mutable();

            for (int j = 0; j < branchLen; j++) {
                mPos.move(dir);
                if (random.nextFloat() < 0.2f) mPos.move(Direction.UP);
                if (level.getBlockState(mPos).canBeReplaced()) {
                    level.setBlock(mPos, OAK_LOG, 2);
                }
                // Leaves at end
                if (j > branchLen - 3) {
                    placeLeafCluster(level, mPos, 2 + random.nextInt(2), random);
                }
            }
        }

        // Canopy (flat top)
        for (int y = -1; y <= 2; y++) {
            int r = canopyRadius - Math.abs(y);
            for (int x = -r; x <= r; x++) {
                for (int z = -r; z <= r; z++) {
                    if (x * x + z * z <= r * r + random.nextInt(3)) {
                        BlockPos pos = origin.above(height + y).offset(x, 0, z);
                        if (level.getBlockState(pos).canBeReplaced()) {
                            level.setBlock(pos, random.nextFloat() < 0.3f ? DARK_LEAVES : LEAVES, 2);
                        }
                    }
                }
            }
        }

        // Roots
        for (int i = 0; i < 4 + random.nextInt(4); i++) {
            Direction dir = Direction.from2DDataValue(random.nextInt(4));
            int rootLen = 2 + random.nextInt(5);
            BlockPos start = origin.relative(dir, 2);
            for (int y = 0; y < rootLen; y++) {
                BlockPos rp = start.below(y);
                if (level.getBlockState(rp).canBeReplaced()) {
                    level.setBlock(rp, Blocks.MANGROVE_ROOTS.defaultBlockState(), 2);
                }
            }
        }

        return true;
    }

    private void placeLeafCluster(WorldGenLevel level, BlockPos center, int radius, RandomSource random) {
        for (int x = -radius; x <= radius; x++) {
            for (int z = -radius; z <= radius; z++) {
                if (x * x + z * z <= radius * radius) {
                    BlockPos pos = center.offset(x, 0, z);
                    if (level.getBlockState(pos).canBeReplaced()) {
                        level.setBlock(pos, random.nextFloat() < 0.3f ? DARK_LEAVES : LEAVES, 2);
                    }
                }
            }
        }
    }
}