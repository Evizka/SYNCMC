package com.cenoteswamp.feature;

import com.mojang.serialization.Codec;
import com.mojang.serialization.codecs.RecordCodecBuilder;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.util.RandomSource;
import net.minecraft.world.level.WorldGenLevel;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.LeavesBlock;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.levelgen.feature.Feature;
import net.minecraft.world.level.levelgen.feature.FeaturePlaceContext;
import net.minecraft.world.level.levelgen.feature.configurations.FeatureConfiguration;

/**
 * Гигантское болотное дерево — массивный ствол с горизонтальными ветвями,
 * воздушными корнями и густой тёмной кроной.
 *
 * Вдохновлено кипарисовыми болотами и мангровыми лесами:
 * - Толстый ствол (3-5 блоков в диаметре)
 * - Горизонтальные ветви, уходящие далеко в стороны
 * - Воздушные корни, свисающие с ветвей
 * - Плоская густая крона
 * - Лианы и мхи
 */
public class GiantSwampTreeFeature extends Feature<GiantSwampTreeFeature.Config> {

    public GiantSwampTreeFeature(Codec<Config> codec) {
        super(codec);
    }

    public record Config(
            int minHeight, int maxHeight,
            int minTrunkWidth, int maxTrunkWidth,
            int canopyRadius,
            int branchCount
    ) implements FeatureConfiguration {
        public static final Codec<Config> CODEC = RecordCodecBuilder.create(instance ->
                instance.group(
                        Codec.intRange(12, 40).fieldOf("min_height").forGetter(Config::minHeight),
                        Codec.intRange(15, 60).fieldOf("max_height").forGetter(Config::maxHeight),
                        Codec.intRange(1, 3).fieldOf("min_trunk_width").forGetter(Config::minTrunkWidth),
                        Codec.intRange(2, 5).fieldOf("max_trunk_width").forGetter(Config::maxTrunkWidth),
                        Codec.intRange(6, 18).fieldOf("canopy_radius").forGetter(Config::canopyRadius),
                        Codec.intRange(3, 10).fieldOf("branch_count").forGetter(Config::branchCount)
                ).apply(instance, Config::new)
        );
    }

    private static final BlockState OAK_LOG = Blocks.OAK_LOG.defaultBlockState();
    private static final BlockState DARK_OAK_LOG = Blocks.DARK_OAK_LOG.defaultBlockState();
    private static final BlockState OAK_LEAVES = Blocks.OAK_LEAVES.defaultBlockState()
            .setValue(LeavesBlock.DISTANCE, 1);
    private static final BlockState DARK_LEAVES = Blocks.DARK_OAK_LEAVES.defaultBlockState()
            .setValue(LeavesBlock.DISTANCE, 1);
    private static final BlockState MOSS_CARPET = Blocks.MOSS_CARPET.defaultBlockState();
    private static final BlockState VINE = Blocks.VINE.defaultBlockState();
    private static final BlockState MANGROVE_ROOTS = Blocks.MANGROVE_ROOTS.defaultBlockState();
    private static final BlockState MUD = Blocks.MUD.defaultBlockState();

    @Override
    public boolean place(FeaturePlaceContext<Config> ctx) {
        WorldGenLevel level = ctx.level();
        BlockPos origin = ctx.origin();
        RandomSource random = ctx.random();
        Config config = ctx.config();

        // Проверяем что под деревом есть земля
        if (!level.getBlockState(origin.below()).isSolid()) return false;

        int height = randomInt(random, config.minHeight(), config.maxHeight());
        int trunkWidth = randomInt(random, config.minTrunkWidth(), config.maxTrunkWidth());

        // === 1. Ствол ===
        placeTrunk(level, origin, height, trunkWidth, random);

        // === 2. Ветви от середины ствола вверх ===
        int branchStart = height / 3;
        for (int i = 0; i < config.branchCount(); i++) {
            int branchY = branchStart + random.nextInt(height - branchStart - 4);
            Direction dir = Direction.from2DDataValue(random.nextInt(4));
            int branchLength = 5 + random.nextInt(config.canopyRadius());
            placeBranch(level, origin.above(branchY), dir, branchLength, trunkWidth, random);
        }

        // === 3. Крона — густая плоская шапка ===
        int canopyY = height - 3;
        placeCanopy(level, origin.above(canopyY), config.canopyRadius(), random);

        // === 4. Воздушные корни с ветвей ===
        placeAerialRoots(level, origin, height, config.canopyRadius(), random);

        // === 5. Лианы ===
        placeVines(level, origin, height, trunkWidth, random);

        // === 6. Мшистое основание ===
        placeMossyBase(level, origin, trunkWidth + 2, random);

        return true;
    }

