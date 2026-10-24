import unittest

from clippr.crosshair import crosshair_commands, decode_crosshair
from clippr.detect import badge_for, clip_window, detect_highlights
from clippr.pace import between_kill_cuts, skipped_seconds
from clippr.models import Death, Kill, Round
from clippr.names import clip_stems, file_token, weapon_label
from clippr.parse_demo import _crosshairs
from clippr.paths import parse_library_paths
from clippr.script import build_script
from clippr.tools import choose_hlae_asset

PUBLISHED_CROSSHAIR = "CSvbPubOq37zTGqtsPTP5QTrp5CB4xFXiKRLfzJsm49ZRe"


def kill(tick, round_number=14, attacker="hero", name="s1mple", side="T", victim=None, weapon="awp", **flags):
    return Kill(
        tick=tick,
        round_number=round_number,
        attacker_steamid=attacker,
        attacker_name=name,
        attacker_side=side,
        victim_steamid=victim or f"v{tick}",
        victim_name="enemy",
        victim_side="CT" if side == "T" else "T",
        weapon=weapon,
        headshot=flags.get("headshot", False),
        noscope=flags.get("noscope", False),
        penetrated=flags.get("penetrated", 0),
        thrusmoke=flags.get("thrusmoke", False),
        attackerblind=flags.get("attackerblind", False),
    )


def rnd(number=14, start=8000, end=12000, winner="T"):
    return Round(number=number, start_tick=start, freeze_end_tick=start + 64, end_tick=end, winner=winner)


class DetectTests(unittest.TestCase):
    def test_four_kills_become_one_clip(self):
        rate = 64
        kills = [kill(9000 + i * 64, victim=f"ct{i}") for i in range(4)]
        found = detect_highlights(kills, [], [rnd()], {14: {}}, {}, rate)
        self.assertEqual([item.type for item in found], ["4K"])
        self.assertEqual(found[0].player, "s1mple")
        self.assertEqual(found[0].weapon, "AWP")
        self.assertEqual(found[0].kills, 4)

    def test_distant_pairs_stay_split(self):
        rate = 64
        kills = [
            kill(9000),
            kill(9000 + 5 * rate),
            kill(9000 + 40 * rate),
            kill(9000 + 45 * rate),
        ]
        found = detect_highlights(kills, [], [rnd(end=20000)], {14: {}}, {}, rate)
        self.assertEqual([item.type for item in found], ["2K", "2K"])

    def test_ace_merges_across_a_short_gap(self):
        rate = 64
        # 16s gaps would split, but the whole burst still fits in the ace window.
        ticks = [9000 + int(seconds * rate) for seconds in (0, 16, 32, 48, 60)]
        kills = [kill(tick, victim=f"ct{index}") for index, tick in enumerate(ticks)]
        found = detect_highlights(kills, [], [rnd(end=20000)], {14: {}}, {}, rate)
        self.assertEqual([item.type for item in found], ["Ace"])

    def test_plain_kill_is_dropped_and_opening_is_kept(self):
        rate = 64
        kills = [kill(9000), kill(9500, attacker="other", name="other", victim="x")]
        found = detect_highlights(kills, [], [rnd()], {14: {}}, {}, rate)
        self.assertEqual([(item.player, item.type) for item in found], [("s1mple", "Opening")])

    def test_noscope_is_kept(self):
        found = detect_highlights([kill(9000, noscope=True)], [], [rnd()], {14: {}}, {}, 64)
        self.assertEqual(found[0].type, "Noscope")
        self.assertIn("opening", found[0].detail)
        self.assertEqual(found[0].crosshair_code, "")

    def test_highlight_keeps_the_crosshair_in_effect_at_the_kill(self):
        early = "CS-EARLY-CODE"
        late = "CS-LATE-CODE"
        found = detect_highlights(
            [kill(9000, noscope=True)],
            [],
            [rnd()],
            {14: {}},
            {},
            64,
            {"hero": [(8000, early), (12000, late)]},
        )
        self.assertEqual(found[0].crosshair_code, early)
        before = detect_highlights(
            [kill(1000, noscope=True)],
            [],
            [rnd()],
            {14: {}},
            {},
            64,
            {"hero": [(8000, early), (12000, late)]},
        )
        self.assertEqual(before[0].crosshair_code, early)

    def test_won_clutch_uses_enemies_at_the_start(self):
        hero = "hero"
        roster = {hero: "T", "a": "CT", "b": "CT", "c": "CT"}
        deaths = [
            Death(2000, 5, "a", hero, "T", "CT"),
            Death(2500, 5, "b", hero, "T", "CT"),
            Death(3000, 5, "c", hero, "T", "CT"),
        ]
        kills = [kill(2000, 5, victim="a"), kill(2500, 5, victim="b"), kill(3000, 5, victim="c")]
        found = detect_highlights(kills, deaths, [rnd(5, 1000, 5000, "T")], {5: roster}, {hero: 4}, 64)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].type, "1v3")
        self.assertEqual(found[0].spec_slot, 4)
        self.assertIn("1v3 clutch", found[0].detail)
        self.assertEqual(found[0].focus_end_tick, 5000)

    def test_lost_clutch_still_keeps_the_multi_kill(self):
        hero = "hero"
        roster = {hero: "T", "ally": "T", "a": "CT", "b": "CT", "c": "CT", "d": "CT"}
        kills = [kill(9000 + i * 64, victim=f"ct{i}") for i in range(4)]
        found = detect_highlights(kills, [], [rnd(winner="CT")], {14: roster}, {}, 64)
        self.assertEqual([item.type for item in found], ["4K"])

    def test_badge_priority(self):
        self.assertEqual(badge_for(5, 1, None), "Ace")
        self.assertEqual(badge_for(3, 3, None), "1v3")
        self.assertEqual(badge_for(4, 1, None), "4K")
        self.assertEqual(badge_for(1, None, None), None)

    def test_highlight_remembers_each_kill_tick(self):
        ticks = [9000, 9640, 10280, 10920]
        found = detect_highlights([kill(tick, victim=f"ct{tick}") for tick in ticks], [], [rnd()], {14: {}}, {}, 64)
        self.assertEqual(found[0].kill_ticks, ticks)
        self.assertEqual(len(between_kill_cuts(found[0].kill_ticks, 64)), 3)

    def test_clip_window_keeps_spec_after_seek(self):
        highlight = {
            "focus_start_tick": 10000,
            "focus_end_tick": 11000,
            "round_start_tick": 8000,
            "round_end_tick": 14000,
        }
        seek, spec, start, end = clip_window(highlight, 64, 5, 3)
        self.assertLess(seek, spec)
        self.assertLess(spec, start)
        self.assertEqual(start, 10000 - 5 * 64)
        self.assertEqual(end, 11000 + 3 * 64)
        self.assertGreaterEqual(seek, 96)


