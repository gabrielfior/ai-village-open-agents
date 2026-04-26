/**
 * Validate that SDK version references across all markdown files match
 * the canonical versions defined in NETWORK_CONFIG.md.
 */

import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');

// Canonical SDK versions (source of truth)
const CANONICAL_VERSIONS: Record<string, string> = {
  '@0glabs/0g-ts-sdk': '^0.3.3',
  '@0glabs/0g-serving-broker': '^0.6.5',
  'ethers': '^6.13.0',
};

function globMarkdown(dir: string): string[] {
  const results: string[] = [];
  if (!fs.existsSync(dir)) return results;

  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...globMarkdown(fullPath));
    } else if (entry.name.endsWith('.md')) {
      results.push(fullPath);
    }
  }
  return results;
}

function main() {
  console.log('Validating SDK version references...\n');

  const mdFiles = [
    ...globMarkdown(path.join(ROOT, 'skills')),
    ...globMarkdown(path.join(ROOT, 'patterns')),
  ];

  let errors = 0;

  for (const mdFile of mdFiles) {
    const content = fs.readFileSync(mdFile, 'utf-8');
    const relPath = path.relative(ROOT, mdFile);

    for (const [pkg, expectedVersion] of Object.entries(CANONICAL_VERSIONS)) {
      // Match patterns like: `@0glabs/0g-ts-sdk` ^0.3.3 or `@0glabs/0g-ts-sdk ^0.3.3`
      const escapedPkg = pkg.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const versionPattern = new RegExp(
        `\`${escapedPkg}\`\\s+\\^?\\d+\\.\\d+\\.\\d+|${escapedPkg}[\\s@]+\\^?(\\d+\\.\\d+\\.\\d+)`,
        'g'
      );

      let match;
      while ((match = versionPattern.exec(content)) !== null) {
        const matchedText = match[0];
        // Extract the version number
        const versionMatch = matchedText.match(/\^?(\d+\.\d+\.\d+)/);
        if (versionMatch) {
          const foundVersion = `^${versionMatch[1]}`;
          if (foundVersion !== expectedVersion) {
            const line = content.substring(0, match.index).split('\n').length;
            console.error(
              `${relPath}:${line} — ${pkg} version mismatch: found ${foundVersion}, expected ${expectedVersion}`
            );
            errors++;
          }
        }
      }
    }
  }

  if (errors > 0) {
    console.error(`\n${errors} version mismatch(es) found. Update to match NETWORK_CONFIG.md.`);
    process.exit(1);
  }

  console.log(`Checked ${mdFiles.length} files — all SDK versions consistent!`);
}

main();
