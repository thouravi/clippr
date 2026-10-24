import { useEffect, useMemo, useRef, useState } from "react";
import {
  cancelJob,
  ensureTools,
  generateClip,
  getStatus,
  inTauri,
  onProgress,
  parseDemo,
  pickDemo,
  pickFolder,
} from "./api";
import { HIGHLIGHT_TYPES, matchesTypeFilter, highlightTypes } from "./filters";
import { skippedSeconds } from "./pace";
import { previewDemo, previewStatus } from "./preview";
import type { ClipResult, Highlight, ParsedDemo, ToolStatus } from "./types";

type Settings = {
  leadIn: number;
  leadOut: number;
  outputDir: string;
};

const SETTINGS_KEY = "clippr-settings";
const desktop = inTauri();

function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return { leadIn: 5, leadOut: 3, outputDir: "" };
    const parsed = JSON.parse(raw) as Partial<Settings>;
    return {
      leadIn: clamp(Number(parsed.leadIn ?? 5), 1, 12),
      leadOut: clamp(Number(parsed.leadOut ?? 3), 1, 8),
      outputDir: typeof parsed.outputDir === "string" ? parsed.outputDir : "",
    };
  } catch {
    return { leadIn: 5, leadOut: 3, outputDir: "" };
  }
}

function clamp(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) return min;
  return Math.min(max, Math.max(min, value));
}

function mapLabel(name: string): string {
  const bare = name.replace(/^de_|^cs_/i, "").replace(/_/g, " ");
  return bare.replace(/\b\w/g, (letter) => letter.toUpperCase()) || "Unknown map";
}

function clock(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return `${minutes}:${rest.toString().padStart(2, "0")}`;
}

function fileName(path: string): string {
  const parts = path.split(/[/\\]/);
  return parts[parts.length - 1] || path;
}

function clipLength(highlight: Highlight, tickrate: number, leadIn: number, leadOut: number): number {
  const rate = Math.max(tickrate, 1);
  const span = (highlight.focus_end_tick - highlight.focus_start_tick) / rate;
  const skipped = skippedSeconds(highlight.kill_ticks ?? [], rate);
  return Math.max(1, Math.round(span + leadIn + leadOut - skipped));
}

function badgeClass(type: string): string {
  if (type === "Ace" || type.startsWith("1v") || type === "4K") return "bg-amber text-ink";
  if (type === "Noscope" || type === "Wallbang") return "bg-rose-400/90 text-ink";
  if (type === "Opening") return "bg-sky-400/90 text-ink";
  return "bg-white/10 text-white";
}