class NameTests(unittest.TestCase):
    def test_clip_names_match_the_readme(self):
        wide, vertical = clip_stems("s1mple", 14, "4K")
        self.assertEqual(wide, "s1mple_Round14_4K_16x9.mp4")
        self.assertEqual(vertical, "s1mple_Round14_4K_9x16.mp4")

    def test_file_token_strips_path_characters(self):
        self.assertEqual(file_token("big man"), "big_man")
        self.assertEqual(file_token('a/b:c'), "a_b_c")

    def test_weapon_labels(self):
        self.assertEqual(weapon_label("weapon_m4a1_silencer"), "M4A1-S")
        self.assertEqual(weapon_label("ak47"), "AK-47")


class ScriptTests(unittest.TestCase):
    def test_script_orders_seek_spec_and_record(self):
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = build_script(
                root / "clippr_record.js",
                seek=9584,
                spec=9648,
                start=9680,
                end=12000,
                fps=60,
                slot=7,
                player='Ni"ko',
                record_dir=root / "take",
                video_path=root / "take" / "video.mp4",
            )
            text = path.read_text(encoding="utf-8")
        self.assertIn("var SEEK = 9584;", text)
        self.assertIn("var SPEC = 9648;", text)
        self.assertIn("var START = 9680;", text)
        self.assertIn("var SLOT = 7;", text)
        self.assertIn('run("cl_draw_only_deathnotices 0")', text)
        self.assertIn('mirv.exec("demo_ui_mode 0")', text)
        boot = text.index('phase === "boot"')
        seek = text.index('run("demo_gototick " + SEEK)')
        approach = text.index('phase === "approach"')
        record = text.index('run("mirv_streams record start")')
        self.assertLess(text.index("hideDemoUi(false)"), boot)
        self.assertLess(text.index("hideDemoUi(true)", boot), seek)
        self.assertLess(text.index("hideDemoUi(true)", approach), record)
        self.assertIn('run("demo_gototick " + SEEK)', text)
        self.assertLess(text.index("demoOrigin + 128"), text.index('run("demo_gototick " + SEEK)'))
        self.assertIn('run("spec_player " + SLOT)', text)
        self.assertIn("mirv_streams record start", text)
        self.assertIn("mirv_streams record end", text)
        self.assertIn("C:/", text.replace("\\", "/"))
        self.assertNotIn("\\", text)
        self.assertNotIn('Ni"ko', text)
        approach = text.index('phase === "approach"')
        armed = text.index('phase === "armed"')
        recording = text.index('phase === "recording"')
        self.assertLess(approach, armed)
        self.assertLess(armed, recording)

    def test_script_jumps_the_gap_between_kills(self):
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = build_script(
                root / "clippr_record.js",
                seek=9584,
                spec=9648,
                start=9680,
                end=14000,
                fps=60,
                slot=7,
                player="Krabeni",
                record_dir=root / "take",
                video_path=root / "take" / "video.mp4",
                cuts=[(10000, 12000)],
            )
            text = path.read_text(encoding="utf-8")
        self.assertIn("var CUTS = [[10000, 12000]];", text)
        self.assertLess(text.index('phase === "recut"'), text.index('phase === "recording"'))
        self.assertLess(text.index('run("demo_gototick " + nextTo)'), text.index("mirv_streams record end"))
        self.assertIn('say("cut " + nextTo)', text)


