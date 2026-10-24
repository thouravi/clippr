"""Build the HLAE mirv script that seeks, aims the camera, and records."""

from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = r"""
(function () {
  if (globalThis.__clipprRecording) return;
  globalThis.__clipprRecording = true;

  var SEEK = __SEEK__;
  var SPEC = __SPEC__;
  var START = __START__;
  var END = __END__;
  var FPS = __FPS__;
  var SLOT = __SLOT__;
  var PLAYER = __PLAYER__;
  var CROSSHAIR = __CROSSHAIR__;
  var PRESET = __PRESET__;
  var RECORD_NAME = __RECORD_NAME__;
  var CUTS = __CUTS__;

  var phase = "boot";
  var flushAt = 0;
  var demoOrigin = null;
  var cutIndex = 0;
  var recutTo = 0;
  var recutFrames = 0;
  var recutLanded = 0;

  function say(msg) {
    try { mirv.message("clippr: " + msg); } catch (err) {}
  }

  function run(cmd) {
    mirv.exec(cmd);
    say(cmd);
  }

  // demo_ui_mode is 2 (full) by default. A seek opens HudDemoPlayback again,
  // so a single set before demo_gototick does not keep the panel closed.
  // Pulsing 2 then 0 makes an already-open panel notice the change.
  function hideDemoUi(pulse) {
    if (pulse) mirv.exec("demo_ui_mode 2");
    mirv.exec("demo_ui_mode 0");
  }

  function aim() {
    run("spec_mode 1");
    if (SLOT > 0) run("spec_player " + SLOT);
    else if (PLAYER) run('spec_player "' + PLAYER + '"');
  }

  function step() {
    if (typeof mirv.isPlayingDemo === "function" && !mirv.isPlayingDemo()) return;
    var tick = mirv.getDemoTick();
    if (tick === undefined || tick === null || tick < 0) return;
    hideDemoUi(false);

    if (phase === "recut") {
      recutFrames++;
      if (tick >= recutTo) recutLanded++;
      // spec_player on the landing tick of demo_gototick is ignored, so aim
      // a few frames after the jump actually arrives.
      if (recutLanded > 8 || recutFrames > 240) {
        aim();
        hideDemoUi(true);
        phase = "recording";
      }
      return;
    }

    if (phase === "flush") {
      if (Date.now() >= flushAt) {
        phase = "done";
        run("quit");
      }
      return;
    }

    if (phase === "boot") {
      // Seeking while playback is still at tick 0 applies entity updates before
      // the server class table exists: CopyNewEntity invalid class index, out of range 0.
      if (demoOrigin === null) {
        demoOrigin = tick;
        return;
      }
      if (tick < demoOrigin + 128) return;
      run("sv_cheats 1");
      hideDemoUi(true);
      run("cl_draw_only_deathnotices 0");
      if (CROSSHAIR.length) {
        run("mirv_cvar_unhide_all");
        for (var i = 0; i < CROSSHAIR.length; i++) run(CROSSHAIR[i]);
      }
      run("volume 1");
      run("cl_demo_predict 0");
      run("spec_show_xray 0");
      run("r_show_build_info 0");
      run("cl_hud_telemetry_frametime_show 0");
      run("cl_hud_telemetry_ping_show 0");
      run("cl_hud_telemetry_net_misdelivery_show 0");
      run("cl_hud_telemetry_serverrecvmargin_graph_show 0");
      run("cl_trueview_show_status 0");
      run("mirv_streams record screen enabled 1");
      run("mirv_streams record startMovieWav 1");
      run('mirv_streams record name "' + RECORD_NAME + '"');
      run('mirv_streams settings add ffmpeg clippr "' + PRESET + '"');
      run("mirv_streams record screen settings clippr");
      run("mirv_streams record fps " + FPS);
      run("demo_gototick " + SEEK);
      phase = "approach";
      say("seek " + SEEK);
      return;
    }

    // spec_player on the same tick as demo_gototick is ignored, so aim on a
    // later callback than the seek and start recording on a later one still.
    if (phase === "approach" && tick >= SPEC) {
      hideDemoUi(true);
      aim();
      phase = "armed";
      return;
    }

    if (phase === "armed" && tick >= START) {
      run("host_framerate " + FPS);
      run("mirv_streams record start");
      phase = "recording";
      say("recording");
      return;
    }

    if (phase === "recording") {
      if (cutIndex < CUTS.length && tick >= CUTS[cutIndex][0] && tick < CUTS[cutIndex][1]) {
        var nextTo = CUTS[cutIndex][1];
        cutIndex++;
        recutTo = nextTo;
        recutFrames = 0;
        recutLanded = 0;
        run("demo_gototick " + nextTo);
        hideDemoUi(true);
        phase = "recut";
        say("cut " + nextTo);
        return;
      }
      while (cutIndex < CUTS.length && tick >= CUTS[cutIndex][1]) cutIndex++;
      if (tick >= END) {
        run("mirv_streams record end");
        run("host_framerate 0");
        phase = "flush";
        flushAt = Date.now() + 1200;
        say("flush");
      }
    }
  }

  var handler = function (event) {
    try { mirv.exec("demo_ui_mode 0"); } catch (err) {}
    if (event && event.isBefore) return;
    try { step(); } catch (err) { try { mirv.warning("clippr " + err); } catch (e2) {} }
  };

  if (mirv.events && mirv.events.clientFrameStageNotify && mirv.events.clientFrameStageNotify.on) {
    mirv.events.clientFrameStageNotify.on("clippr-record", handler);
  } else {
    mirv.onClientFrameStageNotify = handler;
  }
  say("armed");
})();
"""


def build_script(
    destination: Path,
    *,
    seek: int,
    spec: int,
    start: int,
    end: int,
    fps: int,
    slot: int | None,
    player: str,
    record_dir: Path,
    video_path: Path,
    crf: int = 18,
    crosshair: list[str] | None = None,
    cuts: list[tuple[int, int]] | None = None,
) -> Path:
    record_name = str(record_dir).replace("\\", "/")
    video = str(video_path).replace("\\", "/")
    preset = (
        f"-c:v libx264 -pix_fmt yuv420p -crf {int(crf)} -preset veryfast "
        f"{{QUOTE}}{video}{{QUOTE}}"
    )
    safe_player = "".join(ch for ch in player if ch not in '"\r\n\\')
    script = (
        TEMPLATE.replace("__SEEK__", str(int(seek)))
        .replace("__SPEC__", str(int(spec)))
        .replace("__START__", str(int(start)))
        .replace("__END__", str(int(end)))
        .replace("__FPS__", str(int(fps)))
        .replace("__SLOT__", str(int(slot or 0)))
        .replace("__PLAYER__", json.dumps(safe_player))
        .replace("__CROSSHAIR__", json.dumps(list(crosshair or [])))
        .replace("__CUTS__", json.dumps([[int(leave), int(arrive)] for leave, arrive in (cuts or [])]))
        .replace("__PRESET__", json.dumps(preset))
        .replace("__RECORD_NAME__", json.dumps(record_name))
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(script, encoding="utf-8")
    return destination
