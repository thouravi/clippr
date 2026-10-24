import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";
import type { ClipResult, Highlight, ParsedDemo, ProgressEvent, ToolStatus } from "./types";

export function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export function onProgress(handler: (event: ProgressEvent) => void): Promise<UnlistenFn> {
  return listen<ProgressEvent>("clippr-progress", (event) => handler(event.payload));
}

export function getStatus(): Promise<ToolStatus> {
  return invoke<ToolStatus>("app_status");
}

export function ensureTools(): Promise<ToolStatus> {
  return invoke<ToolStatus>("ensure_tools");
}

export function parseDemo(path: string): Promise<ParsedDemo> {
  return invoke<ParsedDemo>("parse_demo", { path });
}

export function generateClip(input: {
  demoPath: string;
  highlight: Highlight;
  tickrate: number;
  leadIn: number;
  leadOut: number;
  outputDir: string;
}): Promise<ClipResult> {
  return invoke<ClipResult>("generate_clip", {
    demoPath: input.demoPath,
    highlight: input.highlight,
    tickrate: input.tickrate,
    leadIn: input.leadIn,
    leadOut: input.leadOut,
    outputDir: input.outputDir,
  });
}

export function cancelJob(): Promise<void> {
  return invoke("cancel_job");
}

export async function pickDemo(): Promise<string | null> {
  const selected = await open({
    title: "Select a CS2 demo",
    multiple: false,
    filters: [
      { name: "CS2 demo", extensions: ["dem", "gz", "zst"] },
      { name: "All files", extensions: ["*"] },
    ],
  });
  if (typeof selected === "string") return selected;
  return null;
}

export async function pickFolder(): Promise<string | null> {
  const selected = await open({
    title: "Choose a folder for clips",
    directory: true,
    multiple: false,
  });
  if (typeof selected === "string") return selected;
  return null;
}
