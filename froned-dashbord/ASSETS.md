# Orbit artwork

## Original generated crew

- Production asset: `app/assets/orbit-crew.webp` (1024×1024, 100,526 bytes), used as a 4×4 CSS
  sprite atlas. Each avatar has fixed dimensions, avoiding layout shift. There are 16 original
  fictional characters, 14 used for the crew and others for the workspace and growth graphics.
- Built-in `image_gen` generation was used, not the API/CLI fallback.
- Original output retained at `/Users/apple/.codex/generated_images/01a16352-8bbc-7342-b7e3-a0c7e0ac8546/exec-26d49c3a-1600-4b75-970b-b13b7a6d3c11.png`.
- Converted to WebP with `cwebp -q 82 -resize 1024 1024`; the project needs only the local WebP.
- The workspace character is a fictional avatar, not a photograph of the account owner.

Final prompt:

> Use case: stylized-concept. Asset type: one production avatar atlas image for a premium dark
> career dashboard called Orbit. Create a precise 4 by 4 grid of sixteen separate high-end 3D
> vinyl character head avatars. Every tile is exactly the same size, on an identical solid very
> dark charcoal background #1b1d24. No visible grid lines. Each character is centered, fully
> contained in its tile, with 18% clear padding around the entire head and shoulders. All sixteen
> heads use the same soft studio light, real ambient occlusion, beautifully modeled forms,
> polished ceramic and satin vinyl material, memorable and friendly but sophisticated for Gen Z.
> Their faces have expressive black capsule eyes, small smiles, no uncanny realistic humans.
> Distinct character types in reading order: lavender capsule robot with headphones; mint rounded
> square explorer bot with a small antenna; peach round pilot bot with a glass visor; periwinkle
> astronaut bot with a metallic ring around the head; warm ivory robot with black faceplate; sage
> companion bot with two rounded ears; dusty rose rounded AI character; blue gray bookish bot with
> round glasses; charcoal professional bot with lilac side panels; purple creative bot with
> asymmetrical antenna; ivory helpful robot with peach cheeks; mint study bot with a tiny visor;
> lavender star-shaped soft sculpture character with two eyes; peach round investigator bot with
> large glasses; silver chrome pearl robot with gentle lavender reflections; rich violet pill
> shaped mascot with a single ring around its head. Every character is an original identity, no
> copyrighted characters, no brand logos, NO TEXT, NO LETTERS, NO WATERMARK. These should be finished
> polished 3D avatar assets, not flat vector icons, not a UI mockup. Square overall image, uniform
> 4x4 layout, 16 cleanly separated tiles, dark background that blends into #1b1d24 UI. Aim for
> exceptional shape design and tactile lighting.

## Code-native graphics and typography

`app/js/components/identity.js` contains the original Orbit mark and filled/duotone navigation
set. Familiar small action symbols use the existing code-native utility set. Source Sans3 is
locally hosted; its license is included under `app/fonts/`.

## Visual reference

[iBanko Finance Dashboard UI Concept, Anik Deb](https://dribbble.com/shots/19411888-iBanko-Finance-Dashboard-UI-Concept)
was used for composition and hierarchy. The tablet image is retained only in ignored QA artifacts.
Its logo, financial figures, portraits and card imagery are not shipped in Orbit.

## Orbit world extension — October 23, 2026

- Mode: built-in imagegen; existing `orbit-crew.webp` supplied as a style reference, viewed before generation.
- Saved original: `/Users/apple/.codex/generated_images/01a16352-8bbc-7342-b7e3-a0c7e0ac8546/exec-e9488db6-a1f0-461d-9936-f95e465fdf78.png` (1254×1254).
- Production: `app/assets/orbit-world.webp` (1024×1024, 108,128 bytes). Converted with cwebp quality 85. Original retained.
- Eight new portraits (indices16–23) and eight section emblems (24–31). Total selectable workspace portraits: 24. The atlas is centrally cropped within each CSS tile to avoid neighboring-row bleed; no screenshot is used as UI.
- New portraits identify Hirist/Instahyre/Cutshort/Wellfound profile agents and extend the workspace picker. Emblems identify Orbit, Research Studio, Data hub, Action inbox, Flows, Reports, Learning path and Preferences.
- No platform logos or implied platform affiliation. Existing vector utility icons remain for common actions.

Final prompt:

> Use case: stylized-concept. Asset type: a production 4 by 4 sprite atlas for Orbit, a dark career dashboard. Input image is a STYLE REFERENCE only, preserve its premium glossy vinyl 3D material, rounded cute bot faces, studio rim light, tasteful lavender/mint/peach/slate palette. Generate a NEW atlas of sixteen distinct graphics on a uniform charcoal #191b22 backdrop, exactly four equal columns and four equal rows, no gaps, no borders, no text. Each figure is centered WITHIN its 256px square cell of a 1024px square image, safely contained with 18px margin, even scale, no objects crossing cell boundaries. Row 1: four NEW friendly head-and-shoulder robot avatars for profile update specialists: mint bot with clear round visor and tiny leaf antenna; peach bot with headphones and square glasses; lavender bot with sleek swept helmet and small star antenna; slate blue bot with silver glasses and circular ear pads. Row 2: four NEW user avatar mascots: cream bot with small lavender bowtie; lilac cat-eared robot; pearl silver floating orb bot; sage green explorer bot. Row 3: four matching beautiful dimensional standalone app emblems without faces: purple ringed planet (Orbit brand); mint magnifying glass over purple open book (Research Studio); three stacked translucent lavender data cylinders with mint accents (Data hub); peach mail tray with one cream card (Action inbox). Row 4: four matching dimensional emblems: lilac and mint connected flow nodes (Flows); cream report sheet with purple tiny bar graph (Reports); mint graduation cap on lavender book (Learning path); lavender polished cog with pearl center (Preferences). Camera orthographic-ish front three-quarter, highly polished soft studio lighting, gentle cast shadows confined to cells, no bright background, no labels, no brand logos, no watermark. Keep professional collectible designer-toy quality matching reference. Prioritize clean legibility at 48px. This is an asset atlas, not a dashboard screenshot.

### Delivery variants

Both generated originals are also encoded at the same 1024×1024 dimensions as AVIF with FFmpeg/SVT-AV1 (CRF34). CSS `image-set` selects AVIF on supporting browsers and retains WebP fallback. `app/assets/orbit-crew.avif` is 61,463 bytes; `app/assets/orbit-world.avif` is 58,376 bytes. Combined image transfer drops from 208,654 to 119,839 bytes without removing graphics or changing layout/materials. Browser screenshots verify the rendered variants.
