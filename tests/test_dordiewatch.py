import base64
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QSize, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QPushButton

from dordiewatch import (
    DordieWatchWindow,
    HoverIconButton,
    LibraryCollection,
    LibraryScanTask,
    Movie,
    MpvController,
    MpvVideoSurface,
    SeekSlider,
    MPV_RUNTIME,
    build_collections,
    cache_key,
    collection_database_id,
    collection_folder_for_video,
    database_cover_for_movie,
    discover_videos,
    find_binary,
    format_duration,
    generate_previews,
    link_collection_to_database_id,
    load_website_library,
    match_website_collection,
    path_is_within,
    probe_video,
    update_movies_from_website,
    website_launch_manifest,
    mpv,
)


class DordieWatchCoreTest(unittest.TestCase):
    def test_website_protocol_and_database_id_matching(self) -> None:
        manifest = (
            "http://dordielist.test/api/dordiewatch/media/42"
            "?expires=123&signature=abc"
        )
        encoded = base64.urlsafe_b64encode(manifest.encode()).decode().rstrip("=")
        launch_url = "dordiewatch://open?manifest=" + encoded
        self.assertEqual(website_launch_manifest([launch_url]), manifest)
        payload = {
            "id": 42,
            "display_title": "Kizumonogatari Part 1: Tekketsu",
            "title": {
                "english": "Kizumonogatari Part 1: Tekketsu",
                "romaji": "Kizumonogatari I: Tekketsu-hen",
            },
        }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "A deliberately unrelated local folder name"
            folder.mkdir()
            movie = Movie(
                path=str(folder / "movie.mkv"),
                title="movie",
                root=str(root),
                size=0,
                modified=0,
            )
            collection = LibraryCollection(
                folder=str(folder),
                title=folder.name,
                movies=[movie],
            )

            self.assertIsNone(match_website_collection(payload, [collection]))
            marker = link_collection_to_database_id(folder, 42)
            self.assertTrue(marker.is_file())
            self.assertEqual(collection_database_id(folder), 42)

            movie.media_id = collection_database_id(folder)
            self.assertIs(match_website_collection(payload, [collection]), collection)

            numeric_folder = root / "12345"
            numeric_folder.mkdir()
            self.assertEqual(collection_database_id(numeric_folder), 12345)

            payload["title"] = {"english": "A completely renamed title"}
            self.assertIs(match_website_collection(payload, [collection]), collection)

            second_folder = root / "Another folder for the same database entry"
            second_folder.mkdir()
            second_movie = Movie(
                path=str(second_folder / "episode-2.mkv"),
                title="episode-2",
                root=str(root),
                size=0,
                modified=0,
                collection=str(second_folder),
                media_id=42,
            )
            movie.collection = str(folder)
            grouped = build_collections([movie, second_movie], [str(root)])
            self.assertEqual(len(grouped), 1)
            self.assertEqual(len(grouped[0].movies), 2)

    def test_library_scan_does_not_decode_videos(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            series = root / "Series"
            series.mkdir()
            video = series / "01.mkv"
            video.write_bytes(b"not-a-real-video")
            cover = series / "thumbnail.jpg"
            cover.write_bytes(b"cover")
            link_collection_to_database_id(series, 9876)

            class Store:
                preview_dir = root / "cache"
                website_cover_dir = root / "website-covers"

            payloads = []
            task = LibraryScanTask(root, Store())
            task.signals.movie.connect(payloads.append)
            task.run()
            self.assertEqual(len(payloads), 1)
            movie = Movie.from_dict(payloads[0])
            self.assertEqual(movie.duration_ms, 0)
            self.assertEqual(movie.preview_frames, ())
            self.assertNotEqual(Path(movie.thumbnail), cover)
            self.assertTrue(Path(movie.thumbnail).is_file())
            self.assertEqual(movie.cover, "")
            self.assertEqual(Path(movie.collection), series)
            self.assertEqual(movie.media_id, 9876)

    def test_replaced_videos_keep_database_metadata_during_refresh(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            series = root / "17970"
            series.mkdir()
            replacement = series / "new-episode.mkv"
            replacement.write_bytes(b"replacement")

            class Store:
                preview_dir = root / "cache"
                website_cover_dir = root / "website-covers"

            Store.website_cover_dir.mkdir()
            database_cover = Store.website_cover_dir / "17970-cover.img"
            database_cover.write_bytes(b"database-cover")
            previous = Movie(
                path=str(series / "old-episode.mkv"),
                title="Old Episode",
                root=str(root),
                size=100,
                modified=1,
                collection=str(series),
                cover=str(database_cover),
                media_id=17970,
                media_type="anime",
                collection_title="Sentenced to Be a Hero",
                website_url="https://dordielist.test/media/17970",
                cover_source_url="https://example.test/17970.jpg",
            )

            payloads = []
            task = LibraryScanTask(root, Store(), [previous])
            task.signals.movie.connect(payloads.append)
            task.run()

            self.assertEqual(len(payloads), 1)
            movie = Movie.from_dict(payloads[0])
            self.assertEqual(Path(movie.path), replacement)
            self.assertEqual(movie.media_id, 17970)
            self.assertEqual(movie.collection_title, "Sentenced to Be a Hero")
            self.assertEqual(movie.media_type, "anime")
            self.assertEqual(Path(movie.cover), database_cover)
            self.assertEqual(Path(movie.thumbnail), database_cover)

    def test_player_icon_activates_once_on_click(self) -> None:
        app = QApplication.instance() or QApplication([])
        button = HoverIconButton()
        button.show()
        app.processEvents()
        clicked = QSignalSpy(button.clicked)
        QTest.mousePress(button, Qt.LeftButton, pos=QPoint(32, 28))
        app.processEvents()
        self.assertEqual(clicked.count(), 0)
        QTest.mouseRelease(button, Qt.LeftButton, pos=QPoint(32, 28))
        app.processEvents()
        self.assertEqual(clicked.count(), 1)
        button.close()

    def test_video_surface_click_does_not_toggle_playback(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temporary:
            previous = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = temporary
            try:
                class SignalStub:
                    def connect(self, _callback):
                        pass

                class FakeController:
                    position_changed = SignalStub()
                    playing_changed = SignalStub()
                    ended = SignalStub()
                    error = SignalStub()

                    def __init__(self, _surface):
                        self.available = True

                    def is_playing(self):
                        return False

                with patch("dordiewatch.MpvController", FakeController):
                    window = DordieWatchWindow()
                window.player.movie = Movie(
                    path=str(Path(temporary) / "episode-01.mkv"),
                    title="Episode 1",
                    root=temporary,
                    size=0,
                    modified=0,
                )
                toggles = []
                window.player._toggle_playback = lambda: toggles.append(True)
                window.player.overlay.show()
                window.player.video_surface.show()
                app.processEvents()

                QTest.mouseClick(
                    window.player.video_surface,
                    Qt.LeftButton,
                    pos=QPoint(20, 20),
                )
                QTest.qWait(240)

                self.assertEqual(toggles, [])
                window.player.movie = None
                window.close()
            finally:
                if previous is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous

    def test_play_movie_uses_embedded_subtitles_without_extraction(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temporary:
            previous = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = temporary
            try:
                window = DordieWatchWindow()
                video = Path(temporary) / "episode-01.mkv"
                video.touch()
                captured = {}

                def open_mock(path, start_ms=0, volume=80):
                    captured.update({"path": path, "start_ms": start_ms, "volume": volume})
                    return True

                window.player.controller.open = open_mock
                window.play_movie(
                    Movie(
                        path=str(video),
                        title="Episode 1",
                        root=temporary,
                        size=0,
                        modified=0,
                    )
                )

                self.assertEqual(captured["path"], str(video))
                self.assertEqual(window.player.selected_subtitle, -1)
                self.assertFalse(window.player.subtitle_preference_applied)
                window.player.movie = None
                window.close()
            finally:
                if previous is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous

    def test_embedded_subtitle_selection_and_preference(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temporary:
            previous = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = temporary
            try:
                window = DordieWatchWindow()
                series = Path(temporary) / "Series"
                series.mkdir()
                video = series / "episode-01.mkv"
                video.touch()
                movie = Movie(
                    path=str(video),
                    title="Episode 1",
                    root=temporary,
                    size=0,
                    modified=0,
                    collection=str(series),
                )
                window.player.movie = movie
                selected = []
                window.player.controller.select_subtitle = selected.append
                window.player._choose_subtitle_track(3, "English")

                self.assertEqual(selected, [3])
                self.assertEqual(window.player.selected_subtitle, 3)
                self.assertEqual(
                    window.settings["series_subtitles"][str(series.resolve())],
                    {"off": False, "label": "English", "track_id": 3},
                )

                selected.clear()
                window.player.subtitle_preference_applied = False
                window.player.controller.subtitle_tracks = lambda: [
                    (2, "French"),
                    (3, "English"),
                ]
                window.player._apply_saved_subtitle_preference()

                self.assertEqual(selected, [3])
                window.player.movie = None
                window.close()
            finally:
                if previous is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous

    def test_video_surface_fills_player_and_mpv_preserves_aspect(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temporary:
            previous = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = temporary
            try:
                window = DordieWatchWindow()
                window.player.resize(800, 800)
                window.player.movie = Movie(
                    path=str(Path(temporary) / "wide.mkv"),
                    title="Wide",
                    root=temporary,
                    size=0,
                    modified=0,
                    width=1920,
                    height=1080,
                )
                window.player._sync_video_surface_geometry()

                geometry = window.player.video_surface.geometry()
                self.assertEqual(geometry.width(), 800)
                self.assertEqual(geometry.height(), 800)
                self.assertEqual(geometry.y(), 0)
                window.player.movie = None
                window.close()
            finally:
                if previous is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous

    def test_video_resize_does_not_reconfigure_mpv(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temporary:
            previous = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = temporary
            try:
                window = DordieWatchWindow()
                calls = []
                window.player.controller.fit_video = lambda: calls.append("fit")
                window.player.resize(900, 700)
                window.player._sync_video_surface_geometry()

                self.assertEqual(calls, [])
                window.close()
            finally:
                if previous is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous

    def test_video_resize_settle_reapplies_final_contain_fit(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temporary:
            previous = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = temporary
            try:
                window = DordieWatchWindow()
                calls = []
                window.player.controller.fit_video = lambda: calls.append("fit")
                window.player.resize(900, 700)
                window.player._settle_video_layout()

                self.assertEqual(window.player.video_surface.geometry(), window.player.rect())
                self.assertEqual(calls, ["fit"])
                window.close()
            finally:
                if previous is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous

    def test_video_surface_resizes_immediately_during_drag(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temporary:
            previous = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = temporary
            try:
                window = DordieWatchWindow()
                window.player.resize(800, 600)
                window.player.movie = Movie(
                    path=str(Path(temporary) / "episode.mkv"),
                    title="Episode",
                    root=temporary,
                    size=0,
                    modified=0,
                )
                window.player._sync_video_surface_geometry()
                self.assertEqual(window.player.video_surface.size(), QSize(800, 600))

                window.player.begin_interactive_resize()
                window.player.resize(830, 620)
                window.player._sync_video_surface_geometry()
                updated = window.player.video_surface.geometry()
                self.assertEqual(updated.size(), QSize(830, 620))
                self.assertEqual(updated.x(), 0)
                self.assertEqual(updated.y(), 0)

                window.player.resize(900, 700)
                window.player._sync_video_surface_geometry()
                updated = window.player.video_surface.geometry()
                self.assertEqual(updated.size(), QSize(900, 700))
                self.assertEqual(updated.x(), 0)
                self.assertEqual(updated.y(), 0)

                window.player.resize(930, 720)
                window.player.end_interactive_resize()
                self.assertEqual(window.player.video_surface.size(), QSize(930, 720))
                self.assertIsInstance(window.player.video_surface, MpvVideoSurface)
                self.assertFalse(
                    window.player.video_surface.testAttribute(Qt.WA_NativeWindow)
                )
                window.player.movie = None
                window.close()
            finally:
                if previous is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous

    def test_timeline_drag_does_not_seek_until_release(self) -> None:
        app = QApplication.instance() or QApplication([])
        slider = SeekSlider(Qt.Horizontal)
        slider.setRange(0, 1_000)
        slider.resize(200, 26)
        slider.show()
        app.processEvents()
        seek_spy = QSignalSpy(slider.seek_requested)
        release_spy = QSignalSpy(slider.sliderReleased)

        QTest.mousePress(slider, Qt.LeftButton, pos=QPoint(50, 10))
        self.assertEqual(seek_spy.count(), 1)
        QTest.mouseMove(slider, QPoint(120, 10))
        app.processEvents()
        self.assertEqual(seek_spy.count(), 1)
        QTest.mouseRelease(slider, Qt.LeftButton, pos=QPoint(120, 10))
        app.processEvents()
        self.assertEqual(seek_spy.count(), 2)
        self.assertEqual(release_spy.count(), 1)

        slider.close()

    def test_mpv_set_time_uses_absolute_seek_command(self) -> None:
        calls = []

        class FakePlayer:
            def command(self, *args):
                calls.append(args)

        controller = MpvController.__new__(MpvController)
        controller.player = FakePlayer()

        controller.set_time(12_345)

        self.assertEqual(calls, [("seek", 12.345, "absolute", "exact")])

    def test_mpv_fit_video_forces_letterboxed_aspect_mode(self) -> None:
        calls = []

        class FakePlayer:
            def command(self, *args):
                calls.append(args)

        controller = MpvController.__new__(MpvController)
        controller.player = FakePlayer()

        controller.fit_video()

        self.assertIn(("set", "keepaspect", "yes"), calls)
        self.assertIn(("set", "keepaspect-window", "no"), calls)
        self.assertIn(("set", "panscan", "0"), calls)
        self.assertIn(("set", "video-zoom", "0"), calls)
        self.assertIn(("set", "video-aspect-override", "no"), calls)
        self.assertIn(("set", "video-crop", "none"), calls)

    def test_mpv_render_params_are_wrapper_dicts(self) -> None:
        def noop_proc_address(_ctx, _name):
            return 0

        init_param = mpv.MpvRenderParam(
            "opengl_init_params",
            {"get_proc_address": mpv.MpvGlGetProcAddressFn(noop_proc_address)},
        )
        fbo_param = mpv.MpvRenderParam(
            "opengl_fbo",
            {"w": 800, "h": 450, "fbo": 1, "internal_format": 0},
        )

        self.assertEqual(init_param.type_id, 2)
        self.assertEqual(fbo_param.type_id, 3)

    def test_close_waits_for_active_playback_to_pause_before_stop(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temporary:
            previous = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = temporary
            try:
                window = DordieWatchWindow()
                window.player.movie = Movie(
                    path=str(Path(temporary) / "episode-01.mkv"),
                    title="Episode 1",
                    root=temporary,
                    size=0,
                    modified=0,
                    duration_ms=60_000,
                )
                calls = []
                window.player.controller.time = lambda: 10_000
                window.player.controller.length = lambda: 60_000
                window.player.controller.quiet_for_close = lambda: calls.append(
                    "quiet"
                )
                window.player.controller.stop = lambda: calls.append("stop")
                playing_state = {"playing": True}
                window.player.controller.is_playing = lambda: playing_state[
                    "playing"
                ]
                window.player.controller.stopped_or_idle = lambda: True

                window.player.close_player()
                window.player._stop_playback_for_close()
                self.assertNotIn("stop", calls)
                playing_state["playing"] = False
                window.player._stop_playback_for_close()
                self.assertIn("stop", calls)
                window.player.movie = None
                window.close()
            finally:
                if previous is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous

    def test_helpers_and_discovery(self) -> None:
        self.assertEqual(format_duration(65_000), "1:05")
        self.assertEqual(format_duration(3_723_000), "1:02:03")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / "Series"
            nested.mkdir()
            (root / "movie.MP4").touch()
            (nested / "episode.mkv").touch()
            (nested / "episode2.mkv").touch()
            (nested / "thumbnail.jpg").touch()
            (root / "notes.txt").touch()
            found = discover_videos(root)
            self.assertEqual(
                {path.name for path in found},
                {"movie.MP4", "episode.mkv", "episode2.mkv"},
            )
            self.assertTrue(path_is_within(nested / "episode.mkv", root))
            self.assertFalse(path_is_within(root, nested))
            self.assertEqual(
                collection_folder_for_video(nested / "episode.mkv", root),
                nested.resolve(),
            )
            collections = build_collections(
                [
                    Movie(
                        path=str(path),
                        title=path.stem,
                        root=str(root),
                        size=0,
                        modified=0,
                    )
                    for path in found
                ],
                [str(root)],
            )
            series = next(
                collection
                for collection in collections
                if collection.title == "Series"
            )
            self.assertTrue(series.is_series)
            self.assertEqual(len(series.movies), 2)
            self.assertEqual(series.cover, "")

    def test_only_cached_database_cover_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            local_cover = root / "videos" / "42" / "thumbnail.jpg"
            local_cover.parent.mkdir(parents=True)
            local_cover.write_bytes(b"local")
            database_cover_dir = root / "website-covers"
            database_cover_dir.mkdir()
            database_cover = database_cover_dir / "42-cover.img"
            database_cover.write_bytes(b"database")
            movie = Movie(
                path=str(local_cover.parent / "episode.mkv"),
                title="Episode",
                root=str(root),
                size=0,
                modified=0,
                media_id=42,
                cover_source_url="http://example.test/cover.jpg",
                cover=str(local_cover),
            )

            self.assertEqual(
                database_cover_for_movie(movie, database_cover_dir), ""
            )
            movie.cover = str(database_cover)
            self.assertEqual(
                database_cover_for_movie(movie, database_cover_dir),
                str(database_cover),
            )

    def test_library_refresh_posts_ids_and_updates_only_matching_movies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            class Store:
                preview_dir = root / "previews"
                website_cover_dir = root / "website-covers"

            Store.preview_dir.mkdir()
            Store.website_cover_dir.mkdir()
            requests = []

            class Response:
                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def read(self, _maximum):
                    return json.dumps(
                        {
                            "version": 1,
                            "media": [
                                {
                                    "id": 42,
                                    "type": "anime",
                                    "display_title": "Database Title",
                                    "cover_url": None,
                                    "website_url": "https://dordielist.test/media/42",
                                }
                            ],
                        }
                    ).encode()

            def open_request(request, timeout):
                requests.append((request, timeout))
                return Response()

            with patch(
                "dordiewatch.urllib.request.urlopen",
                side_effect=open_request,
            ):
                payloads = load_website_library(
                    "https://dordielist.test/api/dordiewatch/library?signature=test",
                    [42, 7, 42],
                    Store(),
                )

            self.assertEqual(len(requests), 1)
            request, timeout = requests[0]
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(json.loads(request.data), {"ids": [7, 42]})
            self.assertEqual(timeout, 20)

            linked_video = root / "42" / "episode.mkv"
            other_video = root / "7" / "episode.mkv"
            linked_video.parent.mkdir()
            other_video.parent.mkdir()
            linked_video.touch()
            other_video.touch()
            linked = Movie(
                path=str(linked_video),
                title="Unrelated Local Filename",
                root=str(root),
                size=0,
                modified=0,
                media_id=42,
            )
            other = Movie(
                path=str(other_video),
                title="Database Title",
                root=str(root),
                size=0,
                modified=0,
                media_id=7,
            )

            updated = update_movies_from_website(
                [linked, other], payloads, Store()
            )

            self.assertEqual(updated, 1)
            self.assertEqual(linked.collection_title, "Database Title")
            self.assertEqual(linked.media_type, "anime")
            self.assertTrue(Path(linked.thumbnail).is_file())
            self.assertEqual(other.collection_title, "")

    @unittest.skipUnless(find_binary("ffmpeg") and find_binary("ffprobe"), "FFmpeg required")
    def test_media_probe_preview_and_embedded_subtitle_playback(self) -> None:
        ffmpeg = find_binary("ffmpeg")
        ffprobe = find_binary("ffprobe")
        assert ffmpeg and ffprobe
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "video.mp4"
            subtitle = root / "subtitle.ass"
            output = root / "movie.mkv"
            subtitle.write_text(
                """[Script Info]
ScriptType: v4.00+
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,20,1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
Dialogue: 0,0:00:00.00,0:00:03.00,Default,,0,0,0,,Hello
""",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=640x360:rate=12",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=44100",
                    "-t",
                    "4",
                    "-c:v",
                    "mpeg4",
                    "-c:a",
                    "aac",
                    "-y",
                    str(video),
                ],
                check=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(video),
                    "-i",
                    str(subtitle),
                    "-map",
                    "0",
                    "-map",
                    "1",
                    "-c",
                    "copy",
                    "-metadata:s:s:0",
                    "language=eng",
                    "-y",
                    str(output),
                ],
                check=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            duration, width, height = probe_video(output, ffprobe)
            self.assertGreater(duration, 3_500)
            self.assertEqual((width, height), (640, 360))
            thumbnail, frames = generate_previews(
                output, root / cache_key(output, "test"), duration, ffmpeg
            )
            self.assertTrue(Path(thumbnail).is_file())
            self.assertGreaterEqual(len(frames), 4)
            with Image.open(thumbnail) as image:
                self.assertEqual(image.size, (640, 360))

            app = QApplication.instance() or QApplication([])
            previous_local_app_data = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = temporary
            try:
                window = DordieWatchWindow()
                window.show()
                app.processEvents()
                movie = Movie(
                    path=str(output),
                    title="Rapid close",
                    root=temporary,
                    size=output.stat().st_size,
                    modified=output.stat().st_mtime,
                    duration_ms=duration,
                )
                window.play_movie(movie)
                window.player.close_player()
                QTest.qWait(1_500)
                self.assertIsNone(window.player.movie)
                self.assertIs(window.pages.currentWidget(), window.home)
                window.close()
            finally:
                if previous_local_app_data is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous_local_app_data

    def test_mpv_engine_and_window_construct(self) -> None:
        self.assertIsNotNone(MPV_RUNTIME)
        self.assertIsNotNone(mpv)
        player = mpv.MPV(vo="null", ao="null", idle=True, config=False)
        self.assertIn("mpv", player.mpv_version)
        player.terminate()
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temporary:
            previous = os.environ.get("LOCALAPPDATA")
            os.environ["LOCALAPPDATA"] = temporary
            try:
                window = DordieWatchWindow()
                window.show()
                app.processEvents()
                self.assertEqual(window.pages.count(), 3)
                self.assertTrue(window.player.controller.available)
                self.assertTrue(
                    window.player.overlay.testAttribute(Qt.WA_TranslucentBackground)
                )
                window.player._sync_overlay_geometry()
                self.assertFalse(window.player.overlay.isWindow())
                self.assertIs(window.player.overlay.parent(), window.player)
                self.assertEqual(window.player.overlay.geometry(), window.player.rect())
                self.assertIs(window.player.top_bar.parent(), window.player.overlay)
                self.assertIs(window.player.bottom_bar.parent(), window.player.overlay)
                self.assertIsInstance(window.player.timeline, SeekSlider)
                window.player.timeline.setRange(0, 1_000)
                window.player.timeline.setFixedWidth(200)
                window.player.timeline.resize(200, 26)
                self.assertEqual(window.player.timeline.value_at_x(100), 500)
                seek_spy = QSignalSpy(window.player.timeline.seek_requested)
                QTest.mouseClick(
                    window.player.timeline,
                    Qt.LeftButton,
                    pos=QPoint(150, 10),
                )
                self.assertEqual(window.player.timeline.value(), 750)
                self.assertGreaterEqual(seek_spy.count(), 1)
                window.player.volume.setValue(0)
                self.assertEqual(window.player.volume_button.toolTip(), "Unmute (M)")
                window.player.volume.setValue(80)
                self.assertEqual(window.player.volume_button.toolTip(), "Mute (M)")
                self.assertEqual(window.player.volume_popup.size(), QSize(36, 200))
                self.assertEqual(window.player.volume.size(), QSize(22, 168))
                volume_click = QPoint(
                    window.player.volume.width() // 2,
                    window.player.volume.height() * 3 // 4,
                )
                expected_volume = window.player.volume.value_at_position(
                    volume_click
                )
                QTest.mouseClick(
                    window.player.volume,
                    Qt.LeftButton,
                    pos=volume_click,
                )
                self.assertEqual(window.player.volume.value(), expected_volume)
                window.player._position_volume_popup()
                volume_top = window.player.volume_button.mapTo(
                    window.player.overlay, QPoint(0, 0)
                ).y()
                self.assertEqual(
                    volume_top - window.player.volume_popup.geometry().bottom(),
                    7,
                )
                window.player.top_opacity.setOpacity(0)
                window.player.bottom_opacity.setOpacity(0)
                window.player.controls_visible = False
                QApplication.sendEvent(
                    window.player.bottom_bar, QEvent(QEvent.Enter)
                )
                QTest.qWait(300)
                self.assertTrue(window.player.controls_visible)
                self.assertGreater(window.player.bottom_opacity.opacity(), 0.75)
                window.player.controls_visible = False
                window.player._animate_controls(False)
                QTest.qWait(340)
                self.assertEqual(
                    window.player.top_bar.y(),
                    -window.player.top_bar.height(),
                )
                self.assertEqual(
                    window.player.bottom_bar.y(),
                    window.player.overlay.height(),
                )
                window.player._show_controls(keep=True)
                QTest.qWait(300)
                self.assertEqual(window.player.top_bar.y(), 0)
                self.assertEqual(
                    window.player.bottom_bar.y(),
                    window.player.overlay.height()
                    - window.player.bottom_bar.height(),
                )
                window.player._show_feedback_icon("play")
                play_size = window.player.icon_feedback.pixmap().size()
                window.player._show_feedback_icon("pause")
                self.assertEqual(window.player.icon_feedback.size(), QSize(88, 88))
                self.assertEqual(window.player.icon_feedback.pixmap().size(), play_size)
                QTest.qWait(210)
                self.assertGreater(
                    window.player.icon_feedback_opacity.opacity(), 0.7
                )
                QTest.qWait(540)
                self.assertTrue(window.player.icon_feedback.isHidden())
                window.player._show_feedback("Volume 80%")
                self.assertTrue(window.player.feedback.isHidden())
                window.player._show_toast("Subtitle selected")
                self.assertTrue(window.player.toast.isHidden())
                window.player._show_feedback_icon("play")
                self.assertFalse(window.player.icon_feedback.isHidden())
                window.player.pointer_timer.stop()
                window.player.play_button.set_hovered(True)
                QTest.qWait(240)
                self.assertEqual(
                    window.player.play_button.size(), QSize(64, 56)
                )
                self.assertGreaterEqual(
                    window.player.play_button.iconSize().width(), 47
                )
                window.player.play_button.set_hovered(False)
                QTest.qWait(190)
                self.assertEqual(
                    window.player.play_button.iconSize(), QSize(40, 40)
                )
                window.player.pointer_timer.start()
                window.player._sync_overlay_geometry()
                window.player.overlay.show()
                window.player._show_controls(keep=True)
                app.processEvents()
                self.assertFalse(
                    window.player.fullscreen_button.testAttribute(
                        Qt.WA_TransparentForMouseEvents
                    )
                )
                play_spy = QSignalSpy(window.player.play_button.clicked)
                QTest.mousePress(
                    window.player.play_button,
                    Qt.LeftButton,
                    pos=QPoint(32, 28),
                )
                app.processEvents()
                self.assertEqual(play_spy.count(), 0)
                QTest.mouseRelease(
                    window.player.play_button,
                    Qt.LeftButton,
                    pos=QPoint(32, 28),
                )
                app.processEvents()
                self.assertEqual(play_spy.count(), 1)
                QTest.mousePress(
                    window.player.fullscreen_button,
                    Qt.LeftButton,
                    pos=QPoint(32, 28),
                )
                app.processEvents()
                self.assertFalse(window.isFullScreen())
                QTest.mouseRelease(
                    window.player.fullscreen_button,
                    Qt.LeftButton,
                    pos=QPoint(32, 28),
                )
                app.processEvents()
                self.assertTrue(window.isFullScreen())
                play_count = play_spy.count()
                QTest.mouseClick(
                    window.player.play_button,
                    Qt.LeftButton,
                    pos=QPoint(32, 28),
                )
                app.processEvents()
                self.assertEqual(play_spy.count(), play_count + 1)
                self.assertTrue(window.isFullScreen())
                QTest.mousePress(
                    window.player.fullscreen_button,
                    Qt.LeftButton,
                    pos=QPoint(32, 28),
                )
                app.processEvents()
                self.assertTrue(window.isFullScreen())
                QTest.mouseRelease(
                    window.player.fullscreen_button,
                    Qt.LeftButton,
                    pos=QPoint(32, 28),
                )
                app.processEvents()
                self.assertFalse(window.isFullScreen())
                series_folder = str(
                    (Path(temporary) / "Example Series").resolve()
                )
                window.player.movie = Movie(
                    path=str(Path(temporary) / "episode-02.mkv"),
                    title="Episode 2",
                    root=temporary,
                    size=0,
                    modified=0,
                    collection=series_folder,
                )
                window.player._remember_subtitle_preference(22, "English")
                self.assertEqual(
                    window.settings["series_subtitles"][series_folder],
                    {"off": False, "label": "English", "track_id": 22},
                )
                original_tracks = window.player.controller.subtitle_tracks
                original_select = window.player.controller.select_subtitle
                selected_tracks = []
                window.player.subtitle_preference_applied = False
                window.player.controller.subtitle_tracks = lambda: [
                    (21, "French"),
                    (22, "English"),
                ]
                window.player.controller.select_subtitle = (
                    lambda track_id: selected_tracks.append(track_id)
                )
                window.player._apply_saved_subtitle_preference()
                self.assertEqual(selected_tracks, [22])
                self.assertEqual(window.player.selected_subtitle, 22)
                window.player._select_subtitle(-1)
                self.assertEqual(selected_tracks[-1], -1)
                window.player.controller.subtitle_tracks = original_tracks
                window.player.controller.select_subtitle = original_select
                window.player.movie = Movie(
                    path="missing.mkv",
                    title="Input handoff test",
                    root="",
                    size=0,
                    modified=0,
                )
                window.pages.setCurrentWidget(window.player)
                app.processEvents()
                window.player.overlay.show()
                window.player.open_settings_menu()
                app.processEvents()
                self.assertIsNotNone(window.player.track_panel)
                self.assertFalse(window.player.track_panel.isHidden())
                self.assertTrue(window.player.menu_open)
                QTest.mouseClick(
                    window.player.overlay,
                    Qt.LeftButton,
                    pos=QPoint(10, window.player.overlay.height() // 2),
                )
                app.processEvents()
                self.assertIsNone(window.player.track_panel)
                self.assertFalse(window.player.menu_open)
                window.player.open_settings_menu()
                app.processEvents()
                self.assertIsNotNone(window.player.track_panel)
                panel = window.player.track_panel
                window.player.controller.is_playing = lambda: True
                with patch.object(
                    window.player, "_cursor_in_controls_zone", return_value=True
                ), patch.object(
                    panel, "underMouse", return_value=False
                ), patch.object(
                    window.player.top_bar, "underMouse", return_value=False
                ), patch.object(
                    window.player.bottom_bar, "underMouse", return_value=False
                ), patch.object(
                    window.player.volume_popup, "underMouse", return_value=False
                ):
                    window.player._hide_controls()
                app.processEvents()
                self.assertIsNone(window.player.track_panel)
                self.assertFalse(window.player.menu_open)
                self.assertTrue(window.player.controls_visible)
                window.player.open_settings_menu()
                app.processEvents()
                track_options = window.player.track_panel.findChildren(
                    QPushButton, "trackOption"
                )
                self.assertTrue(track_options)
                self.assertTrue(
                    all(button.focusPolicy() == Qt.NoFocus for button in track_options)
                )
                QTest.mouseClick(track_options[-1], Qt.LeftButton)
                QTest.qWait(120)
                self.assertIsNone(window.player.track_panel)
                self.assertFalse(window.player.menu_open)
                play_count = play_spy.count()
                QTest.mousePress(
                    window.player.play_button,
                    Qt.LeftButton,
                    pos=QPoint(32, 28),
                )
                QTest.mouseRelease(
                    window.player.play_button,
                    Qt.LeftButton,
                    pos=QPoint(32, 28),
                )
                app.processEvents()
                self.assertEqual(play_spy.count(), play_count + 1)
                window.player.movie = None
                window.player.overlay.hide()
                window.showFullScreen()
                app.processEvents()
                self.assertTrue(window.isFullScreen())
                window.show_home()
                app.processEvents()
                self.assertFalse(window.isFullScreen())
                window.close()
            finally:
                if previous is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = previous


if __name__ == "__main__":
    unittest.main()
