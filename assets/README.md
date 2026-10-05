# Original launcher artwork

Every theme has its own local Minecraft Java-style voxel background, selected automatically
when the user changes themes. The scene descriptions below are also the intended visible block
inventory used for a manual vanilla-block audit:

| Theme | Asset | Scene and intended in-game blocks |
| --- | --- | --- |
| Aurora | `aurora-world.jpg` | Purple night over a spruce lake: grass/dirt/stone, spruce logs/leaves, water and lanterns |
| Forest | `forest-world.jpg` | Lush river forest: grass/dirt, oak/spruce logs and leaves, ferns, tall grass, vanilla flowers and water |
| Nord | `nord-world.jpg` | Blue-hour snowy taiga: snow blocks/layers, spruce logs/leaves, ice, water, stone and a lantern |
| Ember | `ember-world.jpg` | Sunset Badlands: red sand, red/orange/yellow terracotta, cactus and dead bush |
| Graphite | `graphite-world.jpg` | Underground cave: stone, deepslate, cobbled deepslate, tuff, water and wall torches |
| Paper | `paper-world.jpg` | Bright snowy plains: snow blocks/layers, spruce logs/leaves, ice, water, grass and dirt |

## Block audit and limitations

The listed block families were manually audited against the Minecraft Java block/biome
catalog. In particular, deepslate, cobbled deepslate and tuff are real underground Overworld
blocks; stone, water and wall torches are standard Java blocks. Glow-lichen-like patches from an
earlier cave draft were removed because the generated artwork made them look like raised ore
crystals. The earlier autumn-tree Ember draft was replaced with a Badlands scene so its warm
colors come from recognizable terracotta and red sand rather than ambiguous orange foliage.
Badlands naturally feature red sand, terracotta bands, cacti and dead bushes. Reference pages:
[Deepslate](https://minecraft.wiki/w/Deepslate),
[Cobbled Deepslate](https://minecraft.wiki/w/Cobbled_Deepslate),
[Tuff](https://minecraft.wiki/w/Tuff), [Stone](https://minecraft.wiki/w/Stone),
[Torch](https://minecraft.wiki/w/Torch), [Water](https://minecraft.wiki/w/Water),
[Badlands](https://minecraft.wiki/w/Badlands),
[Snowy Plains](https://minecraft.wiki/w/Snowy_Plains),
[Grass](https://minecraft.wiki/w/Grass) and [Leaves](https://minecraft.wiki/w/Leaves).

These are original AI-generated illustrations, not actual game captures or Mojang texture assets.
The table documents the intended, visually distinguishable block families; image generation
cannot guarantee that every shaded pixel or tiny texture detail is an exact vanilla texture/ID.
The final images were visually reviewed for cubic, grid-aligned silhouettes and obvious invented
objects. No runtime image download is used.

`app-icon.png` is the selected MCSync brand mark: a simple, flat pixel-art portal on a dark
background, using restrained teal and violet accents. It has no paired blocks or sync ring.
`app-icon.ico` and `app-icon.icns` include multiple native sizes derived from the same artwork.
The Qt window, taskbar and PyInstaller bundles use these local assets. The icon is original
artwork, not an in-game screenshot.

Qt draws the interface, small vector illustrations and state indicators separately. Any
screenshots in `designs/` use temporary offline demo data, not the user's real worlds or party.