export default function App() {
  const [status, setStatus] = useState<ToolStatus | null>(desktop ? null : previewStatus);
  const [demo, setDemo] = useState<ParsedDemo | null>(desktop ? null : previewDemo);
  const [player, setPlayer] = useState("all");
  const [types, setTypes] = useState<string[]>([]);
  const [settings, setSettings] = useState<Settings>(loadSettings);
  const [busy, setBusy] = useState<string | null>(null);
  const [progress, setProgress] = useState<{ stage: string; message: string; percent: number | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [clips, setClips] = useState<Record<string, ClipResult>>({});
  const previewCancelled = useRef(false);

  useEffect(() => {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  }, [settings]);

  useEffect(() => {
    if (!desktop) return;
    let stop = false;
    const unlisten = onProgress((event) => {
      if (!event.message) return;
      setProgress({
        stage: event.stage || "working",
        message: event.message,
        percent: typeof event.percent === "number" ? event.percent : null,
      });
    });
    getStatus()
      .then((next) => {
        if (!stop) setStatus(next);
      })
      .catch((reason: unknown) => {
        if (!stop) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      stop = true;
      void unlisten.then((fn) => fn());
    };
  }, []);

  const forPlayer = useMemo(() => {
    if (!demo) return [];
    if (player === "all") return demo.highlights;
    return demo.highlights.filter((item) => item.steamid === player);
  }, [demo, player]);

  const visible = useMemo(
    () => forPlayer.filter((item) => matchesTypeFilter(item, types)),
    [forPlayer, types],
  );

  const typeCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of forPlayer) {
      for (const kind of highlightTypes(item)) counts.set(kind, (counts.get(kind) ?? 0) + 1);
    }
    return counts;
  }, [forPlayer]);

  const availableTypes = HIGHLIGHT_TYPES.filter((item) => (typeCounts.get(item.id) ?? 0) > 0 || types.includes(item.id));

  const toolsReady = Boolean(status?.hlae_installed && status.ffmpeg_installed);
  const gameBusy = Boolean(status?.cs2_running);
  const steamReady = !desktop || Boolean(status?.steam_running);
  const outputDir = settings.outputDir || (demo ? defaultOutput(demo.demo_path) : "");

  async function refreshStatus() {
    if (!desktop) return;
    setStatus(await getStatus());
  }

  async function onDownloadTools() {
    setError(null);
    setBusy("tools");
    setProgress({ stage: "tools", message: "Downloading HLAE and FFmpeg", percent: 0 });
    try {
      if (!desktop) {
        previewCancelled.current = false;
        const finished = await simulate(setProgress, "tools", ["Checking GitHub", "Downloading HLAE", "Downloading FFmpeg", "Tools ready"], () => previewCancelled.current);
        if (!finished) return;
        setStatus((current) => (current ? { ...current, hlae_installed: true, ffmpeg_installed: true } : current));
        return;
      }
      const next = await ensureTools();
      setStatus(next);
      setProgress({ stage: "tools", message: "HLAE and FFmpeg are ready", percent: 100 });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function onSelectDemo() {
    setError(null);
    try {
      if (!desktop) {
        previewCancelled.current = false;
        setBusy("parsing");
        const finished = await simulate(setProgress, "parsing", ["Reading rounds", "Reading kills", "Highlights ready"], () => previewCancelled.current);
        if (!finished) return;
        setDemo(previewDemo);
        setPlayer("all");
        setTypes([]);
        setClips({});
        return;
      }
      const path = await pickDemo();
      if (!path) return;
      setBusy("parsing");
      setProgress({ stage: "parsing", message: "Reading the demo", percent: 5 });
      setDemo(null);
      setClips({});
      const parsed = await parseDemo(path);
      setDemo(parsed);
      setPlayer("all");
      setTypes([]);
      setProgress({ stage: "parsing", message: `${parsed.highlights.length} highlights`, percent: 100 });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }

  async function onChooseOutput() {
    if (!desktop) return;
    const folder = await pickFolder();
    if (folder) setSettings((current) => ({ ...current, outputDir: folder }));
  }

  async function onGenerate(highlight: Highlight) {
    if (!demo) return;
    setError(null);
    setBusy(highlight.id);
    setProgress({ stage: "launch", message: "Preparing the recording", percent: 2 });
    try {
      if (!desktop) {
        previewCancelled.current = false;
        const finished = await simulate(
          setProgress,
          "recording",
          ["Launching CS2 through HLAE", "Seeking to the round", "Recording", "Encoding 16:9 and 9:16"],
          () => previewCancelled.current,
        );
        if (!finished) return;
        const result: ClipResult = {
          output_dir: outputDir || "C:\\clips",
          wide: `C:\\clips\\${highlight.player}_Round${highlight.round}_${highlight.type}_16x9.mp4`,
          vertical: `C:\\clips\\${highlight.player}_Round${highlight.round}_${highlight.type}_9x16.mp4`,
          wide_name: `${highlight.player}_Round${highlight.round}_${highlight.type}_16x9.mp4`,
          vertical_name: `${highlight.player}_Round${highlight.round}_${highlight.type}_9x16.mp4`,
          audio: true,
        };
        setClips((current) => ({ ...current, [highlight.id]: result }));
        setProgress({ stage: "encoding", message: "Preview clip ready", percent: 100 });
        return;
      }
      const result = await generateClip({
        demoPath: demo.demo_path,
        highlight,
        tickrate: demo.tickrate,
        leadIn: settings.leadIn,
        leadOut: settings.leadOut,
        outputDir,
      });
      setClips((current) => ({ ...current, [highlight.id]: result }));
      setProgress({ stage: "encoding", message: "Clips saved. The folder is open.", percent: 100 });
      await refreshStatus();
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setError(message);
    } finally {
      setBusy(null);
    }
  }

  async function onCancel() {
    previewCancelled.current = true;
    if (desktop) {
      try {
        await cancelJob();
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    }
    setBusy(null);
    setProgress({ stage: "recording", message: "Cancelled", percent: null });
  }

  return (
    <div className="flex h-full min-h-screen flex-col">
      <header className="flex items-center justify-between gap-4 border-b border-white/10 px-6 py-4">
        <div className="flex items-baseline gap-3">
          <h1 className="text-xl font-semibold tracking-tight">clippr</h1>
          <p className="text-[11px] uppercase tracking-[0.22em] text-mist">CS2 highlights</p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Pill label="Steam" ok={Boolean(status?.steam_running)} />
          <Pill label="CS2" ok={Boolean(status?.cs2_installed)} />
          <Pill label="HLAE" ok={Boolean(status?.hlae_installed)} />
          <Pill label="FFmpeg" ok={Boolean(status?.ffmpeg_installed)} />
        </div>
      </header>

      {!desktop && (
        <div className="border-b border-amber/30 bg-amber/10 px-6 py-2 text-sm text-amber">
          Preview in the browser. Launch the desktop app with <span className="font-mono">npm run tauri dev</span> to parse a real demo and record.
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="flex flex-col gap-4 border-b border-white/10 p-5 lg:border-b-0 lg:border-r">
          <button
            type="button"
            onClick={() => void onSelectDemo()}
            disabled={busy !== null}
            className="rounded-xl bg-amber px-4 py-3 text-sm font-semibold text-ink disabled:opacity-50"
          >
            Select demo
          </button>

          {demo ? (
            <section className="rounded-2xl border border-white/10 bg-panel p-4">
              <p className="truncate font-medium" title={demo.demo_path}>
                {fileName(demo.demo_path)}
              </p>
              <p className="mt-1 text-sm text-mist">{mapLabel(demo.map_name)}</p>
              <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
                <Stat label="Rounds" value={String(demo.rounds)} />
                <Stat label="Length" value={clock(demo.duration_seconds)} />
                <Stat label="Clips" value={String(demo.highlights.length)} />
              </dl>
            </section>
          ) : (
            <section className="rounded-2xl border border-dashed border-white/15 p-4 text-sm text-mist">
              Choose a <span className="text-white">.dem</span>, <span className="text-white">.dem.gz</span>, or{" "}
              <span className="text-white">.dem.zst</span> file. Kills, multi-kills, and clutches show up here.
            </section>
          )}

          <section className="rounded-2xl border border-white/10 bg-panel p-4">
            <div className="flex items-center justify-between text-sm">
              <span>Lead in</span>
              <span className="font-mono text-mist">{settings.leadIn.toFixed(0)}s</span>
            </div>
            <input
              className="mt-2 w-full accent-amber"
              type="range"
              min={1}
              max={12}
              value={settings.leadIn}
              onChange={(event) => setSettings((current) => ({ ...current, leadIn: Number(event.target.value) }))}
            />
            <div className="mt-3 flex items-center justify-between text-sm">
              <span>Lead out</span>
              <span className="font-mono text-mist">{settings.leadOut.toFixed(0)}s</span>
            </div>
            <input
              className="mt-2 w-full accent-amber"
              type="range"
              min={1}
              max={8}
              value={settings.leadOut}
              onChange={(event) => setSettings((current) => ({ ...current, leadOut: Number(event.target.value) }))}
            />
            <button
              type="button"
              onClick={() => void onChooseOutput()}
              className="mt-4 w-full truncate rounded-lg border border-white/10 px-3 py-2 text-left text-xs text-mist hover:border-white/25"
              title={outputDir || "Next to the demo"}
            >
              Output: {outputDir ? fileName(outputDir) : "next to the demo"}
            </button>
          </section>

          {status && !toolsReady && (
            <section className="rounded-2xl border border-amber/40 bg-amber/10 p-4 text-sm">
              <p>HLAE and FFmpeg are required for recording. They stay in your clippr folder, not in the CS2 install.</p>
              <button
                type="button"
                onClick={() => void onDownloadTools()}
                disabled={busy !== null}
                className="mt-3 rounded-lg bg-white px-3 py-2 text-sm font-semibold text-ink disabled:opacity-50"
              >
                Download tools
              </button>
            </section>
          )}

          {desktop && gameBusy && (
            <p className="text-sm text-rose-300">
              Close Counter-Strike 2 before generating a clip. clippr starts its own session and will not attach to a game that is already open.
            </p>
          )}

          {desktop && status && !status.steam_running && (
            <p className="text-sm text-rose-300">Start Steam, then generate a clip.</p>
          )}

          {status && !status.demoparser && (
            <p className="text-sm text-rose-300">
              demoparser2 is missing. Install it with <span className="font-mono">pip install -r python/requirements.txt</span>.
            </p>
          )}
        </aside>

        <main className="flex min-h-0 flex-col">
          <div className="flex flex-col gap-3 border-b border-white/10 px-5 py-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-medium">
                Highlights
                {demo && types.length > 0 && (
                  <span className="ml-2 font-normal text-mist">
                    {visible.length} of {forPlayer.length}
                  </span>
                )}
              </h2>
              <label className="flex items-center gap-2 text-sm text-mist">
                Player
                <select
                  className="rounded-lg border border-white/10 bg-panel px-2 py-1 text-white"
                  value={player}
                  onChange={(event) => setPlayer(event.target.value)}
                  disabled={!demo}
                >
                  <option value="all">All players</option>
                  {demo?.players.map((item) => (
                    <option key={item.steamid} value={item.steamid}>
                      {item.name} ({item.highlights})
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {demo && availableTypes.length > 0 && (
              <div className="flex flex-wrap gap-1.5" role="group" aria-label="Highlight type">
                <button
                  type="button"
                  aria-pressed={types.length === 0}
                  onClick={() => setTypes([])}
                  className={`rounded-full border px-2.5 py-1 text-xs ${
                    types.length === 0
                      ? "border-amber bg-amber font-semibold text-ink"
                      : "border-white/10 bg-panel text-mist hover:border-white/25 hover:text-white"
                  }`}
                >
                  All
                </button>
                {availableTypes.map((item) => {
                  const on = types.includes(item.id);
                  return (
                    <button
                      key={item.id}
                      type="button"
                      data-type-filter={item.id}
                      aria-pressed={on}
                      onClick={() =>
                        setTypes((current) =>
                          current.includes(item.id) ? current.filter((id) => id !== item.id) : [...current, item.id],
                        )
                      }
                      className={`rounded-full border px-2.5 py-1 text-xs ${
                        on
                          ? "border-amber bg-amber font-semibold text-ink"
                          : "border-white/10 bg-panel text-mist hover:border-white/25 hover:text-white"
                      }`}
                    >
                      {item.label}
                      <span className="ml-1 font-mono">{typeCounts.get(item.id) ?? 0}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <div className="min-h-0 flex-1 overflow-auto px-3 py-2">
            {!demo && (
              <div className="mx-auto mt-16 max-w-md text-center">
                <p className="text-lg font-medium">No demo loaded</p>
                <p className="mt-2 text-sm text-mist">Select a demo, filter by player or type, then generate a clip. Each clip is saved as 16:9 and 9:16.</p>
              </div>
            )}
            {demo && visible.length === 0 && (
              <p className="px-3 py-10 text-center text-sm text-mist">
                {forPlayer.length === 0 ? "No highlights for this player." : "No highlights for the selected types."}
              </p>
            )}
            <ul className="flex flex-col gap-2">
              {visible.map((highlight) => {
                const made = clips[highlight.id];
                const running = busy === highlight.id;
                return (
                  <li key={highlight.id} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 rounded-2xl border border-white/10 bg-panel px-3 py-3">
                    <span className={`rounded-md px-2 py-1 text-center text-xs font-bold tracking-wide ${badgeClass(highlight.type)}`}>
                      {highlight.type}
                    </span>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                        <span className={highlight.side === "CT" ? "text-sky-300" : "text-amber"}>{highlight.player}</span>
                        <span className="text-sm text-white">Round {highlight.round}</span>
                        <span className="text-sm text-mist">{highlight.weapon}</span>
                        <span className="font-mono text-xs text-mist">{clipLength(highlight, demo?.tickrate || 64, settings.leadIn, settings.leadOut)}s</span>
                      </div>
                      <p className="truncate text-xs text-mist">{highlight.detail}</p>
                      {made && (
                        <p className="mt-1 truncate font-mono text-[11px] text-emerald-300" title={made.wide}>
                          {made.wide_name} · {made.vertical_name}
                        </p>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => void onGenerate(highlight)}
                      disabled={busy !== null || (desktop && (!toolsReady || gameBusy || !steamReady))}
                      title={
                        desktop && !toolsReady
                          ? "Download HLAE and FFmpeg first"
                          : desktop && gameBusy
                            ? "Close Counter-Strike 2 first"
                            : desktop && !steamReady
                              ? "Start Steam first"
                              : undefined
                      }
                      className="rounded-lg border border-white/15 px-3 py-2 text-sm hover:border-amber hover:text-amber disabled:opacity-40"
                    >
                      {running ? "Working" : made ? "Generate again" : "Generate clip"}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        </main>
      </div>

      <footer className="border-t border-white/10 px-5 py-3">
        {error && <p className="mb-2 text-sm text-rose-300">{error}</p>}
        {progress && (
          <div className="mb-2">
            <div className="flex items-center justify-between gap-3 text-xs uppercase tracking-wider text-mist">
              <span>{progress.stage}</span>
              <span className="normal-case tracking-normal text-white">{progress.message}</span>
            </div>
            <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full bg-amber transition-all"
                style={{ width: `${progress.percent === null ? 35 : progress.percent}%` }}
              />
            </div>
          </div>
        )}
        <div className="flex items-center justify-between gap-3 text-xs text-mist">
          <p>Recording launches CS2 through HLAE with -insecure. Do not join VAC-secured servers while HLAE is active.</p>
          {busy && busy !== "parsing" && (
            <button type="button" onClick={() => void onCancel()} className="shrink-0 rounded-md border border-white/15 px-2 py-1 text-white">
              Cancel
            </button>
          )}
        </div>
      </footer>
    </div>
  );
}

function defaultOutput(demoPath: string): string {
  const normalized = demoPath.replace(/[/\\][^/\\]+$/, "");
  return `${normalized}\\clippr`;
}

function Pill({ label, ok }: { label: string; ok: boolean }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-panel px-2.5 py-1 text-xs">
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-emerald-400" : "bg-white/25"}`} />
      {label}
    </span>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-panel2 px-2 py-2">
      <div className="font-mono text-sm">{value}</div>
      <div className="text-[10px] uppercase tracking-wider text-mist">{label}</div>
    </div>
  );
}

async function simulate(
  apply: (update: { stage: string; message: string; percent: number | null }) => void,
  stage: string,
  messages: string[],
  cancelled: () => boolean,
): Promise<boolean> {
  for (let index = 0; index < messages.length; index += 1) {
    await new Promise((resolve) => setTimeout(resolve, 280));
    if (cancelled()) return false;
    apply({
      stage,
      message: messages[index],
      percent: Math.round(((index + 1) / messages.length) * 100),
    });
  }
  return true;
}
