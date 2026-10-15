package com.cenoteswamp.feature;

import com.mojang.serialization.Codec;
import com.mojang.serialization.codecs.RecordCodecBuilder;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Holder;
import net.minecraft.util.Mth;
import net.minecraft.util.RandomSource;
import net.minecraft.world.level.WorldGenLevel;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.levelgen.feature.Feature;
import net.minecraft.world.level.levelgen.feature.FeaturePlaceContext;
import net.minecraft.world.level.levelgen.feature.configurations.FeatureConfiguration;

/**
 * Сенот — глубокий карстовый провал, заполненный водой.
 *
 * Генерирует вертикальную шахту с:
 * - Неровными стенами из грязевого камня и гальки
 * - Пологим входом, сужающимся к глубине
 * - Водой на дне с подводной пещерой
 * - Светящимся мхом на стенах
 * - Мангровыми корнями сверху
 * - Иногда подводной системой пещер
 */
public class CenoteFeature extends Feature<CenoteFeature.Config> {

    public CenoteFeature(Codec<Config> codec) {
        super(codec);
    }

    public record Config(
            int minRadius, int maxRadius,
            int minDepth, int maxDepth,
            float waterRatio
    ) implements FeatureConfiguration {
        public static final Codec<Config> CODEC = RecordCodecBuilder.create(instance ->
                instance.group(
                        Codec.intRange(3, 20).fieldOf("min_radius").forGetter(Config::minRadius),
                        Codec.intRange(5, 40).fieldOf("max_radius").forGetter(Config::maxRadius),
                        Codec.intRange(10, 80).fieldOf("min_depth").forGetter(Config::minDepth),
                        Codec.intRange(20, 120).fieldOf("max_depth").forGetter(Config::maxDepth),
                        Codec.floatRange(0.1f, 1.0f).fieldOf("water_ratio").forGetter(Config::waterRatio)
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
        int surfaceRadius = Mth.randomBetweenInclusive(random, config.minRadius(), config.maxRadius());
        int waterLevel = (int) (depth * config.waterRatio());

        // Не генерировать если слишком высоко
        if (origin.getY() > level.getMaxBuildHeight() - depth) return false;

        // Определяем реальную поверхность
        BlockPos surface = findSurface(level, origin);
        if (surface == null) return false;

        int baseY = surface.getY();

        // === 1. Выкапываем верхнюю воронку (пологий вход) ===
        int funnelDepth = depth / 4;
        for (int y = 0; y < funnelDepth; y++) {
            float progress = (float) y / funnelDepth;
            float radius = surfaceRadius * (1.0f - progress * 0.3f);
            carveCircle(level, surface.below(y), radius, random);
        }

        // === 2. Вертикальная шахта с неровными стенами ===
        int shaftTop = funnelDepth;
        int shaftBottom = depth - waterLevel;
        for (int y = shaftTop; y < shaftBottom; y++) {
            float progress = (float) (y - shaftTop) / (shaftBottom - shaftTop);
            float radius = surfaceRadius * 0.7f * (1.0f - progress * 0.5f);
            // Случайная неровность стен
            radius += random.nextFloat() * 1.5f - 0.75f;
            carveCircle(level, surface.below(y), Math.max(2, radius), random);
        }

        // === 3. Подводная камера (расширяется к низу) ===
        int caveTop = shaftBottom;
        int caveBottom = depth;
        for (int y = caveTop; y < caveBottom; y++) {
            float progress = (float) (y - caveTop) / (caveBottom - caveTop);
            // Сначала расширяется, потом сужается
            float bulge = (float) Math.sin(progress * Math.PI);
            float radius = surfaceRadius * 0.6f + surfaceRadius * 0.8f * bulge;
            radius += random.nextFloat() * 2.0f - 1.0f;
            carveCircle(level, surface.below(y), Math.max(3, radius), random);
        }

        // === 4. Заполняем водой от waterLevel до дна ===
        for (int y = caveBottom; y >= shaftBottom - 2; y--) {
            float progress = (float) (y - shaftTop) / (caveBottom - shaftTop);
            float radius = getRadiusAt(progress, surfaceRadius);
            fillWithWater(level, surface.below(y), radius + 1);
        }

        // === 5. Стены из грязевого камня и гальки ===
        for (int y = 0; y < depth; y++) {
            float progress = (float) y / depth;
            float radius = getRadiusAt(progress, surfaceRadius);
            placeWalls(level, surface.below(y), radius, random, y < shaftBottom);
        }

        // === 6. Светящийся мох на стенах ===
        for (int y = 0; y < depth; y++) {
            float progress = (float) y / depth;
            float radius = getRadiusAt(progress, surfaceRadius);
            placeMoss(level, surface.below(y), radius, random);
        }

        // === 7. Корни сверху (нависают над входом) ===
        placeRoots(level, surface, surfaceRadius, random);

        // === 8. Дно — глина и гравий ===
        placeFloor(level, surface.below(depth), surfaceRadius * 0.5f, random);

        return true;
    }

    private float getRadiusAt(float progress, int surfaceRadius) {
        if (progress < 0.25f) {
            // Воронка — плавное сужение
            return surfaceRadius * (1.0f - progress * 1.2f);
        } else if (progress < 0.7f) {
            // Шахта — узкая
            float shaftProgress = (progress - 0.25f) / 0.45f;
            return surfaceRadius * 0.7f * (1.0f - shaftProgress * 0.5f);
        } else {
            // Пещера — расширяется
            float caveProgress = (progress - 0.7f) / 0.3f;
            float bulge = (float) Math.sin(caveProgress * Math.PI);
            return surfaceRadius * 0.5f + surfaceRadius * 0.7f * bulge;
        }
    }

    private BlockPos findSurface(WorldGenLevel level, BlockPos pos) {
        for (int y = level.getMaxBuildHeight() - 1; y > level.getMinBuildHeight() + 20; y--) {
            BlockPos check = pos.atY(y);
            if (level.getBlockState(check).isAir() &&
                    !level.getBlockState(check.below()).isAir()) {
                return check;
            }
        }
        return null;
    }

    private void carveCircle(WorldGenLevel level, BlockPos center, float radius, RandomSource random) {
        int r = (int) Math.ceil(radius);
        for (int x = -r; x <= r; x++) {
            for (int z = -r; z <= r; z++) {
                double dist = Math.sqrt(x * x + z * z);
                if (dist <= radius + random.nextFloat() * 0.5) {
                    BlockPos pos = center.offset(x, 0, z);
                    BlockState state = level.getBlockState(pos);
                    // Не выкапываем бедрок
                    if (!state.is(Blocks.BEDROCK) && !state.isAir()) {
                        level.setBlock(pos, Blocks.AIR.defaultBlockState(), 2);
                    }
                }
            }
        }
    }

    private void fillWithWater(WorldGenLevel level, BlockPos center, float radius) {
        int r = (int) Math.ceil(radius);
        for (int x = -r; x <= r; x++) {
            for (int z = -r; z <= r; z++) {
                if (x * x + z * z <= radius * radius) {
                    BlockPos pos = center.offset(x, 0, z);
                    if (level.getBlockState(pos).isAir()) {
                        level.setBlock(pos, Blocks.WATER.defaultBlockState(), 2);
                    }
                }
            }
        }
    }

    private void placeWalls(WorldGenLevel level, BlockPos center, float radius,
                            RandomSource random, boolean isUpper) {
        int r = (int) Math.ceil(radius) + 1;
        for (int x = -r; x <= r; x++) {
            for (int z = -r; z <= r; z++) {
                double dist = Math.sqrt(x * x + z * z);
                // Только края — стенки
                if (dist > radius - 1.5 && dist <= radius + 1.0) {
                    BlockPos pos = center.offset(x, 0, z);
                    BlockState current = level.getBlockState(pos);
                    if (!current.isAir() && !current.is(Blocks.WATER)) {
                        // Смешиваем камень, гальку, грязь
                        BlockState wall;
                        float roll = random.nextFloat();
                        if (roll < 0.4f) {
                            wall = Blocks.COBBLESTONE.defaultBlockState();
                        } else if (roll < 0.7f) {
                            wall = Blocks.MUD.defaultBlockState();
                        } else if (roll < 0.85f) {
                            wall = Blocks.GRAVEL.defaultBlockState();
                        } else {
                            wall = Blocks.STONE.defaultBlockState();
                        }
                        level.setBlock(pos, wall, 2);
                    }
                }
            }
        }
    }

    private void placeMoss(WorldGenLevel level, BlockPos center, float radius, RandomSource random) {
        int r = (int) Math.ceil(radius) + 1;
        for (int x = -r; x <= r; x++) {
            for (int z = -r; z <= r; z++) {
                double dist = Math.sqrt(x * x + z * z);
                if (dist > radius - 1.0 && dist <= radius + 0.5 && random.nextFloat() < 0.3f) {
                    BlockPos pos = center.offset(x, 0, z);
                    BlockState current = level.getBlockState(pos);
                    if (current.is(Blocks.COBBLESTONE) || current.is(Blocks.STONE)) {
                        // Мох на стенах
                        level.setBlock(pos, Blocks.MOSSY_COBBLESTONE.defaultBlockState(), 2);
                    }
                }
            }
        }
    }

    private void placeRoots(WorldGenLevel level, BlockPos surface, int radius, RandomSource random) {
        // Корни свисают сверху — на 2-5 блоков вниз от края воронки
        for (int i = 0; i < radius * 2; i++) {
            double angle = random.nextDouble() * Math.PI * 2;
            double dist = random.nextDouble() * radius * 0.8;
            int x = (int) (Math.cos(angle) * dist);
            int z = (int) (Math.sin(angle) * dist);

            int rootLength = 2 + random.nextInt(4);
            BlockPos start = surface.offset(x, 0, z);

            // Только если под корнем есть воздух (воронка)
            if (level.getBlockState(start.below()).isAir()) {
                for (int y = 0; y < rootLength; y++) {
                    BlockPos rootPos = start.below(y);
                    if (level.getBlockState(rootPos).isAir()) {
                        level.setBlock(rootPos,
                                random.nextFloat() < 0.7f ?
                                        Blocks.MANGROVE_ROOTS.defaultBlockState() :
                                        Blocks.OAK_FENCE.defaultBlockState(),
                                2);
                    } else {
                        break;
                    }
                }
            }
        }
    }

    private void placeFloor(WorldGenLevel level, BlockPos center, float radius, RandomSource random) {
        int r = (int) Math.ceil(radius);
        for (int x = -r; x <= r; x++) {
            for (int z = -r; z <= r; z++) {
                if (x * x + z * z <= radius * radius) {
                    BlockPos pos = center.offset(x, 0, z);
                    BlockState floor;
                    float roll = random.nextFloat();
                    if (roll < 0.5f) {
                        floor = Blocks.CLAY.defaultBlockState();
                    } else if (roll < 0.8f) {
                        floor = Blocks.GRAVEL.defaultBlockState();
                    } else {
                        floor = Blocks.SAND.defaultBlockState();
                    }
                    level.setBlock(pos, floor, 2);
                }
            }
        }
    }
}