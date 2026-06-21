import {makeScene2D, Rect, Txt, Video} from "@revideo/2d";
import {waitFor} from "@revideo/core";
import runtimeRenderPlan from "../runtime-render-plan.json";

type RenderPlan = {
  video?: {source_url?: string; filename?: string};
  timeline?: {duration_seconds?: number};
  slides?: RenderSlide[];
  scenes?: RenderScene[];
};

type RenderSlide = {
  id: string;
  title: string;
  body?: string;
  bullets?: string[];
  source_filename?: string | null;
};

type RenderScene = {
  id: string;
  source_start_time?: number;
  start_time: number;
  end_time: number;
  duration_seconds: number;
  layout: string;
  slide_id: string;
  caption_text?: string;
  topic_label?: string;
};

export default makeScene2D("aive-lecture-composition", function* (view) {
  const plan = parsePlan(runtimeRenderPlan);
  const sourceVideo = String((plan as RenderPlan & {runtime?: {sourceVideo?: string}}).runtime?.sourceVideo || plan.video?.source_url || "");
  const scenes = Array.isArray(plan.scenes) && plan.scenes.length > 0
    ? plan.scenes
    : [fallbackScene(plan)];

  let previousRoot: Rect | null = null;
  for (const scene of scenes) {
    previousRoot?.remove();
    const slide = slideForScene(plan, scene);
    const root = sceneNode(scene, slide, sourceVideo);
    view.add(root);
    previousRoot = root;
    yield* waitFor(Math.max(0.1, Number(scene.duration_seconds) || 0.1));
  }
});

function sceneNode(scene: RenderScene, slide: RenderSlide, sourceVideo: string) {
  const layout = scene.layout || "picture_in_picture";
  const isCameraFull = layout === "full_camera_source";
  const isSideBySide = layout === "side_by_side";
  const isSlideOnly = layout === "full_screen_source";
  const caption = scene.caption_text || scene.topic_label || "";

  return (
    <Rect width={1920} height={1080} fill={"#070812"}>
      {isCameraFull ? (
        cameraVideo(sourceVideo, 960, 540, 1920, 1080, scene.source_start_time || 0)
      ) : isSideBySide ? (
        <>
          {slideCard(slide, 500, 540, 920, 980)}
          {cameraVideo(sourceVideo, 1440, 540, 880, 980, scene.source_start_time || 0)}
        </>
      ) : (
        <>
          {slideCard(slide, 960, 540, 1920, 1080)}
          {!isSlideOnly && cameraVideo(sourceVideo, 1580, 250, 380, 380, scene.source_start_time || 0)}
        </>
      )}
      {caption && (
        <Rect x={0} y={438} width={1540} height={116} radius={22} fill={"rgba(15, 23, 42, 0.82)"}>
          <Txt
            text={caption}
            width={1440}
            height={74}
            fill={"#ffffff"}
            fontSize={38}
            fontFamily={"Inter, Arial"}
            textAlign={"center"}
          />
        </Rect>
      )}
    </Rect>
  );
}

function slideCard(slide: RenderSlide, x: number, y: number, width: number, height: number) {
  const bullets = Array.isArray(slide.bullets) && slide.bullets.length > 0
    ? slide.bullets.slice(0, 4)
    : [slide.body || ""].filter(Boolean);
  return (
    <Rect x={x - 960} y={y - 540} width={width} height={height} fill={"#f8fafc"}>
      <Txt
        x={-width / 2 + 94}
        y={-height / 2 + 96}
        text={slide.source_filename || "AI teaching slide"}
        fill={"#2563eb"}
        fontSize={30}
        fontFamily={"Inter, Arial"}
        fontWeight={700}
      />
      <Txt
        x={-width / 2 + 94}
        y={-height / 2 + 225}
        text={slide.title || "Teaching point"}
        width={Math.max(420, width - 190)}
        fill={"#111827"}
        fontSize={72}
        lineHeight={82}
        fontFamily={"Inter, Arial"}
        fontWeight={800}
      />
      {slide.body && (
        <Txt
          x={-width / 2 + 94}
          y={-height / 2 + 430}
          text={slide.body}
          width={Math.max(420, width - 220)}
          fill={"#334155"}
          fontSize={39}
          lineHeight={50}
          fontFamily={"Inter, Arial"}
        />
      )}
      {bullets.map((bullet, index) => (
        <Rect
          key={`${slide.id}-${index}`}
          x={-width / 2 + 118}
          y={height / 2 - 250 + index * 86}
          width={Math.max(420, width - 260)}
          height={64}
          radius={16}
          fill={"#ffffff"}
          stroke={"#cbd5e1"}
          lineWidth={2}
        >
          <Txt
            x={18}
            text={bullet}
            width={Math.max(360, width - 330)}
            fill={"#1f2937"}
            fontSize={31}
            lineHeight={38}
            fontFamily={"Inter, Arial"}
            fontWeight={600}
          />
        </Rect>
      ))}
    </Rect>
  );
}

function cameraVideo(sourceVideo: string, x: number, y: number, width: number, height: number, seek: number) {
  if (!sourceVideo) {
    return <Rect x={x - 960} y={y - 540} width={width} height={height} radius={28} fill={"#111827"} />;
  }
  return (
    <Rect x={x - 960} y={y - 540} width={width} height={height} radius={32} clip fill={"#000000"} stroke={"rgba(15,23,42,0.35)"} lineWidth={5}>
      <Video src={sourceVideo} width={width} height={height} play time={seek} />
    </Rect>
  );
}

function parsePlan(raw: unknown): RenderPlan {
  return typeof raw === "object" && raw ? raw as RenderPlan : {};
}

function slideForScene(plan: RenderPlan, scene: RenderScene): RenderSlide {
  return plan.slides?.find((slide) => slide.id === scene.slide_id) || {
    id: "fallback-slide",
    title: scene.topic_label || "Lecture Overview",
    body: scene.caption_text || "Generated teaching slide",
    bullets: [],
    source_filename: plan.video?.filename || null,
  };
}

function fallbackScene(plan: RenderPlan): RenderScene {
  const duration = Math.max(0.1, Number(plan.timeline?.duration_seconds || 5));
  return {
    id: "scene-0001",
    start_time: 0,
    end_time: duration,
    duration_seconds: duration,
    layout: "picture_in_picture",
    slide_id: plan.slides?.[0]?.id || "fallback-slide",
  };
}
