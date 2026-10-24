# clippr

**clippr** is a desktop application that turns Counter-Strike 2 demo files into clean, ready-to-share highlight clips. Select a `.dem` file, review detected moments, and generate both 16:9 and 9:16 videos with a single click.

The app handles the full pipeline automatically: demo parsing, highlight detection, CS2 + HLAE recording, and FFmpeg post-processing.

## Features

- Select any CS2 `.dem` file (supports compressed `.dem.gz` and `.dem.zst`)
- Automatic parsing of kills, multi-kills, clutches, and other notable moments
- Clean list of highlights with player, round, weapon, and type
- One-click **Generate Clip** for any moment
- Fully automated recording via CS2 launched through HLAE (`-insecure`, sandboxed config)
- Dual output:
  - **16:9** (widescreen, YouTube-ready)
  - **9:16** (vertical, TikTok / Reels / Shorts-ready with smart framing)
- Progress feedback during parsing, launch, recording, and encoding
- Dark-mode UI with file picker, highlight browser, and status indicators

## Requirements

- Windows 10/11
- Counter-Strike 2 installed via Steam
- Steam running
- Python 3.11+
- Rust stable with the MSVC toolchain
- Visual Studio 2022 Build Tools with the Desktop development with C++ workload
- HLAE (AfxHookSource2) — downloaded automatically or manually
- FFmpeg — downloaded automatically or manually

> Always run recording sessions with HLAE in `-insecure` mode. Do not join VAC-secured servers while HLAE is active.

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/thouravi/clippr.git
   cd clippr
   ```

2. Install dependencies:
   ```bash
   npm install
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r python\requirements.txt
   ```

3. Run the application in development:
   ```bash
   npm run tauri dev
   ```

A Windows build is published on the [`latest` release](https://github.com/thouravi/clippr/releases/latest) whenever source code changes. `clippr.exe` still runs the Python pipeline from this checkout: keep the `.venv` from step 2, and put the exe inside the checkout (for example `src-tauri\target\release\clippr.exe`). An exe launched from Downloads cannot find that venv.

On first launch, the app will check for (and optionally download) HLAE and FFmpeg.

## Usage

1. Launch **clippr**.
2. Click **Select Demo** and choose a `.dem` file.
3. Wait for parsing to complete. Highlights appear in the list.
4. Filter by player if desired.
5. Click **Generate Clip** on any highlight.
6. The app will:
   - Launch CS2 through HLAE
   - Seek to the correct tick and POV
   - Record the segment
   - Encode both 16:9 and 9:16 versions
7. When finished, the output folder opens automatically.

Clips are saved with descriptive names, for example:
- `s1mple_Round14_4K_16x9.mp4`
- `s1mple_Round14_4K_9x16.mp4`

## Tech Stack

- **Frontend**: Tauri (Rust) + React + TypeScript + Tailwind CSS
- **Demo Parsing**: demoparser2
- **Recording**: HLAE (AfxHookSource2) + CS2 `mirv_streams`
- **Video Processing**: FFmpeg
- **Backend Orchestration**: Python or Rust

## Project Structure

```
clippr/
├── src/                 # Frontend (React)
├── src-tauri/           # Tauri / Rust backend
├── python/              # Optional Python parsing & recording scripts
├── assets/
└── README.md
```

## Development Notes

- Recording uses a sandboxed CS2 configuration (`USRLOCALCSGO`) so the user’s normal settings remain untouched.
- Frames are piped from HLAE directly into FFmpeg (no intermediate TGA files).
- Lead-in and lead-out times are configurable.
- After major CS2 updates, HLAE may need an update before recording works again.

## License

MIT License (or your preferred license).

## Acknowledgments

Recording approach inspired by open-source tools such as [cs2-highlights-maker](https://github.com/Rovniy/cs2-highlights-maker) and [CS DemoDesk](https://github.com/noih/cs-demodesk). Demo parsing powered by [demoparser2](https://github.com/LaihoE/demoparser). Recording powered by [HLAE](https://github.com/advancedfx/advancedfx).
