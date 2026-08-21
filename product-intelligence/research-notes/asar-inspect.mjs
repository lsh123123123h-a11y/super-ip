import { pathToFileURL } from "node:url";

const [modulePath, archivePath, action, ...args] = process.argv.slice(2);
if (!modulePath || !archivePath || !action) {
  throw new Error("usage: node asar-inspect.mjs <asar-module> <archive> <cat|grep> ...");
}

const asar = await import(pathToFileURL(modulePath).href);

function extractArchiveFile(filePath) {
  const trimmed = filePath.replace(/^[/\\]/, "");
  const candidates = [
    filePath,
    trimmed,
    trimmed.replaceAll("/", "\\"),
    trimmed.replaceAll("\\", "/"),
  ];
  let lastError;
  for (const candidate of [...new Set(candidates)]) {
    try {
      return asar.extractFile(archivePath, candidate);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
}

if (action === "cat") {
  for (const filePath of args) {
    process.stdout.write(`\n===== ${filePath} =====\n`);
    process.stdout.write(extractArchiveFile(filePath).toString("utf8"));
  }
} else if (action === "grep") {
  const [textPattern, pathPattern = ".*", rawLimit = "200"] = args;
  const textRegex = new RegExp(textPattern, "giu");
  const pathRegex = new RegExp(pathPattern, "iu");
  const limit = Number.parseInt(rawLimit, 10);
  let emitted = 0;

  for (const archiveEntry of asar.listPackage(archivePath)) {
    const filePath = archiveEntry.replace(/^[/\\]/, "");
    if (!pathRegex.test(filePath)) continue;
    let text;
    try {
      text = extractArchiveFile(filePath).toString("utf8");
    } catch {
      continue;
    }
    const seen = new Set();
    for (const match of text.matchAll(textRegex)) {
      const start = Math.max(0, match.index - 140);
      const end = Math.min(text.length, match.index + match[0].length + 220);
      const snippet = text.slice(start, end).replace(/\s+/g, " ");
      if (seen.has(snippet)) continue;
      seen.add(snippet);
      process.stdout.write(`\n[${filePath}] ${snippet}\n`);
      emitted += 1;
      if (emitted >= limit) process.exit(0);
    }
  }
} else {
  throw new Error(`unsupported action: ${action}`);
}
