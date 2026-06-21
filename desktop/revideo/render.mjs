import fs from "node:fs";
import path from "node:path";
import {fileURLToPath, pathToFileURL} from "node:url";
import {renderVideo} from "@revideo/renderer";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const desktopRoot = path.resolve(__dirname, "..");
process.chdir(desktopRoot);
const projectFile = "/revideo/src/project.ts";

process.env.DISABLE_TELEMETRY = process.env.DISABLE_TELEMETRY || "true";

const planPath = process.env.AIVE_RENDER_PLAN_PATH;
if (!planPath) {
  throw new Error("AIVE_RENDER_PLAN_PATH must point to a semantic render_plan.json file.");
}

const renderPlan = JSON.parse(fs.readFileSync(planPath, "utf8"));
const sourceVideo = normalizeSourceVideo(
  process.env.AIVE_SOURCE_VIDEO_URL ||
  process.env.AIVE_SOURCE_VIDEO_PATH ||
  renderPlan?.video?.source_url ||
  "",
);
const runtimePlanPath = path.join(__dirname, "runtime-render-plan.json");
fs.writeFileSync(
  runtimePlanPath,
  JSON.stringify(
    {
      ...renderPlan,
      runtime: {
        ...(renderPlan.runtime || {}),
        sourceVideo,
        generatedAt: new Date().toISOString(),
      },
    },
    null,
    2,
  ),
);
const outFile = process.env.AIVE_RENDER_OUTPUT || path.join(desktopRoot, "revideo-output.mp4");
const workers = Number.parseInt(process.env.AIVE_RENDER_WORKERS || "2", 10);
const durationSeconds = Math.max(0.1, Number(renderPlan?.timeline?.duration_seconds || renderPlan?.video?.duration_seconds || 5));
const outDir = path.dirname(path.resolve(outFile));
const outName = path.basename(outFile);

console.log(`Rendering Revideo composition from ${planPath}`);
const output = await renderVideo({
  projectFile,
  variables: {},
  settings: {
    outFile: outName,
    outDir,
    workers: Number.isFinite(workers) && workers > 0 ? workers : 2,
    logProgress: true,
    viteBasePort: Number.parseInt(process.env.AIVE_REVIDEO_BASE_PORT || "9010", 10),
    puppeteer: {
      headless: true,
      args: [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
      ],
    },
    projectSettings: {
      range: [0, durationSeconds],
      size: {x: 1920, y: 1080},
      exporter: {
        name: "@revideo/core/ffmpeg",
        options: {format: "mp4"},
      },
    },
  },
});

cleanupIntermediateFiles(outDir, path.basename(outName, path.extname(outName)));
console.log(output);

function normalizeSourceVideo(value) {
  if (!value) return "";
  if (/^https?:\/\//i.test(value) || value.startsWith("/")) return value;
  return pathToFileURL(path.resolve(value)).href;
}

function cleanupIntermediateFiles(directory, stem) {
  for (const suffix of ["-0.mp4", "-audio.wav", "-visuals.mp4"]) {
    const candidate = path.join(directory, `${stem}${suffix}`);
    if (fs.existsSync(candidate)) {
      fs.rmSync(candidate, {force: true});
    }
  }
}