    private void placeTrunk(WorldGenLevel level, BlockPos base, int height, int width, RandomSource random) {
        int halfW = width / 2;
        for (int y = 0; y < height; y++) {
            // Ствол слегка сужается к верху
            float taper = 1.0f - (float) y / height * 0.3f;
            int currentWidth = Math.max(1, (int) (halfW * taper));

            for (int x = -currentWidth; x <= currentWidth; x++) {
                for (int z = -currentWidth; z <= currentWidth; z++) {
                    // Круглое сечение
                    if (x * x + z * z <= currentWidth * currentWidth + 1) {
                        BlockPos pos = base.above(y).offset(x, 0, z);
                        if (level.getBlockState(pos).canBeReplaced()) {
                            // Тёмная древесина для нижней части, обычная для верхней
                            BlockState log = y < height / 3 ? DARK_OAK_LOG : OAK_LOG;
                            // Корявые повороты текстуры
                            if (random.nextFloat() < 0.3f && Math.abs(x) + Math.abs(z) > 0) {
                                log = y < height / 3 ?
                                        Blocks.DARK_OAK_WOOD.defaultBlockState() :
                                        Blocks.OAK_WOOD.defaultBlockState();
                            }
                            level.setBlock(pos, log, 2);
                        }
                    }
                }
            }
        }
    }

    private void placeBranch(WorldGenLevel level, BlockPos start, Direction dir,
                             int length, int trunkWidth, RandomSource random) {
        BlockPos.MutableBlockPos pos = start.mutable();

        for (int i = 0; i < length; i++) {
            // Ветви идут горизонтально, слегка вверх
            pos.move(dir, 1);
            if (random.nextFloat() < 0.2f) pos.move(Direction.UP);

            // Толщина ветви уменьшается
            int branchWidth = Math.max(0, 1 - i / (length / 2));
            placeLogRadius(level, pos, branchWidth, random);

            // На конце ветви — листва
            if (i > length - 4) {
                placeLeafCluster(level, pos, 2 + random.nextInt(2), random);
            }

            // Висячие корни с ветвей
            if (random.nextFloat() < 0.25f && i > 3) {
                placeHangingRoot(level, pos.below(), 3 + random.nextInt(5), random);
            }
        }
    }

