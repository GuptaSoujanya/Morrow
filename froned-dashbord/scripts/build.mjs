import { build } from 'esbuild';
import { readFile, writeFile, mkdir, cp } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../', import.meta.url));
const result = await build({ absWorkingDir: root,
  entryPoints: { main: 'app/js/main.js', workspace: 'app/styles/index.css' },
  bundle: true, minify: true, format: 'esm', target: ['es2022'], outdir: 'dist/assets',
  loader: { '.woff2': 'file', '.webp':'file', '.avif':'file' }, assetNames: '[name]-[hash]', publicPath:'/assets', metafile: true });
let html = await readFile(root + 'app/index.html', 'utf8');
html = html.replace(/  <link rel="stylesheet"[^>]+\/>\n/g, '');
// Inline the small, compressed application shell so local cold loads do not queue
// a separate module request behind the initial API requests. Assets stay external.
const css=await readFile(root+'dist/assets/workspace.css','utf8');
html = html.replace('</head>', `  <style>${css}</style>\n</head>`);
const script=await readFile(root+'dist/assets/main.js','utf8');
html = html.replace('<script type="module" src="./js/main.js"></script>',()=>`<script type="module">${script.replace(/<\/script/gi,'<\\/script')}</script>`);
for (const name of Object.keys(result.metafile.outputs).filter(name => /source-sans-3-|fraunces-500-/.test(name))) {
  html = html.replace('  <meta name="color-scheme" content="dark" />', `  <meta name="color-scheme" content="dark" />\n  <link rel="preload" href="/${name.replace('dist/', '')}" as="font" type="font/woff2" crossorigin fetchpriority="high" />`);
}
await mkdir(root + 'dist', { recursive: true });
await writeFile(root + 'dist/index.html', html);
await mkdir(root + 'artifacts', { recursive: true });
await writeFile(root + 'artifacts/build-meta.json', JSON.stringify(result.metafile, null, 2));
await cp(root + 'app/fonts', root + 'dist/fonts', { recursive: true });
console.log('Dashboard built: inline application shell, local graphics and typography.');
