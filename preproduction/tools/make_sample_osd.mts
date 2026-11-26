/**
 * Build a sample `.osd` package with Open Shot Designer's own code, for tests and demos.
 *
 * It starts from the app's bundled example production and swaps the SVG sketch boards for
 * real image files, the way a user's uploads would be stored (content-addressed assets).
 *
 *   vendor/osd/node_modules/.bin/tsx tools/make_sample_osd.mts --out sample.osd img1.png img2.png ...
 *
 * Images are dealt out to shots in board order; a shot whose camera moves gets a second board
 * on its last waypoint when there are enough images.
 */
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { extname } from 'node:path';
import { parseArgs } from 'node:util';
import { createProject } from '../vendor/osd/src/utils/projectLibrary';
import { exportProjectPackageV2 } from '../vendor/osd/src/utils/projectPackageV2';
import type { CameraElement } from '../vendor/osd/src/types';

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: { out: { type: 'string' }, title: { type: 'string' } },
});
if (!values.out || positionals.length === 0) {
  console.error('Usage: tsx tools/make_sample_osd.mts --out <file.osd> [--title T] <image>...');
  process.exit(1);
}

const MIME: Record<string, string> = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp' };
const assets = new Map<string, { data: Uint8Array; mimeType: string }>();
const images: string[] = [];
for (const file of positionals) {
  const data = new Uint8Array(await readFile(file));
  const id = `asset-sha256-${createHash('sha256').update(data).digest('hex')}`;
  assets.set(id, { data, mimeType: MIME[extname(file).toLowerCase()] ?? 'image/png' });
  images.push(id);
}

const project = createProject({
  title: values.title ?? 'HelloWorld Sample',
  director: 'Sample Director',
  withSampleScenes: true,
});

let next = 0;
const take = () => images[next++ % images.length];
for (const setup of project.setups) {
  const cameras = new Map(
    setup.elements.filter((el): el is CameraElement => el.type === 'camera').map((el) => [el.id, el]),
  );
  for (const shot of setup.shots) {
    shot.storyboardImage = undefined;
    shot.storyboardFrames = { start: { image: take(), note: `Board for ${shot.shotNumber}` } };
    const path = cameras.get(shot.cameraId)?.path ?? [];
    if (path.length && next < images.length) {
      shot.storyboardFrames[path[path.length - 1].id] = { image: take(), note: 'End of move' };
    }
  }
}

const store = {
  async get(id: string) {
    const asset = assets.get(id);
    return asset ? new Blob([asset.data], { type: asset.mimeType }) : null;
  },
  async getMetadata(id: string) {
    const asset = assets.get(id);
    return asset
      ? { mimeType: asset.mimeType, byteSize: asset.data.byteLength, createdAt: new Date().toISOString() }
      : null;
  },
};
const blob = await exportProjectPackageV2(project, store);
await writeFile(values.out, new Uint8Array(await blob.arrayBuffer()));
const shots = project.setups.reduce((n, s) => n + s.shots.length, 0);
console.log(JSON.stringify({ out: values.out, scenes: project.setups.length, shots, images: images.length }));
