export type ToolStatus = {
  steam_running: boolean;
  cs2_running: boolean;
  cs2_installed: boolean;
  cs2_path: string | null;
  hlae_installed: boolean;
  hlae_path: string | null;
  ffmpeg_installed: boolean;
  ffmpeg_path: string | null;
  demoparser: boolean;
  python: string;
  sandbox: string;
  tools_dir: string;
};

export type Highlight = {
  id: string;
  player: string;
  steamid: string;
  side: string;
  round: number;
  type: string;
  detail: string;
  weapon: string;
  kills: number;
  headshots: number;
  focus_start_tick: number;
  focus_end_tick: number;
  round_start_tick: number;
  round_end_tick: number;
  spec_slot: number | null;
  score: number;
  crosshair_code?: string;
  kill_ticks?: number[];
};

export type PlayerFilter = {
  name: string;
  steamid: string;
  side: string;
  highlights: number;
};

export type ParsedDemo = {
  demo_path: string;
  map_name: string;
  tickrate: number;
  duration_seconds: number;
  rounds: number;
  highlights: Highlight[];
  players: PlayerFilter[];
};

export type ClipResult = {
  output_dir: string;
  wide: string;
  vertical: string;
  wide_name: string;
  vertical_name: string;
  audio: boolean;
};

export type ProgressEvent = {
  type?: string;
  stage?: string;
  message?: string;
  percent?: number;
};
