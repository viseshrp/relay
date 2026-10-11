import { readdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { promisify } from "node:util";
import { brotliCompress, gzip, constants } from "node:zlib";

const br = promisify(brotliCompress),
  gz = promisify(gzip);
export async function compressBuild(root) {
  if (root instanceof URL) root = fileURLToPath(root);
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const path = join(root, entry.name);
    if (entry.isDirectory()) await compressBuild(path);
    else if (entry.isFile() && /\.(?:js|css|html|svg|json)$/.test(entry.name)) {
      const source = await readFile(path);
      if (source.length < 512) continue;
      const [brotli, zipped] = await Promise.all([
        br(source, { params: { [constants.BROTLI_PARAM_QUALITY]: 6 } }),
        gz(source, { level: 9 }),
      ]);
      if (brotli.length < source.length) await writeFile(`${path}.br`, brotli);
      if (zipped.length < source.length) await writeFile(`${path}.gz`, zipped);
    }
  }
}
if (process.argv[1]?.endsWith("compress.mjs"))
  await compressBuild(new URL("../../relay/static/", import.meta.url));