class PaceTests(unittest.TestCase):
    def test_close_kills_stay_in_one_take(self):
        self.assertEqual(between_kill_cuts([9000, 9128], 64), [])
        self.assertEqual(skipped_seconds([9000, 9128], 64), 0)

    def test_long_gap_keeps_two_seconds_on_each_side(self):
        self.assertEqual(between_kill_cuts([9000, 9640], 64), [(9128, 9512)])
        self.assertAlmostEqual(skipped_seconds([9000, 9640], 64), (9512 - 9128) / 64)

    def test_cuts_outside_the_recording_are_dropped(self):
        self.assertEqual(between_kill_cuts([9000, 9640], 64, start=9128, end=20000), [])
        self.assertEqual(between_kill_cuts([9000, 9640], 64, start=8000, end=9512), [])

    def test_script_applies_the_players_crosshair_before_the_seek(self):
        from pathlib import Path
        import tempfile

        commands = crosshair_commands(PUBLISHED_CROSSHAIR)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = build_script(
                root / "clippr_record.js",
                seek=9584,
                spec=9648,
                start=9680,
                end=12000,
                fps=60,
                slot=7,
                player="Krabeni",
                record_dir=root / "take",
                video_path=root / "take" / "video.mp4",
                crosshair=commands,
            )
            text = path.read_text(encoding="utf-8")
        loop = text.index("for (var i = 0; i < CROSSHAIR.length; i++) run(CROSSHAIR[i]);")
        seek = text.index('run("demo_gototick " + SEEK)')
        self.assertLess(text.index("hideDemoUi(true)"), text.index('run("mirv_cvar_unhide_all")'))
        self.assertLess(text.index('run("cl_draw_only_deathnotices 0")'), text.index('run("mirv_cvar_unhide_all")'))
        self.assertLess(text.index('run("mirv_cvar_unhide_all")'), loop)
        self.assertLess(loop, seek)
        self.assertIn(PUBLISHED_CROSSHAIR, text)
        self.assertIn("cl_crosshairstyle 2", text)
        self.assertIn("cl_crosshaircolor_r 255", text)
        self.assertIn("cl_crosshairdot 1", text)
        self.assertIn("cl_crosshair_length 5", text)


class CrosshairTests(unittest.TestCase):
    def test_published_code_matches_the_cs2_layout(self):
        settings = dict(decode_crosshair(PUBLISHED_CROSSHAIR) or [])
        self.assertEqual(
            settings,
            {
                "cl_crosshairstyle": "2",
                "cl_crosshair_recoil": "0",
                "cl_crosshairdot": "1",
                "cl_crosshair_t": "0",
                "cl_crosshaircolor_r": "255",
                "cl_crosshaircolor_g": "0",
                "cl_crosshaircolor_b": "0",
                "cl_crosshaircolor_a": "255",
                "cl_crosshairoutline_r": "0",
                "cl_crosshairoutline_g": "0",
                "cl_crosshairoutline_b": "0",
                "cl_crosshairoutline_a": "255",
                "cl_crosshair_thickness": "1",
                "cl_crosshair_drawoutline": "0",
                "cl_crosshair_gap": "0",
                "cl_crosshair_length": "5",
                "cl_crosshair_dynamic_spread_limit": "181",
                "cl_crosshair_dynamic_splitdist": "3",
                "cl_crosshair_dynamic_splitalpha_innermod": "1",
                "cl_crosshair_dynamic_splitalpha_outermod": "0.35",
                "cl_crosshair_dynamic_maxdist_splitratio": "0",
                "cl_crosshair_screen_height": "768",
                "cl_ironsight_dot_scale": "1",
                "cl_ironsight_usecrosshaircolor": "0",
            },
        )
        commands = crosshair_commands(PUBLISHED_CROSSHAIR)
        self.assertEqual(commands[0], f'apply_crosshair_code "{PUBLISHED_CROSSHAIR}"')
        self.assertIn("cl_crosshairstyle 2", commands)

    def test_old_and_garbage_codes_are_ignored(self):
        self.assertEqual(crosshair_commands(""), [])
        self.assertEqual(crosshair_commands("CSGO-KfvhQ-uhqm9-5jzfs-NDbWr-MUYjM"), [])
        self.assertIsNone(decode_crosshair("CS" + "A" * 44))
        self.assertEqual(crosshair_commands("CS" + "A" * 44), [])

    def test_samples_are_grouped_by_player(self):
        import pandas as pd

        frame = pd.DataFrame(
            [
                {"tick": 500, "steamid": "hero", "crosshair_code": "LATE"},
                {"tick": 100, "steamid": "hero", "crosshair_code": "EARLY"},
                {"tick": 100, "steamid": "hero", "crosshair_code": "EARLY"},
                {"tick": 100, "steamid": "other", "crosshair_code": ""},
                {"tick": 100, "steamid": "ghost", "crosshair_code": float("nan")},
            ]
        )

        class Parser:
            def parse_ticks(self, props, ticks=None):
                self.props = props
                self.ticks = list(ticks or [])
                return frame

        parser = Parser()
        found = _crosshairs(parser, [rnd(start=100, end=500)])
        self.assertEqual(parser.props, ["crosshair_code"])
        self.assertIn(164, parser.ticks)
        self.assertIn(500, parser.ticks)
        self.assertEqual(found["hero"], [(100, "EARLY"), (500, "LATE")])
        self.assertNotIn("other", found)
        self.assertNotIn("ghost", found)

    def test_parser_failure_leaves_crosshairs_empty(self):
        class Parser:
            def parse_ticks(self, props, ticks=None):
                raise RuntimeError("no crosshair column")

        self.assertEqual(_crosshairs(Parser(), [rnd()]), {})