    private void placeCanopy(WorldGenLevel level, BlockPos center, int radius, RandomSource random) {
        // Плоская крона с неровными краями
        for (int y = -2; y <= 3; y++) {
            int layerRadius = radius - Math.abs(y);
            if (layerRadius <= 0) continue;

            for (int x = -layerRadius; x <= layerRadius; x++) {
                for (int z = -layerRadius; z <= layerRadius; z++) {
                    double dist = Math.sqrt(x * x + z * z);
                    if (dist <= layerRadius + random.nextFloat() * 2 - 1) {
                        BlockPos pos = center.offset(x, y, z);
                        if (level.getBlockState(pos).canBeReplaced()) {
                            BlockState leaf = random.nextFloat() < 0.3f ? DARK_LEAVES : OAK_LEAVES;
                            level.setBlock(pos, leaf, 2);

                            // Мох поверх листвы (самый верхний слой)
                            if (y >= 2 && random.nextFloat() < 0.15f) {
                                BlockPos above = pos.above();
                                if (level.getBlockState(above).isAir()) {
                                    level.setBlock(above, MOSS_CARPET, 2);
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    private void placeAerialRoots(WorldGenLevel level, BlockPos base, int height,
                                  int radius, RandomSource random) {
        // Корни свисают с ветвей
        int rootCount = 3 + random.nextInt(6);
        for (int i = 0; i < rootCount; i++) {
            double angle = random.nextDouble() * Math.PI * 2;
            double dist = 2 + random.nextDouble() * radius * 0.7;
            int x = (int) (Math.cos(angle) * dist);
            int z = (int) (Math.sin(angle) * dist);

            int startY = height / 2 + random.nextInt(height / 2);
            int rootLength = 3 + random.nextInt(8);

            BlockPos.MutableBlockPos pos = base.offset(x, startY, z).mutable();
            for (int y = 0; y < rootLength; y++) {
                pos.move(Direction.DOWN);
                BlockState current = level.getBlockState(pos);
                if (current.isAir()) {
                    // Корни слегка изгибаются
                    if (random.nextFloat() < 0.2f) {
                        pos.move(Direction.from2DDataValue(random.nextInt(4)));
                    }
                    level.setBlock(pos, MANGROVE_ROOTS, 2);
                } else if (current.isSolid()) {
                    break;
                }
            }
        }
    }

    private void placeVines(WorldGenLevel level, BlockPos base, int height,
                            int trunkWidth, RandomSource random) {
        // Лианы свисают со ствола
        for (int i = 0; i < trunkWidth * 4; i++) {
            int y = height / 3 + random.nextInt(height * 2 / 3);
            Direction side = Direction.from2DDataValue(random.nextInt(4));
            BlockPos vineStart = base.above(y).relative(side, trunkWidth / 2 + 1);

            if (level.getBlockState(vineStart).isAir()) {
                int vineLength = 3 + random.nextInt(8);
                for (int v = 0; v < vineLength; v++) {
                    BlockPos vinePos = vineStart.below(v);
                    if (level.getBlockState(vinePos).isAir()) {
                        level.setBlock(vinePos, VINE, 2);
                    } else {
                        break;
                    }
                }
            }
        }
    }

    private void placeMossyBase(WorldGenLevel level, BlockPos base, int radius, RandomSource random) {
        // Мшистое основание вокруг ствола
        for (int x = -radius; x <= radius; x++) {
            for (int z = -radius; z <= radius; z++) {
                if (x * x + z * z <= radius * radius && random.nextFloat() < 0.6f) {
                    BlockPos pos = base.offset(x, 0, z);
                    BlockPos above = pos.above();
                    if (level.getBlockState(pos).isSolid() && level.getBlockState(above).isAir()) {
                        if (random.nextFloat() < 0.4f) {
                            level.setBlock(above, MOSS_CARPET, 2);
                        } else if (random.nextFloat() < 0.3f) {
                            level.setBlock(above, MUD, 2);
                        }
                    }
                }
            }
        }
    }

    private void placeLogRadius(WorldGenLevel level, BlockPos pos, int radius, RandomSource random) {
        for (int x = -radius; x <= radius; x++) {
            for (int z = -radius; z <= radius; z++) {
                BlockPos logPos = pos.offset(x, 0, z);
                if (level.getBlockState(logPos).canBeReplaced()) {
                    level.setBlock(logPos, OAK_LOG, 2);
                }
            }
        }
    }

    private void placeLeafCluster(WorldGenLevel level, BlockPos center, int radius, RandomSource random) {
        for (int x = -radius; x <= radius; x++) {
            for (int y = -1; y <= 1; y++) {
                for (int z = -radius; z <= radius; z++) {
                    if (x * x + y * y + z * z <= radius * radius + random.nextInt(2)) {
                        BlockPos pos = center.offset(x, y, z);
                        if (level.getBlockState(pos).canBeReplaced()) {
                            level.setBlock(pos, random.nextFloat() < 0.3f ?
                                    DARK_LEAVES : OAK_LEAVES, 2);
                        }
                    }
                }
            }
        }
    }

    private void placeHangingRoot(WorldGenLevel level, BlockPos start, int length, RandomSource random) {
        BlockPos.MutableBlockPos pos = start.mutable();
        for (int i = 0; i < length; i++) {
            if (level.getBlockState(pos).isAir()) {
                level.setBlock(pos, MANGROVE_ROOTS, 2);
            } else {
                break;
            }
            pos.move(Direction.DOWN);
            if (random.nextFloat() < 0.15f) {
                pos.move(Direction.from2DDataValue(random.nextInt(4)));
            }
        }
    }

    private int randomInt(RandomSource random, int min, int max) {
        return min + random.nextInt(max - min + 1);
    }
}