class ToolTests(unittest.TestCase):
    def test_hlae_asset_skips_source_and_prereleases(self):
        releases = [
            {"prerelease": True, "assets": [{"name": "hlae.zip", "browser_download_url": "https://example.com/pre"}]},
            {
                "tag_name": "v2.1",
                "assets": [
                    {"name": "advancedfx-source.zip", "browser_download_url": "https://example.com/src"},
                    {"name": "hlae.zip", "browser_download_url": "https://example.com/hlae.zip"},
                ],
            },
        ]
        url, info = choose_hlae_asset(releases)
        self.assertEqual(url, "https://example.com/hlae.zip")
        self.assertEqual(info["tag"], "v2.1")

    def test_hlae_asset_prefers_highest_version_over_newer_publish(self):
        releases = [
            {
                "tag_name": "v2.185.4",
                "published_at": "2026-10-23T10:54:04Z",
                "body": "This is an OLD re-release. Compatible with CS2 1.40.8.8",
                "assets": [{"name": "hlae_2_185_4.zip", "browser_download_url": "https://example.com/old.zip"}],
            },
            {
                "tag_name": "v2.192.8",
                "published_at": "2026-10-14T15:40:08Z",
                "assets": [
                    {"name": "hlae_2_192_8.zip.asc", "browser_download_url": "https://example.com/sig"},
                    {"name": "notes.zip", "browser_download_url": "https://example.com/notes.zip"},
                    {"name": "hlae_2_192_8.zip", "browser_download_url": "https://example.com/hlae_2_192_8.zip"},
                ],
            },
            {
                "tag_name": "v2.192.7",
                "assets": [{"name": "hlae_2_192_7.zip", "browser_download_url": "https://example.com/older.zip"}],
            },
        ]
        url, info = choose_hlae_asset(releases)
        self.assertEqual(url, "https://example.com/hlae_2_192_8.zip")
        self.assertEqual(info["tag"], "v2.192.8")

    def test_hlae_asset_sorts_versions_when_the_old_build_is_not_labeled(self):
        releases = [
            {
                "tag_name": "v2.185.4",
                "assets": [{"name": "hlae_2_185_4.zip", "browser_download_url": "https://example.com/old.zip"}],
            },
            {
                "tag_name": "v2.192.8",
                "assets": [{"name": "hlae_2_192_8.zip", "browser_download_url": "https://example.com/current.zip"}],
            },
        ]
        url, info = choose_hlae_asset(releases)
        self.assertEqual(url, "https://example.com/current.zip")
        self.assertEqual(info["tag"], "v2.192.8")

    def test_library_vdf_paths(self):
        text = r'''
        "libraryfolders"
        {
            "0" { "path" "C:\\Program Files (x86)\\Steam" }
            "1" { "path" "D:\\SteamLibrary" }
        }
        '''
        self.assertEqual(
            parse_library_paths(text),
            [r"C:\Program Files (x86)\Steam", r"D:\SteamLibrary"],
        )


if __name__ == "__main__":
    unittest.main()
