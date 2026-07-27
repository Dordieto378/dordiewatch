from __future__ import annotations

import base64
import binascii
import ctypes
import ctypes.wintypes
import faulthandler
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import textwrap
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional


SOURCE_ROOT = Path(__file__).resolve().parent
VENDOR_ROOT = SOURCE_ROOT / "vendor"
if VENDOR_ROOT.is_dir():
    sys.path.insert(0, str(VENDOR_ROOT))


def bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", SOURCE_ROOT))


def project_videos_dir() -> Path:
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        project_candidate = executable_dir.parent.parent / "videos"
        if executable_dir.parent.name.casefold() == "dist":
            return project_candidate
        return executable_dir / "videos"
    return SOURCE_ROOT / "videos"


def website_launch_manifest(arguments: Iterable[str]) -> Optional[str]:
    for argument in arguments:
        if not argument.casefold().startswith("dordiewatch://"):
            continue
        parsed = urllib.parse.urlparse(argument)
        if parsed.netloc.casefold() != "open":
            continue
        manifest = urllib.parse.parse_qs(parsed.query).get("manifest", [None])[0]
        if manifest and urllib.parse.urlparse(manifest).scheme.casefold() not in {
            "http",
            "https",
        }:
            try:
                padding = "=" * (-len(manifest) % 4)
                manifest = base64.urlsafe_b64decode(
                    (manifest + padding).encode("ascii")
                ).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError, ValueError, binascii.Error):
                manifest = None
        if manifest and urllib.parse.urlparse(manifest).scheme.casefold() in {
            "http",
            "https",
        }:
            return manifest
    return None


def register_url_scheme() -> bool:
    if os.name != "nt":
        return False

    try:
        import winreg

        if getattr(sys, "frozen", False):
            command_prefix = subprocess.list2cmdline([str(Path(sys.executable).resolve())])
            icon_path = str(Path(sys.executable).resolve())
        else:
            command_prefix = subprocess.list2cmdline(
                [str(Path(sys.executable).resolve()), str(Path(__file__).resolve())]
            )
            icon_path = str(Path(sys.executable).resolve())

        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, r"Software\Classes\dordiewatch"
        ) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "URL:DordieWatch Protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Classes\dordiewatch\DefaultIcon",
        ) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, f'"{icon_path}",0')
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Classes\dordiewatch\shell\open\command",
        ) as key:
            winreg.SetValueEx(
                key,
                None,
                0,
                winreg.REG_SZ,
                f'{command_prefix} "%1"',
            )
        return True
    except OSError:
        return False


def find_mpv_runtime() -> Optional[Path]:
    candidates = [
        bundle_root() / "mpv",
        SOURCE_ROOT / "runtime" / "mpv",
        Path(os.getenv("PROGRAMFILES", r"C:\Program Files")) / "mpv",
    ]
    return next((path for path in candidates if (path / "libmpv-2.dll").is_file()), None)


MPV_RUNTIME = find_mpv_runtime()
_DLL_DIRECTORY_HANDLE = None
if MPV_RUNTIME:
    os.environ["PATH"] = str(MPV_RUNTIME) + os.pathsep + os.environ.get("PATH", "")
    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        _DLL_DIRECTORY_HANDLE = os.add_dll_directory(str(MPV_RUNTIME))

try:
    import mpv
except (ImportError, OSError):
    mpv = None

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import (
    QByteArray,
    QAbstractNativeEventFilter,
    QEasingCurve,
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    Property,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QOpenGLContext,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtSvg import QSvgRenderer


APP_NAME = "DordieWatch"
APP_VERSION = 4
VIDEO_EXTENSIONS = {
    ".3g2",
    ".3gp",
    ".asf",
    ".avi",
    ".flv",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".mts",
    ".ogv",
    ".ts",
    ".vob",
    ".webm",
    ".wmv",
}
def app_data_dir() -> Path:
    if os.name == "nt":
        root = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        root = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))
    result = root / "DordieWatch"
    legacy = root / "DordieCinema"
    if not result.exists() and legacy.is_dir():
        try:
            shutil.copytree(legacy, result)
        except OSError:
            pass
    result.mkdir(parents=True, exist_ok=True)
    return result


def install_crash_logging() -> None:
    try:
        crash_log = app_data_dir() / "crash.log"
        handle = crash_log.open("a", encoding="utf-8")
        handle.write(f"\n\n=== DordieWatch start {time.ctime()} ===\n")
        handle.flush()
        faulthandler.enable(file=handle, all_threads=True)

        def exception_hook(exc_type, exc_value, exc_traceback) -> None:
            traceback.print_exception(
                exc_type, exc_value, exc_traceback, file=handle
            )
            handle.flush()
            sys.__excepthook__(exc_type, exc_value, exc_traceback)

        sys.excepthook = exception_hook
    except OSError:
        pass


def find_binary(name: str) -> Optional[str]:
    executable = f"{name}.exe" if os.name == "nt" else name
    candidates = [
        bundle_root() / executable,
        Path(sys.executable).resolve().parent / executable,
        SOURCE_ROOT / "bin" / executable,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def process_options() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def path_is_within(path: Path | str, folder: Path | str) -> bool:
    try:
        Path(path).resolve().relative_to(Path(folder).resolve())
        return True
    except (OSError, ValueError):
        return False


def format_duration(milliseconds: int | float) -> str:
    seconds = max(0, int(float(milliseconds) / 1000))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def cache_key(path: Path, suffix: str = "") -> str:
    try:
        stat = path.stat()
        identity = f"{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|{suffix}"
    except OSError:
        identity = f"{path.resolve()}|{suffix}"
    return hashlib.sha1(identity.encode("utf-8", errors="replace")).hexdigest()


_FILE_FINGERPRINTS: dict[tuple[str, int, int], str] = {}
_FILE_FINGERPRINT_LOCK = threading.Lock()


def stable_file_fingerprint(path: Path) -> str:
    stat = path.stat()
    resolved = str(path.resolve())
    cache_id = (resolved, stat.st_mtime_ns, stat.st_size)
    with _FILE_FINGERPRINT_LOCK:
        cached = _FILE_FINGERPRINTS.get(cache_id)
    if cached:
        return cached

    chunk_size = 1024 * 1024
    offsets = {
        0,
        max(0, stat.st_size // 2 - chunk_size // 2),
        max(0, stat.st_size - chunk_size),
    }
    digest = hashlib.sha1()
    digest.update(f"size:{stat.st_size}".encode("ascii"))
    with path.open("rb") as handle:
        for offset in sorted(offsets):
            handle.seek(offset)
            digest.update(f"|offset:{offset}|".encode("ascii"))
            digest.update(handle.read(chunk_size))
    value = digest.hexdigest()
    with _FILE_FINGERPRINT_LOCK:
        _FILE_FINGERPRINTS[cache_id] = value
    return value


def discover_videos(folder: Path) -> list[Path]:
    videos: list[Path] = []
    try:
        for root, dirs, files in os.walk(folder):
            dirs[:] = [name for name in dirs if not name.startswith(".")]
            for filename in files:
                path = Path(root) / filename
                if path.suffix.lower() in VIDEO_EXTENSIONS:
                    videos.append(path)
    except OSError:
        pass
    return sorted(videos, key=lambda path: natural_sort_key(str(path)))


def natural_sort_key(value: str) -> tuple:
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part.casefold())
        for part in re.split(r"(\d+)", value)
    )


def collection_folder_for_video(video: Path, root: Path) -> Path:
    try:
        relative = video.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return video.parent.resolve()
    if len(relative.parts) > 1:
        return (root.resolve() / relative.parts[0]).resolve()
    # A loose video at the library root remains its own movie title.
    return video.resolve()


def draw_cover(painter: QPainter, target: QRect, pixmap: QPixmap) -> None:
    if pixmap.isNull():
        painter.fillRect(target, QColor("#202020"))
        return
    scaled = pixmap.scaled(
        target.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
    )
    source = QRect(
        max(0, (scaled.width() - target.width()) // 2),
        max(0, (scaled.height() - target.height()) // 2),
        target.width(),
        target.height(),
    )
    painter.drawPixmap(target, scaled, source)


@dataclass
class Movie:
    path: str
    title: str
    root: str
    size: int
    modified: float
    duration_ms: int = 0
    width: int = 0
    height: int = 0
    thumbnail: str = ""
    preview_frames: tuple[str, ...] = ()
    collection: str = ""
    cover: str = ""
    progress_ms: int = 0
    last_played: float = 0.0
    completed: bool = False
    media_id: Optional[int] = None
    media_type: str = ""
    collection_title: str = ""
    website_url: str = ""
    cover_source_url: str = ""

    @classmethod
    def from_dict(cls, value: dict) -> "Movie":
        fields = cls.__dataclass_fields__
        payload = {key: value[key] for key in fields if key in value}
        payload["preview_frames"] = tuple(payload.get("preview_frames", ()))
        return cls(**payload)

    def to_dict(self) -> dict:
        return asdict(self)


def database_cover_for_movie(
    movie: Movie, cover_directory: Optional[Path] = None
) -> str:
    if not (
        movie.media_id
        and movie.cover_source_url
        and movie.cover
    ):
        return ""
    cover_path = Path(movie.cover)
    database_cover_directory = (
        cover_directory
        if cover_directory is not None
        else app_data_dir() / "website-covers"
    )
    if (
        cover_path.is_file()
        and path_is_within(cover_path, database_cover_directory)
    ):
        return str(cover_path)
    return ""


@dataclass
class LibraryCollection:
    folder: str
    title: str
    movies: list[Movie]
    cover: str = ""

    @property
    def is_series(self) -> bool:
        return len(self.movies) > 1

    @property
    def representative(self) -> Movie:
        resumable = [
            movie
            for movie in self.movies
            if movie.progress_ms > 0
            and not movie.completed
            and (
                not movie.duration_ms
                or movie.progress_ms < movie.duration_ms * 0.92
            )
        ]
        if resumable:
            return max(resumable, key=lambda movie: movie.last_played)
        return self.movies[0]

    @property
    def modified(self) -> float:
        return max((movie.modified for movie in self.movies), default=0.0)

    @property
    def last_played(self) -> float:
        return max((movie.last_played for movie in self.movies), default=0.0)


def build_collections(
    movies: Iterable[Movie], roots: Iterable[str] = ()
) -> list[LibraryCollection]:
    known_roots = [Path(root) for root in roots]
    grouped: dict[str, list[Movie]] = {}
    folders: dict[str, Path] = {}
    for movie in movies:
        video = Path(movie.path)
        if movie.collection:
            folder = Path(movie.collection)
        else:
            matching_root = next(
                (root for root in known_roots if path_is_within(video, root)),
                Path(movie.root) if movie.root else video.parent,
            )
            folder = collection_folder_for_video(video, matching_root)
        if movie.media_id:
            key = f"dordielist:{movie.media_id}"
        else:
            try:
                key = str(folder.resolve())
            except OSError:
                key = str(folder)
        grouped.setdefault(key, []).append(movie)
        folders.setdefault(key, folder)

    collections: list[LibraryCollection] = []
    for key, items in grouped.items():
        items.sort(key=lambda movie: natural_sort_key(movie.path))
        folder = folders[key]
        folder_is_file = folder.is_file()
        title = next(
            (
                movie.collection_title
                for movie in items
                if movie.collection_title.strip()
            ),
            folder.stem if folder_is_file else folder.name,
        )
        database_covers = (
            database_cover_for_movie(movie) for movie in items
        )
        cover = next((path for path in database_covers if path), "")
        if not cover:
            cover = items[0].thumbnail
        collections.append(
            LibraryCollection(
                folder=key,
                title=title or items[0].title,
                movies=items,
                cover=cover,
            )
        )
    return sorted(
        collections, key=lambda collection: natural_sort_key(collection.title)
    )


def match_website_collection(
    payload: dict, collections: Iterable[LibraryCollection]
) -> Optional[LibraryCollection]:
    try:
        media_id = int(payload.get("id"))
    except (TypeError, ValueError):
        return None

    return next(
        (
            collection
            for collection in collections
            if any(movie.media_id == media_id for movie in collection.movies)
        ),
        None,
    )


MEDIA_LINK_FILENAME = ".dordielist.json"


def collection_database_id(folder: Path) -> Optional[int]:
    marker = folder / MEDIA_LINK_FILENAME
    if not marker.is_file():
        try:
            folder_media_id = int(folder.name)
            return folder_media_id if folder_media_id > 0 else None
        except ValueError:
            return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        media_id = int(payload.get("media_id"))
        return media_id if media_id > 0 else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def link_collection_to_database_id(folder: Path, media_id: int) -> Path:
    media_id = int(media_id)
    if media_id <= 0 or not folder.is_dir():
        raise ValueError("The local folder or database media ID is invalid.")

    marker = folder / MEDIA_LINK_FILENAME
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"media_id": media_id}, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(marker)
    return marker


class DordieWatchStore:
    def __init__(self) -> None:
        self.base_dir = app_data_dir()
        self.preview_dir = self.base_dir / "previews"
        self.website_cover_dir = self.base_dir / "website-covers"
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        self.website_cover_dir.mkdir(parents=True, exist_ok=True)
        self.file = self.base_dir / "library.json"

    def load(self) -> tuple[list[str], list[Movie], dict]:
        defaults = {
            "volume": 80,
            "series_subtitles": {},
            "dordielist_library_url": "",
        }
        if not self.file.is_file():
            return [], [], defaults
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
            roots = [
                str(Path(root).resolve())
                for root in data.get("roots", [])
                if Path(root).is_dir()
            ]
            movies = [
                Movie.from_dict(item)
                for item in data.get("movies", [])
                if Path(item.get("path", "")).is_file()
            ]
            settings = defaults | data.get("settings", {})
            return roots, movies, settings
        except (OSError, ValueError, TypeError):
            return [], [], defaults

    def save(self, roots: Iterable[str], movies: Iterable[Movie], settings: dict) -> None:
        payload = {
            "version": APP_VERSION,
            "roots": list(roots),
            "movies": [movie.to_dict() for movie in movies],
            "settings": settings,
        }
        temporary = self.file.with_suffix(".tmp")
        try:
            temporary.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            temporary.replace(self.file)
        except OSError:
            pass


def probe_video(path: Path, ffprobe: Optional[str]) -> tuple[int, int, int]:
    if not ffprobe:
        return 0, 0, 0
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,duration:format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=25,
            **process_options(),
        )
        data = json.loads(result.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        duration = float(
            stream.get("duration") or data.get("format", {}).get("duration") or 0
        )
        return (
            int(duration * 1000),
            int(stream.get("width") or 0),
            int(stream.get("height") or 0),
        )
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return 0, 0, 0


def _placeholder_image(path: Path, title: str) -> None:
    image = Image.new("RGB", (640, 360), "#181818")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 639, 359), outline="#303030", width=2)
    draw.polygon([(285, 135), (285, 225), (370, 180)], fill="#e50914")
    draw.text(
        (24, 320),
        textwrap.shorten(title, width=60, placeholder="…"),
        fill="#dddddd",
        font=ImageFont.load_default(),
    )
    image.save(path, format="JPEG", quality=88)


def catalog_placeholder(
    store: DordieWatchStore, video: Path, title: str
) -> str:
    preview_dir = (
        store.preview_dir
        / cache_key(video, "catalog-placeholder-v2")
    )
    preview_dir.mkdir(parents=True, exist_ok=True)
    placeholder = preview_dir / "thumbnail.jpg"
    if not placeholder.is_file():
        _placeholder_image(placeholder, title)
    return str(placeholder)


def update_movies_from_website(
    movies: Iterable[Movie],
    payloads: Iterable[dict],
    store: DordieWatchStore,
) -> int:
    media_by_id: dict[int, dict] = {}
    for payload in payloads:
        try:
            media_id = int(payload["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if str(payload.get("type") or "").casefold() in {"anime", "hentai"}:
            media_by_id[media_id] = payload

    updated = 0
    for movie in movies:
        payload = media_by_id.get(movie.media_id or 0)
        if payload is None:
            continue
        previous_cover_url = movie.cover_source_url
        previous_cover = database_cover_for_movie(
            movie, store.website_cover_dir
        )
        movie.media_type = str(payload.get("type") or "").casefold()
        movie.collection_title = str(
            payload.get("display_title") or movie.collection_title or movie.title
        ).strip()
        movie.website_url = str(payload.get("website_url") or "").strip()
        movie.cover_source_url = str(payload.get("cover_url") or "").strip()

        downloaded_cover = str(payload.get("_cover_path") or "").strip()
        if (
            downloaded_cover
            and Path(downloaded_cover).is_file()
            and path_is_within(downloaded_cover, store.website_cover_dir)
        ):
            movie.cover = downloaded_cover
            movie.thumbnail = downloaded_cover
        elif previous_cover and previous_cover_url == movie.cover_source_url:
            movie.cover = previous_cover
            movie.thumbnail = previous_cover
        else:
            movie.cover = ""
            movie.thumbnail = catalog_placeholder(
                store, Path(movie.path), movie.title
            )
        updated += 1
    return updated


def generate_previews(
    video: Path, output_dir: Path, duration_ms: int, ffmpeg: Optional[str]
) -> tuple[str, tuple[str, ...]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    thumbnail = output_dir / "thumbnail.jpg"
    existing = sorted(output_dir.glob("preview-*.jpg"))
    if thumbnail.is_file() and existing:
        return str(thumbnail), tuple(str(frame) for frame in existing)

    duration = duration_ms / 1000
    fractions = (0.08, 0.24, 0.40, 0.56, 0.72, 0.88)
    frames: list[Path] = []
    if ffmpeg:
        for index, fraction in enumerate(fractions, 1):
            frame = output_dir / f"preview-{index:02d}.jpg"
            seek = duration * fraction if duration else float(index - 1)
            command = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{seek:.3f}",
                "-i",
                str(video),
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-vf",
                (
                    "scale=640:360:force_original_aspect_ratio=increase,"
                    "crop=640:360"
                ),
                "-q:v",
                "3",
                "-y",
                str(frame),
            ]
            try:
                subprocess.run(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=35,
                    **process_options(),
                )
                if frame.is_file():
                    frames.append(frame)
            except (OSError, subprocess.SubprocessError):
                continue

    if not frames:
        fallback = output_dir / "preview-01.jpg"
        try:
            _placeholder_image(fallback, video.stem)
            frames.append(fallback)
        except OSError:
            return "", ()

    try:
        with Image.open(frames[min(2, len(frames) - 1)]) as source:
            source.convert("RGB").save(
                thumbnail, format="JPEG", quality=90, optimize=True
            )
    except OSError:
        thumbnail = frames[0]
    return str(thumbnail), tuple(str(frame) for frame in frames)


def _read_website_json(
    request: urllib.request.Request,
    *,
    maximum_size: int,
    forbidden_message: str,
    invalid_message: str,
) -> object:
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(maximum_size + 1)
    except urllib.error.HTTPError as error:
        if error.code == 403:
            raise RuntimeError(forbidden_message) from error
        raise RuntimeError(f"The website returned HTTP {error.code}.") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RuntimeError(f"Could not connect to DordieList: {error}") from error

    if len(raw) > maximum_size:
        raise RuntimeError("The website response was unexpectedly large.")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(invalid_message) from error


def _prepare_website_media(
    payload: object, store: DordieWatchStore
) -> dict:
    if not isinstance(payload, dict):
        raise RuntimeError("The website returned invalid media data.")
    payload = dict(payload)
    try:
        payload["id"] = int(payload["id"])
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("The website response does not contain a valid media ID.") from error
    if str(payload.get("type", "")).casefold() not in {"anime", "hentai"}:
        raise RuntimeError("DordieWatch can only open anime and hentai entries.")

    cover_url = str(payload.get("cover_url") or "").strip()
    if cover_url:
        parsed_cover = urllib.parse.urlparse(cover_url)
        if parsed_cover.scheme.casefold() in {"http", "https"}:
            digest = hashlib.sha1(cover_url.encode("utf-8")).hexdigest()[:12]
            cover_path = store.website_cover_dir / f"{payload['id']}-{digest}.img"
            if not cover_path.is_file():
                temporary = cover_path.with_name(
                    f"{cover_path.name}.{os.getpid()}.part"
                )
                cover_request = urllib.request.Request(
                    cover_url,
                    headers={
                        "Accept": "image/*",
                        "User-Agent": f"{APP_NAME}/{APP_VERSION}",
                    },
                )
                try:
                    with urllib.request.urlopen(cover_request, timeout=20) as response:
                        image_data = response.read(30 * 1024 * 1024 + 1)
                    if len(image_data) > 30 * 1024 * 1024:
                        raise RuntimeError("The database cover image is too large.")
                    temporary.write_bytes(image_data)
                    with Image.open(temporary) as image:
                        image.verify()
                    temporary.replace(cover_path)
                except Exception:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass
            if cover_path.is_file():
                payload["_cover_path"] = str(cover_path)
    return payload


def load_website_media(manifest_url: str, store: DordieWatchStore) -> dict:
    request = urllib.request.Request(
        manifest_url,
        headers={
            "Accept": "application/json",
            "User-Agent": f"{APP_NAME}/{APP_VERSION}",
        },
    )
    payload = _read_website_json(
        request,
        maximum_size=2 * 1024 * 1024,
        forbidden_message=(
            "This website Play link has expired. Return to the website and click it again."
        ),
        invalid_message="The website returned invalid media data.",
    )
    return _prepare_website_media(payload, store)


def load_website_library(
    library_url: str,
    media_ids: Iterable[int],
    store: DordieWatchStore,
) -> list[dict]:
    requested_ids = sorted(
        {
            int(media_id)
            for media_id in media_ids
            if int(media_id) > 0
        }
    )
    if not requested_ids:
        return []
    request = urllib.request.Request(
        library_url,
        data=json.dumps({"ids": requested_ids}).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": f"{APP_NAME}/{APP_VERSION}",
        },
        method="POST",
    )
    response = _read_website_json(
        request,
        maximum_size=8 * 1024 * 1024,
        forbidden_message=(
            "The saved DordieList refresh connection is no longer valid. "
            "Open any anime or hentai from the website once to reconnect it."
        ),
        invalid_message="DordieList returned invalid library data.",
    )
    if not isinstance(response, dict) or not isinstance(response.get("media"), list):
        raise RuntimeError("DordieList returned invalid library data.")
    return [
        _prepare_website_media(payload, store)
        for payload in response["media"]
    ]


class WebsiteMediaSignals(QObject):
    loaded = Signal(object)
    failed = Signal(str)


class WebsiteMediaTask:
    def __init__(self, manifest_url: str, store: DordieWatchStore) -> None:
        from PySide6.QtCore import QRunnable

        class Runnable(QRunnable):
            def __init__(inner, owner: "WebsiteMediaTask") -> None:
                super().__init__()
                inner.owner = owner

            def run(inner) -> None:
                inner.owner.run()

        self.manifest_url = manifest_url
        self.store = store
        self.signals = WebsiteMediaSignals()
        self.runnable = Runnable(self)

    def run(self) -> None:
        try:
            self.signals.loaded.emit(
                load_website_media(self.manifest_url, self.store)
            )
        except Exception as error:
            try:
                self.signals.failed.emit(str(error))
            except RuntimeError:
                return


class WebsiteLibraryTask:
    def __init__(
        self,
        library_url: str,
        media_ids: Iterable[int],
        store: DordieWatchStore,
    ) -> None:
        from PySide6.QtCore import QRunnable

        class Runnable(QRunnable):
            def __init__(inner, owner: "WebsiteLibraryTask") -> None:
                super().__init__()
                inner.owner = owner

            def run(inner) -> None:
                inner.owner.run()

        self.library_url = library_url
        self.media_ids = tuple(media_ids)
        self.store = store
        self.signals = WebsiteMediaSignals()
        self.runnable = Runnable(self)

    def run(self) -> None:
        try:
            self.signals.loaded.emit(
                load_website_library(
                    self.library_url, self.media_ids, self.store
                )
            )
        except Exception as error:
            try:
                self.signals.failed.emit(str(error))
            except RuntimeError:
                return


class ScanSignals(QObject):
    movie = Signal(object)
    progress = Signal(int, int, str)
    finished = Signal(str)
    failed = Signal(str)


class LibraryScanTask:
    def __init__(
        self,
        root: Path,
        store: DordieWatchStore,
        existing_movies: Iterable[Movie] = (),
    ) -> None:
        from PySide6.QtCore import QRunnable

        class Runnable(QRunnable):
            def __init__(inner, owner: "LibraryScanTask") -> None:
                super().__init__()
                inner.owner = owner

            def run(inner) -> None:
                inner.owner.run()

        self.root = root.resolve()
        self.store = store
        self.runnable = Runnable(self)
        self.signals = ScanSignals()
        self.cancelled = threading.Event()
        existing_movie_list = list(existing_movies)
        self.existing_movies = {
            str(Path(movie.path).resolve()).casefold(): movie
            for movie in existing_movie_list
        }
        self.existing_media: dict[int, Movie] = {}
        for movie in existing_movie_list:
            if movie.media_id is None:
                continue
            saved = self.existing_media.get(movie.media_id)
            saved_score = (
                sum(
                    bool(value)
                    for value in (
                        saved.media_type,
                        saved.collection_title,
                        saved.website_url,
                        saved.cover_source_url,
                    )
                )
                if saved
                else -1
            )
            movie_score = sum(
                bool(value)
                for value in (
                    movie.media_type,
                    movie.collection_title,
                    movie.website_url,
                    movie.cover_source_url,
                )
            )
            if movie_score > saved_score:
                self.existing_media[movie.media_id] = movie

    def cancel(self) -> None:
        self.cancelled.set()

    def restore_database_metadata(
        self,
        movie: Movie,
        database_media_id: Optional[int],
        path: Path,
    ) -> None:
        movie.media_id = database_media_id
        movie.media_type = ""
        movie.collection_title = ""
        movie.website_url = ""
        movie.cover_source_url = ""
        movie.cover = ""

        saved = (
            self.existing_media.get(database_media_id)
            if database_media_id is not None
            else None
        )
        if saved is not None:
            movie.media_type = saved.media_type
            movie.collection_title = saved.collection_title
            movie.website_url = saved.website_url
            movie.cover_source_url = saved.cover_source_url
            movie.cover = saved.cover

        database_cover = database_cover_for_movie(
            movie,
            getattr(self.store, "website_cover_dir", None),
        )
        if database_cover:
            movie.cover = database_cover
            movie.thumbnail = database_cover
        else:
            movie.cover = ""
            movie.thumbnail = catalog_placeholder(
                self.store, path, path.stem
            )

    def run(self) -> None:
        try:
            paths = discover_videos(self.root)
            total = len(paths)
            for index, path in enumerate(paths, 1):
                if self.cancelled.is_set():
                    return
                self.signals.progress.emit(index - 1, total, path.name)
                try:
                    stat = path.stat()
                except OSError:
                    continue
                collection_folder = collection_folder_for_video(path, self.root)
                database_media_id = (
                    collection_database_id(collection_folder)
                    if collection_folder.is_dir()
                    else None
                )
                existing = self.existing_movies.get(
                    str(path.resolve()).casefold()
                )
                if (
                    existing is not None
                    and existing.size == stat.st_size
                    and existing.modified == stat.st_mtime
                ):
                    movie = Movie.from_dict(existing.to_dict())
                    movie.root = str(self.root)
                    movie.collection = str(collection_folder)
                else:
                    movie = Movie(
                        path=str(path),
                        title=path.stem,
                        root=str(self.root),
                        size=stat.st_size,
                        modified=stat.st_mtime,
                        collection=str(collection_folder),
                    )
                self.restore_database_metadata(
                    movie, database_media_id, path
                )
                self.signals.movie.emit(
                    movie.to_dict()
                )
                self.signals.progress.emit(index, total, path.name)
            self.signals.finished.emit(str(self.root))
        except RuntimeError:
            return
        except Exception as error:
            try:
                self.signals.failed.emit(str(error))
            except RuntimeError:
                return


class MovieCard(QWidget):
    activated = Signal(object)

    def __init__(self, movie: Movie, width: int = 260) -> None:
        super().__init__()
        self.movie = movie
        self.card_width = width
        self.card_height = int(width * 9 / 16)
        self.thumbnail = QPixmap(movie.thumbnail)
        self.current_pixmap = self.thumbnail
        self.hovered = False
        self.preview_pixmaps: list[QPixmap] = []
        self.preview_index = 0
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(310)
        self.preview_timer.timeout.connect(self._advance_preview)
        self.setFixedSize(width, self.card_height + 43)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(movie.title)

    def enterEvent(self, event) -> None:
        self.hovered = True
        self.preview_pixmaps = [
            QPixmap(path)
            for path in self.movie.preview_frames
            if Path(path).is_file()
        ]
        self.preview_pixmaps = [
            pixmap for pixmap in self.preview_pixmaps if not pixmap.isNull()
        ]
        if len(self.preview_pixmaps) > 1:
            self.preview_index = 0
            self.current_pixmap = self.preview_pixmaps[0]
            self.preview_timer.start()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.hovered = False
        self.preview_timer.stop()
        self.preview_pixmaps.clear()
        self.current_pixmap = self.thumbnail
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.activated.emit(self.movie)
            event.accept()
            return
        super().mousePressEvent(event)

    def _advance_preview(self) -> None:
        if not self.preview_pixmaps:
            self.preview_timer.stop()
            return
        self.preview_index = (self.preview_index + 1) % len(self.preview_pixmaps)
        self.current_pixmap = self.preview_pixmaps[self.preview_index]
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        image_rect = QRect(0, 0, self.card_width, self.card_height)
        clip = QPainterPath()
        clip.addRoundedRect(image_rect, 6, 6)
        painter.save()
        painter.setClipPath(clip)
        draw_cover(painter, image_rect, self.current_pixmap)
        if self.hovered:
            painter.fillRect(image_rect, QColor(0, 0, 0, 55))
            play_rect = QRect(
                self.card_width // 2 - 23, self.card_height // 2 - 23, 46, 46
            )
            painter.setBrush(QColor(255, 255, 255, 225))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(play_rect)
            painter.setBrush(QColor("#111111"))
            painter.drawPolygon(
                [
                    QPoint(play_rect.x() + 19, play_rect.y() + 13),
                    QPoint(play_rect.x() + 19, play_rect.y() + 33),
                    QPoint(play_rect.x() + 34, play_rect.y() + 23),
                ]
            )
        painter.restore()

        if self.movie.duration_ms and self.movie.progress_ms:
            ratio = min(1.0, self.movie.progress_ms / self.movie.duration_ms)
            painter.fillRect(
                QRect(0, self.card_height - 4, self.card_width, 4), QColor("#555555")
            )
            painter.fillRect(
                QRect(0, self.card_height - 4, int(self.card_width * ratio), 4),
                QColor("#e50914"),
            )

        painter.setPen(QColor("#f2f2f2"))
        painter.setFont(QFont("Segoe UI", 10, QFont.DemiBold))
        title = painter.fontMetrics().elidedText(
            self.movie.title, Qt.ElideRight, self.card_width
        )
        painter.drawText(
            QRect(0, self.card_height + 8, self.card_width, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            title,
        )
        painter.setPen(QColor("#8d8d8d"))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(
            QRect(0, self.card_height + 27, self.card_width, 14),
            Qt.AlignLeft | Qt.AlignVCenter,
            f"{format_duration(self.movie.duration_ms)}  ·  {format_bytes(self.movie.size)}",
        )


class MovieRow(QWidget):
    movie_activated = Signal(object)

    def __init__(self, title: str, movies: list[Movie]) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(9)
        heading = QLabel(title)
        heading.setObjectName("rowHeading")
        layout.addWidget(heading)
        scroll = QScrollArea()
        scroll.setObjectName("rowScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedHeight(225)
        canvas = QWidget()
        row = QHBoxLayout(canvas)
        row.setContentsMargins(0, 0, 20, 0)
        row.setSpacing(12)
        for movie in movies:
            card = MovieCard(movie)
            card.activated.connect(self.movie_activated)
            row.addWidget(card)
        row.addStretch()
        scroll.setWidget(canvas)
        layout.addWidget(scroll)


class CollectionCard(QWidget):
    activated = Signal(object)

    def __init__(self, collection: LibraryCollection, width: int = 190) -> None:
        super().__init__()
        self.collection = collection
        self.card_width = width
        self.card_height = round(width * 1.5)
        self.cover = QPixmap(collection.cover)
        self.hovered = False
        self.setFixedSize(width, self.card_height + 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(collection.title)

    def enterEvent(self, event) -> None:
        self.hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.activated.emit(self.collection)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        image_rect = QRect(0, 0, self.card_width, self.card_height)
        clip = QPainterPath()
        clip.addRoundedRect(image_rect, 7, 7)
        painter.save()
        painter.setClipPath(clip)
        draw_cover(painter, image_rect, self.cover)
        if self.hovered:
            painter.fillRect(image_rect, QColor(0, 0, 0, 58))
            play_rect = QRect(
                self.card_width // 2 - 24,
                self.card_height // 2 - 24,
                48,
                48,
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 230))
            painter.drawEllipse(play_rect)
            painter.setBrush(QColor("#111111"))
            painter.drawPolygon(
                [
                    QPoint(play_rect.x() + 19, play_rect.y() + 13),
                    QPoint(play_rect.x() + 19, play_rect.y() + 35),
                    QPoint(play_rect.x() + 35, play_rect.y() + 24),
                ]
            )
        painter.restore()

        representative = self.collection.representative
        if representative.duration_ms and representative.progress_ms:
            ratio = min(
                1.0, representative.progress_ms / representative.duration_ms
            )
            painter.fillRect(
                QRect(0, self.card_height - 4, self.card_width, 4),
                QColor("#555555"),
            )
            painter.fillRect(
                QRect(
                    0,
                    self.card_height - 4,
                    int(self.card_width * ratio),
                    4,
                ),
                QColor("#e50914"),
            )

        painter.setPen(QColor("#f2f2f2"))
        painter.setFont(QFont("Segoe UI", 10, QFont.DemiBold))
        title = painter.fontMetrics().elidedText(
            self.collection.title, Qt.ElideRight, self.card_width
        )
        painter.drawText(
            QRect(0, self.card_height + 7, self.card_width, 19),
            Qt.AlignLeft | Qt.AlignVCenter,
            title,
        )

class CollectionRow(QWidget):
    collection_activated = Signal(object)

    def __init__(
        self, title: str, collections: list[LibraryCollection]
    ) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 10)
        layout.setSpacing(9)
        heading = QLabel(title)
        heading.setObjectName("rowHeading")
        layout.addWidget(heading)
        scroll = QScrollArea()
        scroll.setObjectName("rowScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedHeight(337)
        canvas = QWidget()
        row = QHBoxLayout(canvas)
        row.setContentsMargins(0, 0, 20, 0)
        row.setSpacing(14)
        for collection in collections:
            card = CollectionCard(collection)
            card.activated.connect(self.collection_activated)
            row.addWidget(card)
        row.addStretch()
        scroll.setWidget(canvas)
        layout.addWidget(scroll)


class HeroWidget(QWidget):
    play_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.collection: Optional[LibraryCollection] = None
        self.pixmap = QPixmap()
        self.setMinimumHeight(380)
        self.setMaximumHeight(470)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(50, 40, 50, 50)
        layout.addStretch()
        self.kicker = QLabel("FEATURED")
        self.kicker.setObjectName("heroKicker")
        self.title = QLabel("")
        self.title.setObjectName("heroTitle")
        self.title.setWordWrap(True)
        self.meta = QLabel("")
        self.meta.setObjectName("heroMeta")
        button_row = QHBoxLayout()
        self.play = QPushButton("▶  Play")
        self.play.setObjectName("heroPlay")
        self.play.clicked.connect(self._emit_play)
        button_row.addWidget(self.play)
        button_row.addStretch()
        layout.addWidget(self.kicker)
        layout.addWidget(self.title)
        layout.addWidget(self.meta)
        layout.addSpacing(10)
        layout.addLayout(button_row)

    def set_collection(
        self, collection: Optional[LibraryCollection]
    ) -> None:
        self.collection = collection
        representative = collection.representative if collection else None
        self.pixmap = (
            QPixmap(representative.thumbnail or collection.cover)
            if representative and collection
            else QPixmap()
        )
        if collection and representative:
            self.title.setText(collection.title)
            details = (
                f"{len(collection.movies)} episodes"
                if collection.is_series
                else format_duration(representative.duration_ms)
            )
            resolution = (
                f"{representative.height}p"
                if representative.height
                else "Local video"
            )
            self.meta.setText(f"{details}   •   {resolution}")
            self.play.setText(
                "Episodes" if collection.is_series else "Play"
            )
            self.play.show()
            self.kicker.show()
        else:
            self.title.setText("Your library, your files")
            self.meta.setText("Add a video folder to build your library.")
            self.play.hide()
            self.kicker.hide()
        self.update()

    def _emit_play(self) -> None:
        if self.collection:
            self.play_requested.emit(self.collection)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        draw_cover(painter, self.rect(), self.pixmap)
        horizontal = QLinearGradient(0, 0, self.width(), 0)
        horizontal.setColorAt(0.0, QColor(0, 0, 0, 245))
        horizontal.setColorAt(0.52, QColor(0, 0, 0, 115))
        horizontal.setColorAt(1.0, QColor(0, 0, 0, 20))
        painter.fillRect(self.rect(), horizontal)
        vertical = QLinearGradient(0, 0, 0, self.height())
        vertical.setColorAt(0.55, QColor(0, 0, 0, 0))
        vertical.setColorAt(1.0, QColor(5, 5, 5, 255))
        painter.fillRect(self.rect(), vertical)


def build_home_refresh_icon() -> QIcon:
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.transparent)
    svg = """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">
      <path fill="#ffffff" d="M35.3 14.7C32.4 11.8 28.4 10 24 10C15.2 10 8 17.2 8 26C8 34.8 15.2 42 24 42C31.4 42 37.6 36.9 39.4 30H34.4C32.7 34.7 28.2 38 24 38C17.4 38 12 32.6 12 26C12 19.4 17.4 14 24 14C27.3 14 30.3 15.3 32.5 17.5L26 24H42V8L35.3 14.7Z"/>
    </svg>
    """
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(5, 5, 38, 38))
    painter.end()
    return QIcon(pixmap)


def build_home_search_icon() -> QIcon:
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.transparent)
    svg = """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">
      <path fill="none" stroke="#ffffff" stroke-width="3.8" stroke-linecap="round" d="M21.5 12.5A9 9 0 1 0 21.5 30.5A9 9 0 1 0 21.5 12.5"/>
      <path fill="none" stroke="#ffffff" stroke-width="3.8" stroke-linecap="round" d="M28.2 28.2L36 36"/>
    </svg>
    """
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(7, 7, 34, 34))
    painter.end()
    return QIcon(pixmap)


class HomeIconButton(QToolButton):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.base_icon_size = QSize(34, 34)
        self.hover_icon_size = QSize(42, 42)
        self._size_animation = QPropertyAnimation(self, b"iconSize", self)
        self.setFixedSize(56, 52)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setIconSize(self.base_icon_size)

    def _animate_icon(self, target: QSize) -> None:
        self._size_animation.stop()
        self._size_animation.setDuration(140)
        self._size_animation.setStartValue(self.iconSize())
        self._size_animation.setEndValue(target)
        self._size_animation.setEasingCurve(QEasingCurve.InOutCubic)
        self._size_animation.start()

    def enterEvent(self, event) -> None:
        self._animate_icon(self.hover_icon_size)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate_icon(self.base_icon_size)
        super().leaveEvent(event)


class AnimatedSearchBox(QFrame):
    width_changed = Signal()

    COLLAPSED_WIDTH = 56
    EXPANDED_WIDTH = 400

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.expanded = False
        self._animated_width = self.COLLAPSED_WIDTH
        self.setObjectName("homeSearchBox")
        self.setProperty("expanded", False)
        self.setFixedHeight(56)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._set_animated_width(self.COLLAPSED_WIDTH)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.width_animation = QPropertyAnimation(self, b"animatedWidth", self)
        self.width_animation.setDuration(230)
        self.width_animation.setEasingCurve(QEasingCurve.InOutCubic)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 14, 0)
        layout.setSpacing(0)
        self.button = QToolButton()
        self.button.setObjectName("homeSearchButton")
        self.button.setIcon(build_home_search_icon())
        self.button.setIconSize(QSize(48, 48))
        self.button.setFixedSize(56, 52)
        self.button.setCursor(Qt.PointingHandCursor)
        self.edit = QLineEdit()
        self.edit.setObjectName("homeSearchInput")
        self.edit.setPlaceholderText("")
        self.edit.setClearButtonEnabled(False)
        self.edit.setMinimumWidth(0)
        self.edit.setVisible(False)
        self.edit.installEventFilter(self)
        layout.addWidget(self.button)
        layout.addWidget(self.edit, 1)
        self.button.clicked.connect(self.expand)

    def _get_animated_width(self) -> int:
        return self._animated_width

    def _set_animated_width(self, width: int) -> None:
        self._animated_width = int(width)
        self.setMinimumWidth(self._animated_width)
        self.setMaximumWidth(self._animated_width)
        self.resize(self._animated_width, self.height())
        self.updateGeometry()
        self.width_changed.emit()

    animatedWidth = Property(int, _get_animated_width, _set_animated_width)

    def expand(self) -> None:
        if self.expanded:
            self.edit.setFocus(Qt.MouseFocusReason)
            return
        self.expanded = True
        self.setProperty("expanded", True)
        self.style().unpolish(self)
        self.style().polish(self)
        self.setCursor(Qt.IBeamCursor)
        self.edit.setVisible(True)
        self.width_animation.stop()
        self.width_animation.setStartValue(self._animated_width)
        self.width_animation.setEndValue(self.EXPANDED_WIDTH)
        self.width_animation.start()
        QTimer.singleShot(80, lambda: self.edit.setFocus(Qt.MouseFocusReason))

    def collapse_if_empty(self) -> None:
        if not self.expanded or self.edit.text():
            return
        self.expanded = False
        self.setProperty("expanded", False)
        self.style().unpolish(self)
        self.style().polish(self)
        self.setCursor(Qt.PointingHandCursor)
        self.edit.clearFocus()
        self.width_animation.stop()
        self.width_animation.setStartValue(self._animated_width)
        self.width_animation.setEndValue(self.COLLAPSED_WIDTH)
        self.width_animation.start()
        QTimer.singleShot(230, lambda: self.edit.setVisible(self.expanded))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.expand()
            event.accept()
            return
        super().mousePressEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.edit and event.type() == QEvent.FocusOut:
            QTimer.singleShot(80, self.collapse_if_empty)
        return super().eventFilter(watched, event)


class HomePage(QWidget):
    refresh_requested = Signal()
    movie_activated = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        header = QFrame()
        self.header = header
        header.setObjectName("homeHeader")
        header.setFixedHeight(68)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(28, 0, 28, 0)
        header_layout.setSpacing(18)
        logo = QLabel("D")
        logo.setObjectName("brandLogo")
        brand = QLabel("DORDIEWATCH")
        brand.setObjectName("brandName")
        home = QLabel("Home")
        home.setObjectName("navActive")
        library = QLabel("My Library")
        library.setObjectName("navItem")
        self.search_box = AnimatedSearchBox(header)
        self.search = self.search_box.edit
        self.refresh_button = HomeIconButton()
        self.refresh_button.setObjectName("homeRefreshIcon")
        self.refresh_button.setToolTip("Refresh library")
        self.refresh_button.setIcon(build_home_refresh_icon())
        self.header_controls = QWidget()
        self.header_controls.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        header_controls_layout = QHBoxLayout(self.header_controls)
        header_controls_layout.setContentsMargins(0, 0, 0, 0)
        header_controls_layout.setSpacing(0)
        header_controls_layout.addWidget(self.refresh_button)
        header_layout.addWidget(logo)
        header_layout.addWidget(brand)
        header_layout.addSpacing(15)
        header_layout.addWidget(home)
        header_layout.addWidget(library)
        header_layout.addStretch()
        header_layout.addWidget(self.header_controls)
        root.addWidget(header)

        self.progress_frame = QFrame()
        self.progress_frame.setObjectName("scanStrip")
        progress_layout = QHBoxLayout(self.progress_frame)
        progress_layout.setContentsMargins(28, 4, 28, 4)
        self.progress_text = QLabel("")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        progress_layout.addWidget(self.progress_text)
        progress_layout.addWidget(self.progress, 1)
        self.progress_frame.hide()
        root.addWidget(self.progress_frame)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("homeScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.content = QWidget()
        self.content.setObjectName("homeContent")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 45)
        self.content_layout.setSpacing(8)
        self.hero = HeroWidget()
        self.hero.play_requested.connect(self.movie_activated)
        self.content_layout.addWidget(self.hero)
        self.rows = QWidget()
        self.rows_layout = QVBoxLayout(self.rows)
        self.rows_layout.setContentsMargins(38, 0, 0, 0)
        self.rows_layout.setSpacing(5)
        self.content_layout.addWidget(self.rows)
        self.content_layout.addStretch()
        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll, 1)

        self.refresh_button.clicked.connect(self.refresh_requested)
        self.search_box.width_changed.connect(self._position_search_box)
        self.header.installEventFilter(self)
        self.header_controls.installEventFilter(self)
        self.refresh_button.installEventFilter(self)
        self._search_position_pending = False
        self.search_box.raise_()
        self._schedule_position_search_box()

    def _schedule_position_search_box(self) -> None:
        if self._search_position_pending:
            return
        self._search_position_pending = True
        QTimer.singleShot(0, self._position_search_box)

    def _position_search_box(self) -> None:
        self._search_position_pending = False
        header_layout = self.header.layout()
        if header_layout is not None:
            header_layout.activate()
        refresh_pos = self.refresh_button.mapTo(self.header, QPoint(0, 0))
        x = refresh_pos.x() - self.search_box.width()
        y = (self.header.height() - self.search_box.height()) // 2
        self.search_box.move(max(0, x), max(0, y))
        self.search_box.show()
        self.search_box.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_position_search_box()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_position_search_box()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched in {self.header, self.header_controls, self.refresh_button} and event.type() in {
            QEvent.LayoutRequest,
            QEvent.Resize,
            QEvent.Show,
        }:
            self._schedule_position_search_box()
        return super().eventFilter(watched, event)

    def set_scanning(self, text: Optional[str], current: int = 0, total: int = 0) -> None:
        if text is None:
            self.progress_frame.hide()
            return
        self.progress_frame.show()
        self.progress_text.setText(text)
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(current)
        else:
            self.progress.setRange(0, 0)

    def rebuild(self, roots: list[str], movies: list[Movie], query: str = "") -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        collections = build_collections(movies, roots)
        words = [word.casefold() for word in query.split() if word]
        filtered = [
            collection
            for collection in collections
            if all(
                word
                in (
                    collection.title
                    + " "
                    + " ".join(movie.path for movie in collection.movies)
                ).casefold()
                for word in words
            )
        ]
        featured = max(
            filtered or collections,
            key=lambda collection: (
                collection.last_played or collection.modified
            ),
            default=None,
        )
        self.hero.set_collection(featured)

        continue_watching = sorted(
            [
                collection
                for collection in filtered
                if any(
                    movie.progress_ms > 20_000
                    and movie.duration_ms
                    and movie.progress_ms < movie.duration_ms * 0.92
                    for movie in collection.movies
                )
            ],
            key=lambda collection: collection.last_played,
            reverse=True,
        )
        if continue_watching and not words:
            self._add_collection_row(
                "Continue Watching", continue_watching
            )
        if filtered:
            self._add_collection_row(
                "Search Results" if words else "My Library",
                filtered,
            )

        if not collections or (words and not filtered):
            empty = QLabel(
                (
                    "No matching titles"
                    if words
                    else "No titles yet\n\nPut each movie or series in its own folder inside “videos”."
                )
            )
            empty.setObjectName("homeEmpty")
            empty.setAlignment(Qt.AlignCenter)
            empty.setMinimumHeight(220)
            self.rows_layout.addWidget(empty)

    def _add_collection_row(
        self, title: str, collections: list[LibraryCollection]
    ) -> None:
        row = CollectionRow(title, collections)
        row.collection_activated.connect(self.movie_activated)
        self.rows_layout.addWidget(row)


class PosterWidget(QWidget):
    def __init__(self, width: int = 230, height: int = 345) -> None:
        super().__init__()
        self.pixmap = QPixmap()
        self.setFixedSize(width, height)

    def set_cover(self, path: str) -> None:
        self.pixmap = QPixmap(path)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(self.rect(), 8, 8)
        painter.setClipPath(clip)
        draw_cover(painter, self.rect(), self.pixmap)


class CollectionPage(QWidget):
    back_requested = Signal()
    movie_activated = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.collection: Optional[LibraryCollection] = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("collectionHeader")
        header.setFixedHeight(68)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(28, 0, 28, 0)
        self.back_button = QPushButton("Back")
        self.back_button.setObjectName("collectionBack")
        self.header_title = QLabel("")
        self.header_title.setObjectName("collectionHeaderTitle")
        header_layout.addWidget(self.back_button)
        header_layout.addSpacing(16)
        header_layout.addWidget(self.header_title)
        header_layout.addStretch()
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setObjectName("collectionScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content.setObjectName("collectionContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(44, 36, 0, 50)
        content_layout.setSpacing(26)

        summary = QHBoxLayout()
        summary.setSpacing(32)
        self.poster = PosterWidget()
        summary.addWidget(self.poster)
        information = QVBoxLayout()
        information.addStretch()
        self.title = QLabel("")
        self.title.setObjectName("collectionTitle")
        self.details = QLabel("")
        self.details.setObjectName("collectionDetails")
        self.play_button = QPushButton("Play")
        self.play_button.setObjectName("heroPlay")
        self.play_button.setFixedWidth(120)
        information.addWidget(self.title)
        information.addWidget(self.details)
        information.addSpacing(14)
        information.addWidget(self.play_button)
        information.addStretch()
        summary.addLayout(information, 1)
        content_layout.addLayout(summary)

        self.episodes_layout = QVBoxLayout()
        self.episodes_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addLayout(self.episodes_layout)
        content_layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self.back_button.clicked.connect(self.back_requested)
        self.play_button.clicked.connect(self._play_representative)

    def set_collection(self, collection: LibraryCollection) -> None:
        self.collection = collection
        self.header_title.setText(collection.title)
        self.title.setText(collection.title)
        self.poster.set_cover(collection.cover)
        self.details.setText(
            f"{len(collection.movies)} episodes"
            if collection.is_series
            else format_duration(collection.representative.duration_ms)
        )
        self.play_button.setText(
            "Resume"
            if collection.representative.progress_ms > 0
            else "Play"
        )
        while self.episodes_layout.count():
            item = self.episodes_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        row = MovieRow("Episodes", collection.movies)
        row.movie_activated.connect(self.movie_activated)
        self.episodes_layout.addWidget(row)

    def _play_representative(self) -> None:
        if self.collection:
            self.movie_activated.emit(self.collection.representative)


def safe_description(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def subtitle_preference_key_for_movie(movie: Movie) -> str:
    folder = Path(movie.collection) if movie.collection else Path(movie.path).parent
    try:
        return str(folder.resolve())
    except OSError:
        return str(folder)


class MpvVideoSurface(QOpenGLWidget):
    frame_update_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.player = None
        self.render_context = None
        self._gl_proc_callback = None
        self.setAutoFillBackground(False)
        self.frame_update_requested.connect(self.update)

    def attach_player(self, player) -> None:
        self.player = player
        if self.context() is not None and self.context().isValid():
            try:
                self.makeCurrent()
                self._ensure_render_context()
            finally:
                self.doneCurrent()
        self.update()

    def detach_player(self) -> None:
        if self.render_context is not None:
            try:
                self.makeCurrent()
                self.render_context.free()
            except Exception:
                pass
            finally:
                self.render_context = None
                self.doneCurrent()
        self.player = None

    def initializeGL(self) -> None:
        self._ensure_render_context()

    def paintGL(self) -> None:
        self._ensure_render_context()
        if self.render_context is None:
            return
        scale = self.devicePixelRatioF()
        width = max(1, int(self.width() * scale))
        height = max(1, int(self.height() * scale))
        try:
            self.render_context.update()
            self.render_context.render(
                opengl_fbo={
                    "w": width,
                    "h": height,
                    "fbo": int(self.defaultFramebufferObject()),
                    "internal_format": 0,
                },
                flip_y=True,
            )
            self.render_context.report_swap()
        except Exception:
            pass

    def resizeGL(self, _width: int, _height: int) -> None:
        self.update()

    def _ensure_render_context(self) -> None:
        if self.render_context is not None or self.player is None or mpv is None:
            return
        context = QOpenGLContext.currentContext()
        if context is None:
            return

        @mpv.MpvGlGetProcAddressFn
        def get_proc_address(_ctx, name) -> int:
            active_context = QOpenGLContext.currentContext()
            if active_context is None:
                return 0
            try:
                address = active_context.getProcAddress(name)
            except TypeError:
                address = active_context.getProcAddress(name.decode("ascii"))
            if not address:
                return 0
            try:
                return int(address)
            except TypeError:
                return int(address.__int__())

        try:
            self._gl_proc_callback = get_proc_address
            self.render_context = mpv.MpvRenderContext(
                self.player,
                "opengl",
                opengl_init_params={"get_proc_address": get_proc_address},
            )
            self.render_context.update_cb = self.frame_update_requested.emit
        except Exception:
            self.render_context = None


class MpvController(QObject):
    position_changed = Signal(int, int)
    playing_changed = Signal(bool)
    ended = Signal()
    error = Signal(str)

    def __init__(self, surface: QWidget) -> None:
        super().__init__()
        self.surface = surface
        self.player = None
        self._last_playing = False
        self._ended_emitted = False
        self._generation = 0
        self._opened_at = 0.0
        self._has_media = False
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._poll)
        if mpv is not None and MPV_RUNTIME is not None:
            try:
                self.player = mpv.MPV(
                    idle=True,
                    vo="libmpv",
                    input_default_bindings=False,
                    input_vo_keyboard=False,
                    osc=False,
                    osd_level=0,
                    config=False,
                    terminal=False,
                    hwdec="auto-safe",
                    sub_auto="no",
                    sub_ass_override="no",
                    audio_display="no",
                    keep_open=False,
                )
                if hasattr(self.surface, "attach_player"):
                    self.surface.attach_player(self.player)
                self.fit_video()
            except Exception as error:
                self.error.emit(str(error))

    @property
    def available(self) -> bool:
        return self.player is not None

    def open(
        self,
        path: str,
        start_ms: int = 0,
        volume: int = 80,
    ) -> bool:
        if not self.available:
            self.error.emit("The bundled playback engine could not be loaded.")
            return False
        try:
            self._generation += 1
            generation = self._generation
            self._opened_at = time.monotonic()
            self._has_media = True
            self._ended_emitted = False
            self.player.volume = max(0, min(100, int(volume)))
            self.player.mute = False
            self.player.pause = False
            self.player.command("loadfile", str(path), "replace")
            self.fit_video()
            QTimer.singleShot(
                120,
                lambda: self._run_if_current(generation, self.fit_video),
            )
            if start_ms > 0:
                QTimer.singleShot(
                    250,
                    lambda: self._run_if_current(
                        generation, lambda: self.set_time(start_ms)
                    ),
                )
            self.timer.start()
            return True
        except Exception as error:
            self.error.emit(str(error))
            return False

    def _run_if_current(self, generation: int, action) -> None:
        if generation == self._generation and self.player is not None:
            action()

    def state(self):
        if not self.player:
            return None
        try:
            return {
                "idle": bool(self.player.core_idle),
                "paused": bool(self.player.pause),
                "eof": bool(self.player.eof_reached),
            }
        except Exception:
            return None

    def opening_age(self) -> float:
        return max(0.0, time.monotonic() - self._opened_at)

    def stopped_or_idle(self) -> bool:
        state = self.state()
        return state is None or bool(state.get("idle"))

    def is_playing(self) -> bool:
        if not self.player:
            return False
        try:
            return self._has_media and not bool(self.player.pause) and not bool(
                self.player.core_idle
            )
        except Exception:
            return False

    def fit_video(self) -> None:
        if not self.player:
            return
        for option, value in (
            ("keepaspect", "yes"),
            ("keepaspect-window", "no"),
            ("panscan", "0"),
            ("video-zoom", "0"),
            ("video-align-x", "0"),
            ("video-align-y", "0"),
            ("video-aspect-override", "no"),
            ("video-crop", "none"),
        ):
            try:
                self.player.command("set", option, value)
            except Exception:
                try:
                    setattr(self.player, option.replace("-", "_"), value)
                except Exception:
                    pass

    def stop(self) -> None:
        self._generation += 1
        self.timer.stop()
        if self.player:
            try:
                self.player.stop()
            except Exception:
                pass
        self._has_media = False
        self._opened_at = 0.0
        self._last_playing = False
        self._ended_emitted = False

    def quiet_for_close(self) -> None:
        self._generation += 1
        self.timer.stop()
        if self.player:
            try:
                self.player.pause = True
            except Exception:
                pass
            try:
                self.player.mute = True
            except Exception:
                pass

    def toggle_pause(self) -> None:
        if not self.player:
            return
        self.player.pause = not bool(self.player.pause)

    def set_time(self, milliseconds: int) -> None:
        if self.player:
            try:
                seconds = max(0, int(milliseconds)) / 1000.0
                self.player.command("seek", seconds, "absolute", "exact")
            except Exception:
                try:
                    self.player.time_pos = max(0, int(milliseconds)) / 1000.0
                except Exception:
                    pass

    def time(self) -> int:
        if not self.player:
            return 0
        try:
            return max(0, int(float(self.player.time_pos or 0) * 1000))
        except Exception:
            return 0

    def length(self) -> int:
        if not self.player:
            return 0
        try:
            return max(0, int(float(self.player.duration or 0) * 1000))
        except Exception:
            return 0

    def seek_relative(self, change_ms: int) -> None:
        self.set_time(self.time() + change_ms)

    def set_volume(self, volume: int) -> None:
        if self.player:
            self.player.volume = max(0, min(100, int(volume)))

    def set_rate(self, rate: float) -> None:
        if self.player:
            self.player.speed = max(0.25, min(4.0, float(rate)))

    def _track_description(self, track: dict) -> str:
        parts = [
            safe_description(str(track.get("title", ""))),
            safe_description(str(track.get("lang", ""))).upper(),
            safe_description(str(track.get("codec", ""))).upper(),
        ]
        label = " · ".join(part for part in parts if part and part != "UNKNOWN")
        return label or f"Track {track.get('id', '')}".strip()

    def _tracks_of_type(self, track_type: str) -> list[dict]:
        if not self.player:
            return []
        try:
            tracks = self.player.track_list or []
        except Exception:
            return []
        return [
            track
            for track in tracks
            if str(track.get("type", "")).casefold() == track_type
            and track.get("id") is not None
        ]

    def audio_tracks(self) -> list[tuple[int, str]]:
        return [
            (int(track.get("id")), self._track_description(track))
            for track in self._tracks_of_type("audio")
        ]

    def subtitle_tracks(self) -> list[tuple[int, str]]:
        return [
            (int(track.get("id")), self._track_description(track))
            for track in self._tracks_of_type("sub")
        ]

    def selected_audio(self) -> int:
        if not self.player:
            return -1
        try:
            value = self.player.aid
            return -1 if value in {None, "no", "auto"} else int(value)
        except Exception:
            return -1

    def selected_subtitle(self) -> int:
        if not self.player:
            return -1
        try:
            value = self.player.sid
            return -1 if value in {None, "no", "auto"} else int(value)
        except Exception:
            return -1

    def select_audio(self, track_id: int) -> None:
        if self.player:
            self.player.aid = "no" if int(track_id) == -1 else int(track_id)

    def select_subtitle(self, track_id: int) -> None:
        if self.player:
            self.player.sid = "no" if int(track_id) == -1 else int(track_id)

    def _poll(self) -> None:
        if not self.player:
            return
        current = self.time()
        length = self.length()
        self.position_changed.emit(current, length)
        playing = self.is_playing()
        if playing != self._last_playing:
            self._last_playing = playing
            self.playing_changed.emit(playing)
        try:
            if bool(self.player.eof_reached) and not self._ended_emitted:
                self._ended_emitted = True
                self._has_media = False
                self.ended.emit()
        except Exception:
            pass


class SeekSlider(QSlider):
    hover_position_changed = Signal(int, int)
    hover_left = Signal()
    seek_requested = Signal(int)

    def __init__(self, orientation=Qt.Horizontal, parent=None) -> None:
        super().__init__(orientation, parent)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def value_at_x(self, x: float) -> int:
        return QStyle.sliderValueFromPosition(
            self.minimum(),
            self.maximum(),
            max(0, min(self.width(), round(x))),
            max(1, self.width()),
            self.invertedAppearance(),
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        track_height = 6 if self.underMouse() else 4
        handle_radius = 8 if self.underMouse() else 7
        left = handle_radius
        right = max(left + 1, self.width() - handle_radius)
        center_y = self.height() // 2
        track = QRect(
            left,
            center_y - track_height // 2,
            right - left,
            track_height,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 115))
        painter.drawRoundedRect(track, track_height / 2, track_height / 2)
        span = max(1, self.maximum() - self.minimum())
        fraction = (self.value() - self.minimum()) / span
        handle_x = left + round(fraction * (right - left))
        played = QRect(
            left,
            center_y - track_height // 2,
            max(0, handle_x - left),
            track_height,
        )
        painter.setBrush(QColor("#e50914"))
        painter.drawRoundedRect(played, track_height / 2, track_height / 2)
        painter.drawEllipse(QPoint(handle_x, center_y), handle_radius, handle_radius)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            value = self.value_at_x(event.position().x())
            self.setSliderDown(True)
            self.setValue(value)
            self.sliderMoved.emit(value)
            self.seek_requested.emit(value)
            self.hover_position_changed.emit(value, round(event.position().x()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        value = self.value_at_x(event.position().x())
        if self.isSliderDown():
            self.setValue(value)
            self.sliderMoved.emit(value)
        self.hover_position_changed.emit(value, round(event.position().x()))
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isSliderDown():
            value = self.value_at_x(event.position().x())
            self.setValue(value)
            self.sliderMoved.emit(value)
            self.seek_requested.emit(value)
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        self.hover_left.emit()
        super().leaveEvent(event)


class DirectJumpSlider(QSlider):
    def value_at_position(self, position: QPoint) -> int:
        if self.orientation() == Qt.Vertical:
            pixel_position = self.height() - position.y()
            span = self.height()
        else:
            pixel_position = position.x()
            span = self.width()
        return QStyle.sliderValueFromPosition(
            self.minimum(),
            self.maximum(),
            max(0, min(span, round(pixel_position))),
            max(1, span),
            self.invertedAppearance(),
        )

    def _jump_to(self, position: QPoint) -> None:
        value = self.value_at_position(position)
        self.setValue(value)
        self.sliderMoved.emit(value)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.setSliderDown(True)
            self._jump_to(event.position().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.isSliderDown():
            self._jump_to(event.position().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isSliderDown():
            self._jump_to(event.position().toPoint())
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class HoverIconButton(QToolButton):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.base_icon_size = QSize(40, 40)
        self.hover_icon_size = QSize(48, 48)
        self._size_animation = QPropertyAnimation(self, b"iconSize", self)
        self._hovered = False
        self.setFixedSize(64, 56)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setIconSize(self.base_icon_size)

    def _animate_icon(
        self, target: QSize, duration: int, curve: QEasingCurve.Type
    ) -> None:
        self._size_animation.stop()
        self._size_animation.setDuration(duration)
        self._size_animation.setStartValue(self.iconSize())
        self._size_animation.setEndValue(target)
        self._size_animation.setEasingCurve(curve)
        self._size_animation.start()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.window().activateWindow()
            self.window().setFocus(Qt.MouseFocusReason)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.window().activateWindow()
            self.window().setFocus(Qt.MouseFocusReason)
        super().mouseDoubleClickEvent(event)

    def set_hovered(self, hovered: bool) -> None:
        if hovered == self._hovered:
            return
        self._hovered = hovered
        self._animate_icon(
            self.hover_icon_size if hovered else self.base_icon_size,
            140,
            QEasingCurve.InOutCubic,
        )

    def refresh_icon_size(self) -> None:
        self.setIconSize(self.hover_icon_size if self._hovered else self.base_icon_size)


class NativePlayerInputFilter(QAbstractNativeEventFilter):
    WM_LBUTTONDOWN = 0x0201
    WM_LBUTTONUP = 0x0202
    WM_LBUTTONDBLCLK = 0x0203

    def __init__(self, player: "PlayerPage") -> None:
        super().__init__()
        self.player = player

    def nativeEventFilter(self, event_type, message):
        if sys.platform != "win32":
            return False, 0
        try:
            native_message = ctypes.wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError):
            return False, 0
        if native_message.message not in {
            self.WM_LBUTTONDOWN,
            self.WM_LBUTTONUP,
            self.WM_LBUTTONDBLCLK,
        }:
            return False, 0

        client_x = ctypes.c_short(native_message.lParam & 0xFFFF).value
        client_y = ctypes.c_short(
            (native_message.lParam >> 16) & 0xFFFF
        ).value
        cursor = ctypes.wintypes.POINT(client_x, client_y)
        if not ctypes.windll.user32.ClientToScreen(
            native_message.hWnd, ctypes.byref(cursor)
        ):
            return False, 0
        global_position = QPoint(cursor.x, cursor.y)

        if native_message.message in {
            self.WM_LBUTTONDOWN,
            self.WM_LBUTTONDBLCLK,
        }:
            if self.player._dismiss_track_panel_at(global_position):
                return True, 0
            if self.player.dismiss_click_active:
                return True, 0
            button = self.player._control_button_at_global_position(
                global_position
            )
            if button is None:
                return False, 0
            self.player._begin_routed_control_press(button)
            return True, 0

        if self.player.dismiss_click_active:
            self.player.dismiss_click_active = False
            self.player._cancel_routed_control_press()
            return True, 0
        button = self.player.routed_control_press
        if button is None:
            return False, 0
        self.player._finish_routed_control_press(global_position)
        return True, 0


SKIP_BACK_RING_PATH = (
    "M11.0198 2.04817C13.3222 1.8214 15.6321 2.39998 17.5557 3.68532"
    "C19.4794 4.97067 20.8978 6.88324 21.5694 9.09718"
    "C22.241 11.3111 22.1242 13.6894 21.2388 15.8269"
    "C20.3534 17.9643 18.7543 19.7286 16.714 20.8192"
    "C14.6736 21.9098 12.3182 22.2592 10.0491 21.8079"
    "C7.77999 21.3565 5.73759 20.1323 4.26989 18.3439"
    "C2.80219 16.5555 2 14.3136 2 12L0 12"
    "C0 14.7763 0.962627 17.4666 2.72387 19.6127"
    "C4.48511 21.7588 6.93599 23.2278 9.65891 23.7694"
    "C12.3818 24.3111 15.2083 23.8918 17.6568 22.5831"
    "C20.1052 21.2744 22.0241 19.1572 23.0866 16.5922"
    "C24.149 14.0273 24.2892 11.1733 23.4833 8.51661"
    "C22.6774 5.85989 20.9752 3.56479 18.6668 2.02238"
    "C16.3585 0.479975 13.5867 -0.214319 10.8238 0.057802"
    "C8.71195 0.2658 6.70517 1.02859 5 2.2532V1H3V5"
    "C3 5.55229 3.44772 6 4 6H8V4H5.99999"
    "C7.45608 2.90793 9.19066 2.22833 11.0198 2.04817Z"
    "M2 4V7H5V9H1C0.447715 9 0 8.55229 0 8V4H2Z"
)


def build_skip_control_icon(kind: str) -> QIcon:
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.transparent)
    transform = (
        ' transform="translate(24 0) scale(-1 1)"'
        if kind == "forward10"
        else ""
    )
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<g{transform}><path fill="#ffffff" fill-rule="evenodd" '
        f'clip-rule="evenodd" d="{SKIP_BACK_RING_PATH}"/></g></svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(5, 5, 38, 38))
    font = QFont("Arial")
    font.setPixelSize(13)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(QRect(12, 16, 24, 18), Qt.AlignCenter, "10")
    painter.end()
    return QIcon(pixmap)


def build_player_control_icon(kind: str) -> QIcon:
    if kind in {"rewind10", "forward10"}:
        return build_skip_control_icon(kind)
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(1.5, 1.5)
    painter.translate(16, 16)
    painter.scale(1.18, 1.18)
    painter.translate(-16, -16)
    pen = QPen(QColor("#ffffff"), 2.2)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    if kind == "back":
        painter.drawLine(19, 9, 11, 16)
        painter.drawLine(11, 16, 19, 23)
        painter.drawLine(11, 16, 29, 16)
    elif kind == "play":
        path = QPainterPath()
        path.moveTo(11, 7)
        path.lineTo(25, 16)
        path.lineTo(11, 25)
        path.closeSubpath()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawPath(path)
    elif kind == "pause":
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(9, 7, 5, 18, 1, 1)
        painter.drawRoundedRect(18, 7, 5, 18, 1, 1)
    elif kind in {"volume", "muted"}:
        path = QPainterPath()
        path.moveTo(5, 13)
        path.lineTo(11, 13)
        path.lineTo(18, 7)
        path.lineTo(18, 25)
        path.lineTo(11, 19)
        path.lineTo(5, 19)
        path.closeSubpath()
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        detail_pen = QPen(QColor("#ffffff"), 1.45)
        detail_pen.setCapStyle(Qt.RoundCap)
        detail_pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(detail_pen)
        if kind == "muted":
            mute_pen = QPen(QColor("#ffffff"), 1.45)
            mute_pen.setCapStyle(Qt.FlatCap)
            mute_pen.setJoinStyle(Qt.MiterJoin)
            painter.setPen(mute_pen)
            painter.drawLine(22, 14, 27, 19)
            painter.drawLine(27, 14, 22, 19)
        else:
            waves = QPainterPath()
            waves.moveTo(21, 12)
            waves.cubicTo(23.5, 14, 23.5, 18, 21, 20)
            waves.moveTo(23, 9.5)
            waves.cubicTo(27.5, 12.5, 27.5, 19.5, 23, 22.5)
            painter.drawPath(waves)
    elif kind == "settings":
        painter.drawEllipse(QRect(9, 9, 14, 14))
        painter.drawEllipse(QRect(13, 13, 6, 6))
        for x1, y1, x2, y2 in (
            (16, 4, 16, 9),
            (16, 23, 16, 28),
            (4, 16, 9, 16),
            (23, 16, 28, 16),
            (7, 7, 11, 11),
            (21, 21, 25, 25),
            (25, 7, 21, 11),
            (11, 21, 7, 25),
        ):
            painter.drawLine(x1, y1, x2, y2)
    elif kind == "captions":
        painter.drawRoundedRect(QRect(4, 7, 24, 17), 2, 2)
        painter.drawLine(10, 24, 8, 28)
        painter.drawLine(8, 28, 15, 24)
        painter.drawLine(9, 13, 15, 13)
        painter.drawLine(18, 13, 23, 13)
        painter.drawLine(9, 18, 14, 18)
        painter.drawLine(17, 18, 23, 18)
    elif kind == "check":
        painter.setPen(QPen(QColor("#ffffff"), 2.8))
        painter.drawLine(7, 16, 13, 22)
        painter.drawLine(13, 22, 25, 9)
    elif kind in {"fullscreen", "windowed"}:
        if kind == "fullscreen":
            segments = (
                (6, 13, 6, 6, 13, 6),
                (19, 6, 26, 6, 26, 13),
                (6, 19, 6, 26, 13, 26),
                (19, 26, 26, 26, 26, 19),
            )
        else:
            segments = (
                (13, 6, 13, 13, 6, 13),
                (19, 6, 19, 13, 26, 13),
                (13, 26, 13, 19, 6, 19),
                (19, 26, 19, 19, 26, 19),
            )
        for x1, y1, x2, y2, x3, y3 in segments:
            painter.drawLine(x1, y1, x2, y2)
            painter.drawLine(x2, y2, x3, y3)
    painter.end()
    return QIcon(pixmap)


def set_player_button_icon(button: QToolButton, kind: str) -> None:
    button.setText("")
    button.setIcon(build_player_control_icon(kind))
    if isinstance(button, HoverIconButton):
        button.refresh_icon_size()
    else:
        button.setIconSize(QSize(40, 40))


class PlayerPage(QWidget):
    back_requested = Signal()
    progress_saved = Signal(object, int, bool)
    settings_changed = Signal()

    def __init__(
        self,
        store: DordieWatchStore,
        settings: dict,
    ) -> None:
        super().__init__()
        self.store = store
        self.settings = settings
        self.movie: Optional[Movie] = None
        self.selected_subtitle: int = -1
        self.subtitle_preference_applied = False
        self.playback_token = 0
        self.playback_started_at = 0.0
        self.close_started_at = 0.0
        self.close_pending = False
        self.seeking = False
        self.last_progress_save = 0.0
        self.controls_visible = True
        self.controls_animating = False
        self.control_animation: Optional[QParallelAnimationGroup] = None
        self.menu_open = False
        self.track_panel: Optional[QFrame] = None
        self.routed_control_press: Optional[HoverIconButton] = None
        self.dismiss_click_active = False
        self.ignore_click_release = False
        self.control_hover_widgets: tuple[QWidget, ...] = ()
        self.last_subtitle_selection: int = -1
        self.last_nonzero_volume = max(1, int(settings.get("volume", 80)))
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self.overlay = QWidget(self)
        self.overlay.setObjectName("playerOverlay")
        self.overlay.setAttribute(Qt.WA_TranslucentBackground, True)
        self.overlay.setAutoFillBackground(False)
        self.overlay.setMouseTracking(True)
        self.overlay.setFocusPolicy(Qt.StrongFocus)
        self.overlay.installEventFilter(self)
        self.overlay.hide()

        self.video_surface = MpvVideoSurface(self)
        self.video_surface.setObjectName("videoSurface")
        self.video_surface.setMouseTracking(True)
        self.video_surface.installEventFilter(self)
        self.controller = MpvController(self.video_surface)
        self.controller.position_changed.connect(self._position_changed)
        self.controller.playing_changed.connect(self._playing_changed)
        self.controller.ended.connect(self._ended)
        self.controller.error.connect(self._show_error)

        self.top_bar = QFrame(self.overlay)
        self.top_bar.setObjectName("playerTop")
        self.top_bar.setMouseTracking(True)
        self.top_bar.installEventFilter(self)
        self.top_opacity = QGraphicsOpacityEffect(self.top_bar)
        self.top_opacity.setOpacity(1.0)
        self.top_bar.setGraphicsEffect(self.top_opacity)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(18, 18, 18, 18)
        self.back_button = HoverIconButton()
        self.back_button.setObjectName("playerIcon")
        set_player_button_icon(self.back_button, "back")
        self.back_button.setToolTip("Back (Esc)")
        self.title = QLabel("")
        self.title.setObjectName("playerTitle")
        top_layout.addWidget(self.back_button)
        top_layout.addStretch()
        self.back_button.clicked.connect(self.close_player)

        self.bottom_bar = QFrame(self.overlay)
        self.bottom_bar.setObjectName("playerBottom")
        self.bottom_bar.setMouseTracking(True)
        self.bottom_bar.installEventFilter(self)
        self.bottom_opacity = QGraphicsOpacityEffect(self.bottom_bar)
        self.bottom_opacity.setOpacity(1.0)
        self.bottom_bar.setGraphicsEffect(self.bottom_opacity)
        bottom_layout = QVBoxLayout(self.bottom_bar)
        bottom_layout.setContentsMargins(20, 4, 20, 8)
        bottom_layout.setSpacing(8)
        self.timeline = SeekSlider(Qt.Horizontal)
        self.timeline.setObjectName("timeline")
        self.timeline.setRange(0, 0)
        self.timeline.setMinimumHeight(26)
        self.timeline.sliderPressed.connect(lambda: setattr(self, "seeking", True))
        self.timeline.sliderMoved.connect(self._seek_preview)
        self.timeline.sliderReleased.connect(self._seek_released)
        self.timeline.seek_requested.connect(self._timeline_seek_requested)
        self.timeline.hover_position_changed.connect(self._show_seek_tooltip)
        self.timeline.hover_left.connect(self._hide_seek_tooltip)
        self.time_label = QLabel("0:00")
        self.time_label.setObjectName("playerTime")
        progress_layout = QHBoxLayout()
        progress_layout.setSpacing(10)
        progress_layout.addWidget(self.timeline, 1)
        progress_layout.addWidget(self.time_label)
        bottom_layout.addLayout(progress_layout)
        controls = QHBoxLayout()
        controls.setSpacing(0)
        left_controls = QHBoxLayout()
        left_controls.setSpacing(12)
        right_controls = QHBoxLayout()
        right_controls.setSpacing(12)
        right_controls.addStretch()
        self.play_button = HoverIconButton()
        self.play_button.setObjectName("playerIcon")
        set_player_button_icon(self.play_button, "play")
        self.play_button.setToolTip("Play (K)")
        self.rewind_button = HoverIconButton()
        self.rewind_button.setObjectName("playerIcon")
        set_player_button_icon(self.rewind_button, "rewind10")
        self.rewind_button.setToolTip("Back 10 seconds (J)")
        self.forward_button = HoverIconButton()
        self.forward_button.setObjectName("playerIcon")
        set_player_button_icon(self.forward_button, "forward10")
        self.forward_button.setToolTip("Forward 10 seconds (L)")
        self.volume_button = HoverIconButton()
        self.volume_button.setObjectName("playerIcon")
        self.volume_button.setToolTip("Mute (M)")
        self.volume = DirectJumpSlider(Qt.Vertical)
        self.volume.setObjectName("volumeSliderVertical")
        self.volume.setRange(0, 100)
        self.volume.setFixedSize(22, 168)
        self.volume.setValue(int(settings.get("volume", 80)))
        self.settings_button = HoverIconButton()
        self.settings_button.setObjectName("playerIcon")
        set_player_button_icon(self.settings_button, "captions")
        self.settings_button.setToolTip("Audio and subtitles")
        self.fullscreen_button = HoverIconButton()
        self.fullscreen_button.setObjectName("playerIcon")
        set_player_button_icon(self.fullscreen_button, "fullscreen")
        self.fullscreen_button.setToolTip("Fullscreen (F)")
        left_controls.addWidget(self.play_button)
        left_controls.addWidget(self.rewind_button)
        left_controls.addWidget(self.forward_button)
        left_controls.addWidget(self.volume_button)
        left_controls.addStretch()
        right_controls.addWidget(self.settings_button)
        right_controls.addWidget(self.fullscreen_button)
        controls.addLayout(left_controls, 1)
        controls.addWidget(self.title, 0, Qt.AlignCenter)
        controls.addLayout(right_controls, 1)
        bottom_layout.addLayout(controls)

        self.volume_popup = QFrame(self.overlay)
        self.volume_popup.setObjectName("volumePopup")
        self.volume_popup.setFixedSize(36, 200)
        volume_popup_layout = QVBoxLayout(self.volume_popup)
        volume_popup_layout.setContentsMargins(7, 16, 7, 16)
        volume_popup_layout.addWidget(self.volume, 1, Qt.AlignHCenter)
        self.volume_popup.hide()

        self.seek_preview = QFrame(self.overlay)
        self.seek_preview.setObjectName("seekPreview")
        seek_preview_layout = QVBoxLayout(self.seek_preview)
        seek_preview_layout.setContentsMargins(4, 4, 4, 5)
        seek_preview_layout.setSpacing(3)
        self.seek_preview_image = QLabel()
        self.seek_preview_image.setObjectName("seekPreviewImage")
        self.seek_preview_image.setFixedSize(176, 99)
        self.seek_preview_image.setAlignment(Qt.AlignCenter)
        self.seek_tooltip = QLabel("")
        self.seek_tooltip.setObjectName("seekTooltip")
        self.seek_tooltip.setAlignment(Qt.AlignCenter)
        seek_preview_layout.addWidget(self.seek_preview_image)
        seek_preview_layout.addWidget(self.seek_tooltip)
        self.seek_preview.hide()
        self.feedback = QLabel("", self.overlay)
        self.feedback.setObjectName("playerFeedback")
        self.feedback.setAlignment(Qt.AlignCenter)
        self.feedback.hide()
        self.icon_feedback = QLabel("", self.overlay)
        self.icon_feedback.setObjectName("playerIconFeedback")
        self.icon_feedback.setAlignment(Qt.AlignCenter)
        self.icon_feedback.setFixedSize(88, 88)
        self.icon_feedback_opacity = QGraphicsOpacityEffect(self.icon_feedback)
        self.icon_feedback_opacity.setOpacity(0.0)
        self.icon_feedback.setGraphicsEffect(self.icon_feedback_opacity)
        self.icon_feedback_animation = QPropertyAnimation(
            self.icon_feedback_opacity, b"opacity", self
        )
        self.icon_feedback_animation.setStartValue(0.0)
        self.icon_feedback_animation.setKeyValueAt(0.22, 1.0)
        self.icon_feedback_animation.setKeyValueAt(0.65, 1.0)
        self.icon_feedback_animation.setEndValue(0.0)
        self.icon_feedback_animation.setEasingCurve(QEasingCurve.InOutSine)
        self.icon_feedback_animation.finished.connect(self.icon_feedback.hide)
        self.icon_feedback.hide()
        self.toast = QLabel("", self.overlay)
        self.toast.setObjectName("playerToast")
        self.toast.setAlignment(Qt.AlignCenter)
        self.toast.hide()
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.setInterval(1100)
        self.hide_timer.timeout.connect(self._hide_controls)
        self.click_timer = QTimer(self)
        self.click_timer.setSingleShot(True)
        self.click_timer.setInterval(180)
        self.click_timer.timeout.connect(self._toggle_playback)
        self.feedback_timer = QTimer(self)
        self.feedback_timer.setSingleShot(True)
        self.feedback_timer.timeout.connect(self.feedback.hide)
        self.toast_timer = QTimer(self)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.timeout.connect(self.toast.hide)
        self.hover_buttons = (
            self.back_button,
            self.play_button,
            self.rewind_button,
            self.forward_button,
            self.volume_button,
            self.settings_button,
            self.fullscreen_button,
        )
        self.pointer_timer = QTimer(self)
        self.pointer_timer.setInterval(15)
        self.pointer_timer.timeout.connect(self._poll_pointer)
        self.pointer_left_down = False
        self.pointer_timer.start()
        self.last_cursor_position = QCursor.pos()
        self.volume_popup_timer = QTimer(self)
        self.volume_popup_timer.setSingleShot(True)
        self.volume_popup_timer.setInterval(450)
        self.volume_popup_timer.timeout.connect(self.volume_popup.hide)
        self.routed_press_timer = QTimer(self)
        self.routed_press_timer.setSingleShot(True)
        self.routed_press_timer.setInterval(1200)
        self.routed_press_timer.timeout.connect(self._cancel_routed_control_press)
        self.play_button.clicked.connect(self._toggle_playback)
        self.rewind_button.clicked.connect(lambda: self._seek_by(-10_000))
        self.forward_button.clicked.connect(lambda: self._seek_by(10_000))
        self.volume_button.clicked.connect(self._toggle_mute)
        self.volume.valueChanged.connect(self._volume_changed)
        self.settings_button.clicked.connect(self.open_settings_menu)
        self.fullscreen_button.clicked.connect(self._toggle_fullscreen)
        self._update_volume_icon(self.volume.value())
        self.control_hover_widgets = (
            self.top_bar,
            self.bottom_bar,
            self.back_button,
            self.title,
            self.timeline,
            self.play_button,
            self.rewind_button,
            self.forward_button,
            self.volume_button,
            self.volume_popup,
            self.volume,
            self.time_label,
            self.settings_button,
            self.fullscreen_button,
        )
        for widget in self.control_hover_widgets:
            widget.setMouseTracking(True)
            widget.installEventFilter(self)
        self.native_input_filter = None

    def play_movie(self, movie: Movie) -> None:
        self._close_track_panel()
        self.playback_token += 1
        playback_token = self.playback_token
        self.close_pending = False
        self.back_button.setEnabled(True)
        self.movie = movie
        self.title.setText(movie.title)
        self.selected_subtitle = -1
        self.subtitle_preference_applied = False
        self._sync_video_surface_geometry()
        self.timeline.setRange(0, max(0, movie.duration_ms))
        self.timeline.setValue(movie.progress_ms if not movie.completed else 0)
        set_player_button_icon(self.play_button, "pause")
        self.play_button.setToolTip("Pause (K)")
        self.playback_started_at = time.monotonic()
        self.controller.open(
            movie.path,
            movie.progress_ms if not movie.completed else 0,
            int(self.settings.get("volume", 80)),
        )
        for delay in (120, 300, 700, 1200):
            QTimer.singleShot(
                delay,
                lambda token=playback_token: self._run_for_playback(
                    token, self._apply_saved_subtitle_preference
                ),
            )
        self._sync_overlay_geometry()
        self.overlay.show()
        self.overlay.raise_()
        self._restore_overlay_input(force=True)
        self._queue_overlay_input_restore()
        self._show_controls()

    def _run_for_playback(self, token: int, action) -> None:
        if (
            token == self.playback_token
            and self.movie is not None
            and not self.close_pending
        ):
            action()

    def close_player(self) -> None:
        if self.close_pending or self.movie is None:
            return
        self.close_pending = True
        self.playback_token += 1
        self.back_button.setEnabled(False)
        self._close_track_panel()
        if self.movie:
            current = self.controller.time()
            length = self.controller.length() or self.movie.duration_ms
            completed = bool(length and current >= length * 0.92)
            self.progress_saved.emit(self.movie, current, completed)
        self.click_timer.stop()
        self.hide_timer.stop()
        self.volume_popup_timer.stop()
        self.routed_press_timer.stop()
        self._cancel_routed_control_press()
        self._hide_seek_tooltip()
        self.setCursor(Qt.ArrowCursor)
        self.video_surface.setCursor(Qt.ArrowCursor)
        self.overlay.setCursor(Qt.ArrowCursor)
        self._update_icon_hovers(None)
        self.overlay.setEnabled(False)
        self.close_started_at = time.monotonic()
        self.controller.quiet_for_close()
        QTimer.singleShot(80, self._stop_playback_for_close)

    def _stop_playback_for_close(self) -> None:
        if not self.close_pending:
            return
        elapsed = max(0.0, time.monotonic() - self.close_started_at)
        if self.controller.is_playing() and elapsed < 1.2:
            self.controller.quiet_for_close()
            QTimer.singleShot(80, self._stop_playback_for_close)
            return
        self.controller.stop()
        QTimer.singleShot(80, self._finish_close_when_safe)

    def _finish_close_when_safe(self) -> None:
        if not self.close_pending:
            return
        elapsed = max(0.0, time.monotonic() - self.close_started_at)
        if not self.controller.stopped_or_idle() and elapsed < 1.6:
            QTimer.singleShot(80, self._finish_close_when_safe)
            return
        window = self.window()
        if window.isFullScreen():
            window.showNormal()
            set_player_button_icon(self.fullscreen_button, "fullscreen")
            self.fullscreen_button.setToolTip("Fullscreen (F)")
            QApplication.processEvents()
        self.overlay.hide()
        self.overlay.setEnabled(True)
        self.movie = None
        self.video_surface.setGeometry(self.rect())
        self.close_pending = False
        self.back_button.setEnabled(True)
        self.back_requested.emit()

    def resizeEvent(self, event) -> None:
        self._sync_video_surface_geometry()
        self._sync_overlay_geometry()
        self.video_surface.lower()
        super().resizeEvent(event)

    def begin_interactive_resize(self) -> None:
        self._sync_video_surface_geometry()

    def end_interactive_resize(self) -> None:
        self._settle_video_layout()

    def _settle_video_layout(self) -> None:
        self._sync_video_surface_geometry()
        self._sync_overlay_geometry()
        self.controller.fit_video()

    def _sync_video_surface_geometry(self) -> None:
        target = self.rect()
        if self.video_surface.geometry() != target:
            self.video_surface.setGeometry(target)
        self.video_surface.lower()

    def _sync_overlay_geometry(self) -> None:
        if not hasattr(self, "overlay") or not hasattr(self, "top_bar"):
            return
        target = QRect(0, 0, self.width(), self.height())
        if self.overlay.geometry() != target:
            self.overlay.setGeometry(target)
        self.top_bar.resize(self.overlay.width(), 96)
        self.bottom_bar.resize(self.overlay.width(), 108)
        if not self.controls_animating:
            self.top_bar.move(0, 0 if self.controls_visible else -96)
            self.bottom_bar.move(
                0,
                (
                    self.overlay.height() - 108
                    if self.controls_visible
                    else self.overlay.height()
                ),
            )
        self.toast.adjustSize()
        self.toast.move(
            (self.overlay.width() - self.toast.width()) // 2,
            max(90, self.overlay.height() - 190),
        )
        self.feedback.adjustSize()
        self.feedback.move(
            (self.overlay.width() - self.feedback.width()) // 2,
            (self.overlay.height() - self.feedback.height()) // 2,
        )
        self.icon_feedback.move(
            (self.overlay.width() - self.icon_feedback.width()) // 2,
            (self.overlay.height() - self.icon_feedback.height()) // 2,
        )
        self.top_bar.raise_()
        self.bottom_bar.raise_()
        if self.track_panel and self.track_panel.isVisible():
            self._position_track_panel()
            self.track_panel.raise_()
        if self.volume_popup.isVisible():
            self.volume_popup.raise_()
        self._position_volume_popup()
        self.volume_popup.raise_()
        self.seek_preview.raise_()
        self.feedback.raise_()
        self.icon_feedback.raise_()
        self.toast.raise_()

    def _position_volume_popup(self) -> None:
        self.volume_popup.adjustSize()
        anchor = self.volume_button.mapTo(self.overlay, QPoint(0, 0))
        self.volume_popup.move(
            anchor.x()
            + (self.volume_button.width() - self.volume_popup.width()) // 2,
            anchor.y() - self.volume_popup.height() - 6,
        )

    def _show_volume_popup(self) -> None:
        if not self.controls_visible:
            self._show_controls(keep=True)
        self._position_volume_popup()
        self.volume_popup.show()
        self.volume_popup.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.MouseButtonPress
            and event.button() == Qt.LeftButton
            and self._dismiss_track_panel_for_event(watched, event)
        ):
            event.accept()
            return True
        fallback_surfaces = {
            getattr(self, "overlay", None),
            getattr(self, "top_bar", None),
            getattr(self, "bottom_bar", None),
            getattr(self, "title", None),
            getattr(self, "time_label", None),
        }
        if (
            watched in fallback_surfaces
            and event.type() == QEvent.MouseButtonPress
            and event.button() == Qt.LeftButton
        ):
            button = self._control_button_at_global_position(
                event.globalPosition().toPoint()
            )
            if button is not None:
                self._begin_routed_control_press(button)
                event.accept()
                return True
        if (
            event.type() == QEvent.MouseButtonRelease
            and event.button() == Qt.LeftButton
            and self.routed_control_press is not None
        ):
            global_position = event.globalPosition().toPoint()
            self._finish_routed_control_press(global_position)
            event.accept()
            return True
        video_area = watched in {
            getattr(self, "video_surface", None),
            getattr(self, "overlay", None),
        }
        if (
            event.type() == QEvent.KeyPress
            and watched is getattr(self, "overlay", None)
        ):
            self.keyPressEvent(event)
            return True
        volume_widgets = {
            getattr(self, "volume_button", None),
            getattr(self, "volume_popup", None),
            getattr(self, "volume", None),
        }
        if watched in volume_widgets:
            if event.type() in {QEvent.Enter, QEvent.MouseMove, QEvent.HoverMove}:
                self.volume_popup_timer.stop()
                self._show_volume_popup()
            elif event.type() == QEvent.Leave:
                self.volume_popup_timer.start()
        if watched in self.control_hover_widgets and event.type() in {
            QEvent.MouseMove,
            QEvent.Enter,
            QEvent.HoverMove,
        }:
            self._show_controls(keep=True)
        if video_area and event.type() in {
            QEvent.MouseMove,
            QEvent.Enter,
        }:
            self._show_controls()
        if video_area and event.type() == QEvent.MouseButtonPress:
            self.overlay.setFocus(Qt.MouseFocusReason)
            self._show_controls()
            if self.track_panel and self.track_panel.isVisible():
                self.ignore_click_release = True
                self._close_track_panel()
                return True
        if video_area and event.type() == QEvent.MouseButtonRelease:
            if event.button() == Qt.LeftButton:
                if self.ignore_click_release:
                    self.ignore_click_release = False
                self._show_controls()
                return True
        if video_area and event.type() == QEvent.Leave:
            self._hide_seek_tooltip()
        if video_area and event.type() == QEvent.MouseButtonPress:
            return True
        return super().eventFilter(watched, event)

    def _control_button_at_global_position(
        self, global_position: QPoint
    ) -> Optional[HoverIconButton]:
        if (
            not self.movie
            or not self.overlay.isVisible()
            or not self.controls_visible
        ):
            return None
        for button in getattr(self, "hover_buttons", ()):
            if (
                button.isVisible()
                and button.isEnabled()
                and button.rect().contains(button.mapFromGlobal(global_position))
            ):
                return button
        return None

    def _cancel_routed_control_press(self) -> None:
        button = self.routed_control_press
        self.routed_control_press = None
        self.routed_press_timer.stop()
        if button is not None:
            button.setDown(False)

    def _begin_routed_control_press(self, button: HoverIconButton) -> None:
        self._cancel_routed_control_press()
        self.routed_control_press = button
        button.setDown(True)
        self.routed_press_timer.start()

    def _finish_routed_control_press(self, global_position: QPoint) -> None:
        button = self.routed_control_press
        self.routed_control_press = None
        self.routed_press_timer.stop()
        if button is None:
            return
        button.setDown(False)
        if button.rect().contains(button.mapFromGlobal(global_position)):
            QTimer.singleShot(0, button.click)

    def mouseMoveEvent(self, event) -> None:
        self._show_controls()
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if event.isAutoRepeat() and key in {
            Qt.Key_Space,
            Qt.Key_K,
            Qt.Key_F,
            Qt.Key_M,
            Qt.Key_C,
        }:
            event.accept()
            return
        handled = True
        if key in {Qt.Key_Space, Qt.Key_K}:
            self._toggle_playback()
        elif key == Qt.Key_Left:
            self._seek_by(-10_000)
        elif key == Qt.Key_Right:
            self._seek_by(10_000)
        elif key == Qt.Key_J:
            self._seek_by(-10_000)
        elif key == Qt.Key_L:
            self._seek_by(10_000)
        elif event.key() == Qt.Key_Up:
            self.volume.setValue(min(100, self.volume.value() + 5))
            self._show_feedback(f"Volume {self.volume.value()}%")
        elif event.key() == Qt.Key_Down:
            self.volume.setValue(max(0, self.volume.value() - 5))
            self._show_feedback(f"Volume {self.volume.value()}%")
        elif key == Qt.Key_M:
            self._toggle_mute()
        elif key == Qt.Key_F:
            self._toggle_fullscreen()
        elif key == Qt.Key_C:
            self._toggle_captions()
        elif Qt.Key_0 <= key <= Qt.Key_9:
            self._seek_fraction((key - Qt.Key_0) / 10.0)
        elif key == Qt.Key_Home:
            self._seek_fraction(0)
        elif key == Qt.Key_End:
            self._seek_fraction(1)
        elif key == Qt.Key_Escape:
            window = self.window()
            if self.track_panel and self.track_panel.isVisible():
                self._close_track_panel()
            elif window.isFullScreen():
                window.showNormal()
                set_player_button_icon(self.fullscreen_button, "fullscreen")
                self.fullscreen_button.setToolTip("Fullscreen (F)")
            else:
                self.close_player()
        else:
            handled = False
            super().keyPressEvent(event)
        if handled:
            event.accept()
            self._show_controls()

    def _position_changed(self, current: int, length: int) -> None:
        if length > 0:
            self.timeline.setMaximum(length)
            if self.movie and self.movie.duration_ms != length:
                self.movie.duration_ms = length
        if not self.seeking:
            self.timeline.setValue(current)
            self.time_label.setText(format_duration(length))
        if self.movie and time.monotonic() - self.last_progress_save > 5:
            self.last_progress_save = time.monotonic()
            self.progress_saved.emit(self.movie, current, False)

    def _playing_changed(self, playing: bool) -> None:
        set_player_button_icon(self.play_button, "pause" if playing else "play")
        self.play_button.setToolTip("Pause (K)" if playing else "Play (K)")
        if playing:
            self.hide_timer.start()
        else:
            self._show_controls(keep=True)

    def _toggle_playback(self) -> None:
        playing = self.controller.is_playing()
        self.controller.toggle_pause()
        will_play = not playing
        set_player_button_icon(self.play_button, "pause" if will_play else "play")
        self.play_button.setToolTip("Pause (K)" if will_play else "Play (K)")
        self._show_feedback_icon("play" if will_play else "pause")
        self._show_controls(keep=not will_play)

    def _seek_by(self, change_ms: int) -> None:
        current = self.controller.time()
        length = self.controller.length() or self.timeline.maximum()
        target = max(0, min(length, current + change_ms)) if length else max(
            0, current + change_ms
        )
        self.controller.set_time(target)
        self.timeline.setValue(target)
        self.time_label.setText(format_duration(length))
        if abs(change_ms) != 10_000:
            self._show_feedback(f"{change_ms // 1000:+d}s")
        self._show_controls()

    def _seek_fraction(self, fraction: float) -> None:
        length = self.controller.length() or self.timeline.maximum()
        if length <= 0:
            return
        target = round(max(0.0, min(1.0, fraction)) * length)
        self.controller.set_time(target)
        self.timeline.setValue(target)
        self.time_label.setText(format_duration(length))
        self._show_feedback(format_duration(target))

    def _seek_preview(self, value: int) -> None:
        self.seeking = True
        length = self.controller.length() or self.timeline.maximum()
        self.time_label.setText(format_duration(length))
        self._show_controls()

    def _timeline_seek_requested(self, value: int) -> None:
        self.seeking = False
        self.controller.set_time(value)
        length = self.controller.length() or self.timeline.maximum()
        self.time_label.setText(format_duration(length))

    def _seek_released(self) -> None:
        self.seeking = False
        self.controller.set_time(self.timeline.value())
        self._show_controls()

    def _show_seek_tooltip(self, value: int, slider_x: int) -> None:
        self.seek_tooltip.setText(format_duration(value))
        frames = self.movie.preview_frames if self.movie else ()
        if frames:
            maximum = max(1, self.timeline.maximum())
            frame_index = min(
                len(frames) - 1,
                max(0, round((value / maximum) * (len(frames) - 1))),
            )
            pixmap = QPixmap(frames[frame_index])
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self.seek_preview_image.size(),
                    Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation,
                )
                x_offset = max(
                    0, (scaled.width() - self.seek_preview_image.width()) // 2
                )
                y_offset = max(
                    0, (scaled.height() - self.seek_preview_image.height()) // 2
                )
                self.seek_preview_image.setPixmap(
                    scaled.copy(
                        x_offset,
                        y_offset,
                        self.seek_preview_image.width(),
                        self.seek_preview_image.height(),
                    )
                )
                self.seek_preview_image.show()
            else:
                self.seek_preview_image.hide()
        else:
            self.seek_preview_image.hide()
        self.seek_preview.adjustSize()
        point = self.timeline.mapTo(self.overlay, QPoint(slider_x, 0))
        x = max(
            8,
            min(
                self.overlay.width() - self.seek_preview.width() - 8,
                point.x() - self.seek_preview.width() // 2,
            ),
        )
        y = point.y() - self.seek_preview.height() - 8
        self.seek_preview.move(x, y)
        self.seek_preview.show()
        self.seek_preview.raise_()
        self._show_controls()

    def _hide_seek_tooltip(self) -> None:
        self.seek_preview.hide()

    def _volume_changed(self, value: int) -> None:
        self.controller.set_volume(value)
        if value > 0:
            self.last_nonzero_volume = value
        self._update_volume_icon(value)
        self.settings["volume"] = value
        self.settings_changed.emit()

    def _update_volume_icon(self, value: int) -> None:
        set_player_button_icon(
            self.volume_button, "muted" if value == 0 else "volume"
        )
        self.volume_button.setToolTip("Unmute (M)" if value == 0 else "Mute (M)")

    def _toggle_mute(self) -> None:
        if self.volume.value() > 0:
            self.last_nonzero_volume = self.volume.value()
            self.volume.setValue(0)
            self._show_feedback("Muted")
        else:
            self.volume.setValue(self.last_nonzero_volume)
            self._show_feedback(f"Volume {self.volume.value()}%")
        self._show_controls()

    def _toggle_captions(self) -> None:
        if self.controller.selected_subtitle() != -1:
            self._select_subtitle(-1)
            return
        selection = self.last_subtitle_selection
        available_tracks = self.controller.subtitle_tracks()
        if selection != -1 and any(track_id == selection for track_id, _ in available_tracks):
            self._select_subtitle(selection)
            return
        if available_tracks:
            self._select_subtitle(available_tracks[0][0])

    def _ended(self) -> None:
        if self.movie:
            self.progress_saved.emit(
                self.movie, self.movie.duration_ms or self.controller.length(), True
            )
        self.close_player()

    def _show_controls(self, keep: bool = False) -> None:
        self.hide_timer.stop()
        was_visible = self.controls_visible
        if self.movie:
            self._sync_overlay_geometry()
            self.overlay.show()
            self.overlay.raise_()
        self.controls_visible = True
        self.top_bar.show()
        self.bottom_bar.show()
        if not was_visible:
            self._animate_controls(True)
        elif self.controls_animating:
            pass
        elif self.top_opacity.opacity() < 0.99:
            self._animate_controls(True)
        else:
            self.top_bar.move(0, 0)
            self.bottom_bar.move(0, self.overlay.height() - self.bottom_bar.height())
            self.top_opacity.setOpacity(1.0)
            self.bottom_opacity.setOpacity(1.0)
        self.top_bar.raise_()
        self.bottom_bar.raise_()
        if self.track_panel and self.track_panel.isVisible():
            self.track_panel.raise_()
        if self.volume_popup.isVisible():
            self._position_volume_popup()
            self.volume_popup.raise_()
        if self.seek_preview.isVisible():
            self.seek_preview.raise_()
        if self.feedback.isVisible():
            self.feedback.raise_()
        if self.icon_feedback.isVisible():
            self.icon_feedback.raise_()
        if self.toast.isVisible():
            self.toast.raise_()
        self.setCursor(Qt.ArrowCursor)
        self.video_surface.setCursor(Qt.ArrowCursor)
        self.overlay.setCursor(Qt.ArrowCursor)
        if not keep and self.controller.is_playing():
            self.hide_timer.start()

    def _cursor_in_controls_zone(self) -> bool:
        local = self.mapFromGlobal(QCursor.pos())
        return self.rect().contains(local) and (
            local.y() <= 95 or local.y() >= self.height() - 155
        )

    def _poll_pointer(self) -> None:
        if self.movie and self.isVisible():
            self._sync_overlay_geometry()
        position = QCursor.pos()
        self._poll_control_press(position)
        moved = position != self.last_cursor_position
        self.last_cursor_position = position
        self._update_icon_hovers(
            position
            if self.isVisible() and self.movie and self.controls_visible
            else None
        )
        volume_hovered = (
            self.controls_visible
            and self.volume_button.isVisible()
            and self.volume_button.rect().contains(
                self.volume_button.mapFromGlobal(position)
            )
        )
        if volume_hovered:
            self.volume_popup_timer.stop()
            self._show_volume_popup()
        elif (
            self.volume_popup.isVisible()
            and not self.volume_popup.underMouse()
            and not self.volume_popup_timer.isActive()
        ):
            self.volume_popup_timer.start()
        if not self.isVisible() or not self.movie:
            return
        local = self.mapFromGlobal(position)
        if not self.rect().contains(local):
            return
        in_controls_zone = (
            local.y() <= 95 or local.y() >= self.height() - 155
        )
        if moved or in_controls_zone or not self.controls_visible:
            if moved or in_controls_zone:
                self._show_controls(keep=in_controls_zone)

    def _poll_control_press(self, position: QPoint) -> None:
        if sys.platform != "win32":
            return
        try:
            left_down = bool(
                ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000
            )
        except Exception:
            return

        if self.dismiss_click_active:
            self.pointer_left_down = left_down
            self._cancel_routed_control_press()
            if not left_down:
                self.dismiss_click_active = False
            return

        if not self.movie or not self.isVisible() or not self._application_owns_foreground():
            self.pointer_left_down = left_down
            if self.routed_control_press is not None:
                self._cancel_routed_control_press()
            return

        if left_down and not self.pointer_left_down:
            if self._dismiss_track_panel_at(position):
                self.pointer_left_down = True
                return
            button = self._control_button_at_global_position(position)
            if button is not None:
                self._begin_routed_control_press(button)
        elif (
            not left_down
            and self.pointer_left_down
            and self.routed_control_press is not None
        ):
            self._finish_routed_control_press(position)
        self.pointer_left_down = left_down

    def _update_icon_hovers(self, position: Optional[QPoint]) -> None:
        for button in getattr(self, "hover_buttons", ()):
            hovered = False
            if position is not None and button.isVisible():
                hovered = button.rect().contains(button.mapFromGlobal(position))
            button.set_hovered(hovered)

    def _hide_controls(self) -> None:
        panel_hovered = bool(
            self.track_panel
            and self.track_panel.isVisible()
            and self.track_panel.underMouse()
        )
        if self.seeking or panel_hovered:
            self.hide_timer.start(700)
            return
        if self.menu_open:
            self._close_track_panel(reveal_controls=False)
        if (
            self._cursor_in_controls_zone()
            or self.top_bar.underMouse()
            or self.bottom_bar.underMouse()
            or self.volume_popup.underMouse()
        ):
            self.hide_timer.start(700)
            return
        if self.controller.is_playing():
            self.controls_visible = False
            self._animate_controls(False)
            self.volume_popup.hide()
            self.seek_preview.hide()
            self.setCursor(Qt.BlankCursor)
            self.video_surface.setCursor(Qt.BlankCursor)
            self.overlay.setCursor(Qt.BlankCursor)

    def _animate_controls(self, showing: bool) -> None:
        if self.control_animation is not None:
            self.control_animation.stop()
            self.control_animation.deleteLater()

        group = QParallelAnimationGroup(self)
        self.control_animation = group
        self.controls_animating = True
        duration = 240 if showing else 280
        curve = QEasingCurve.OutCubic if showing else QEasingCurve.InCubic
        positions = (
            (
                self.top_bar,
                self.top_bar.pos(),
                QPoint(0, 0 if showing else -self.top_bar.height()),
            ),
            (
                self.bottom_bar,
                self.bottom_bar.pos(),
                QPoint(
                    0,
                    (
                        self.overlay.height() - self.bottom_bar.height()
                        if showing
                        else self.overlay.height()
                    ),
                ),
            ),
        )
        for widget, start, end in positions:
            animation = QPropertyAnimation(widget, b"pos", group)
            animation.setDuration(duration)
            animation.setStartValue(start)
            animation.setEndValue(end)
            animation.setEasingCurve(curve)
            group.addAnimation(animation)

        for effect in (self.top_opacity, self.bottom_opacity):
            animation = QPropertyAnimation(effect, b"opacity", group)
            animation.setDuration(duration)
            animation.setStartValue(effect.opacity())
            animation.setEndValue(1.0 if showing else 0.0)
            animation.setEasingCurve(curve)
            group.addAnimation(animation)

        group.finished.connect(
            lambda active=group: self._control_animation_finished(active)
        )
        group.start()

    def _control_animation_finished(
        self, animation: QParallelAnimationGroup
    ) -> None:
        if self.control_animation is not animation:
            return
        self.controls_animating = False
        self.control_animation = None
        animation.deleteLater()
        self._sync_overlay_geometry()

    def _toggle_fullscreen(self) -> None:
        window = self.window()
        entering = not window.isFullScreen()
        self.click_timer.stop()
        self.ignore_click_release = True
        self._close_track_panel(reveal_controls=False)
        self.overlay.hide()
        window.showFullScreen() if entering else window.showNormal()
        set_player_button_icon(
            self.fullscreen_button,
            "windowed" if entering else "fullscreen",
        )
        self.fullscreen_button.setToolTip(
            "Exit fullscreen (F)" if entering else "Fullscreen (F)"
        )

        def restore_overlay() -> None:
            self._settle_video_layout()
            self.overlay.show()
            self.overlay.raise_()
            self._restore_overlay_input(force=True)
            self._show_controls(keep=True)

        QTimer.singleShot(0, restore_overlay)
        QTimer.singleShot(
            600, lambda: setattr(self, "ignore_click_release", False)
        )

    def _show_feedback(self, text: str, duration: int = 520) -> None:
        self.feedback_timer.stop()
        self.feedback.hide()

    def _show_feedback_icon(self, kind: str, duration: int = 700) -> None:
        self.feedback.hide()
        self.feedback_timer.stop()
        self.icon_feedback_animation.stop()
        self.icon_feedback_opacity.setOpacity(0.0)
        self.icon_feedback.setPixmap(
            build_player_control_icon(kind).pixmap(QSize(48, 48))
        )
        self.icon_feedback.move(
            (self.overlay.width() - self.icon_feedback.width()) // 2,
            (self.overlay.height() - self.icon_feedback.height()) // 2,
        )
        self.icon_feedback.show()
        self.icon_feedback.raise_()
        self.icon_feedback_animation.setDuration(max(400, duration))
        self.icon_feedback_animation.start()

    def _show_toast(self, text: str, duration: int = 2200) -> None:
        self.toast_timer.stop()
        self.toast.hide()

    def _show_error(self, message: str) -> None:
        self._show_toast(message, 4000)

    def open_settings_menu(self) -> None:
        if self.track_panel and self.track_panel.isVisible():
            self._close_track_panel()
            return

        self._close_track_panel()
        self._restore_overlay_input(force=True)
        panel = QFrame(self.overlay)
        panel.setObjectName("trackPanel")
        panel.setMouseTracking(True)
        panel.setFocusPolicy(Qt.NoFocus)
        panel_layout = QHBoxLayout(panel)
        panel_layout.setContentsMargins(28, 24, 28, 24)
        panel_layout.setSpacing(28)

        audio_items: list[tuple[str, bool, object]] = []
        current_audio = self.controller.selected_audio()
        for track_id, description in self.controller.audio_tracks():
            audio_items.append(
                (
                    safe_description(description),
                    track_id == current_audio,
                    lambda checked=False, tid=track_id: self._choose_audio_track(tid),
                )
            )
        if not audio_items:
            audio_items.append(("Default audio", True, None))

        current_spu = self.controller.selected_subtitle()
        self.selected_subtitle = current_spu
        subtitle_items: list[tuple[str, bool, object]] = [
            (
                "Off",
                current_spu == -1,
                lambda checked=False: self._choose_subtitle_track(-1, ""),
            )
        ]
        for track_id, description in self.controller.subtitle_tracks():
            label = safe_description(description)
            subtitle_items.append(
                (
                    label,
                    track_id == current_spu,
                    lambda checked=False, tid=track_id, text=label: (
                        self._choose_subtitle_track(tid, text)
                    ),
                )
            )

        panel_layout.addWidget(self._track_column("Audio", audio_items), 1)
        divider = QFrame()
        divider.setObjectName("trackDivider")
        divider.setFrameShape(QFrame.VLine)
        panel_layout.addWidget(divider)
        panel_layout.addWidget(self._track_column("Subtitles", subtitle_items), 1)

        self.track_panel = panel
        self.menu_open = True
        panel.show()
        self._position_track_panel()
        panel.raise_()
        self._show_controls(keep=True)
        self.hide_timer.start()

    def _track_column(
        self, title: str, items: list[tuple[str, bool, object]]
    ) -> QWidget:
        column = QWidget()
        column.setObjectName("trackColumn")
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("trackPanelTitle")
        layout.addWidget(heading)

        scroll = QScrollArea()
        scroll.setObjectName("trackScroll")
        scroll.setFocusPolicy(Qt.NoFocus)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        contents = QWidget()
        contents.setObjectName("trackContents")
        contents.setFocusPolicy(Qt.NoFocus)
        options = QVBoxLayout(contents)
        options.setContentsMargins(0, 4, 0, 4)
        options.setSpacing(2)
        for label, active, callback in items:
            button = QPushButton(label)
            button.setObjectName("trackOption")
            button.setProperty("active", active)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)
            button.setEnabled(callback is not None)
            if active:
                button.setIcon(build_player_control_icon("check"))
                button.setIconSize(QSize(20, 20))
            else:
                button.setContentsMargins(28, 0, 0, 0)
            if callback is not None:
                button.clicked.connect(callback)
            options.addWidget(button)
        options.addStretch()
        scroll.setWidget(contents)
        layout.addWidget(scroll, 1)
        return column

    def _choose_audio_track(self, track_id: int) -> None:
        self.controller.select_audio(track_id)
        self._close_track_panel()
        self._queue_overlay_input_restore()

    def _choose_subtitle_track(
        self, track_id: int, label: str
    ) -> None:
        self._remember_subtitle_preference(track_id, label)
        self._select_subtitle(track_id)
        self._close_track_panel()
        self._queue_overlay_input_restore()

    def _position_track_panel(self) -> None:
        if not self.track_panel:
            return
        width = max(560, min(760, self.overlay.width() - 48))
        height = max(300, min(610, self.overlay.height() - 182))
        self.track_panel.setFixedSize(width, height)
        self.track_panel.move(
            max(24, self.overlay.width() - width - 24),
            max(24, self.bottom_bar.y() - height - 8),
        )

    def _dismiss_track_panel_at(self, global_position: QPoint) -> bool:
        panel = self.track_panel
        if panel is None or not panel.isVisible():
            return False
        if panel.rect().contains(panel.mapFromGlobal(global_position)):
            return False
        self.dismiss_click_active = True
        self._cancel_routed_control_press()
        self._close_track_panel()
        return True

    def _dismiss_track_panel_for_event(self, watched: QObject, event: QEvent) -> bool:
        panel = self.track_panel
        if panel is None or not panel.isVisible():
            return False
        if watched is self.overlay:
            local_position = event.position().toPoint()
            if panel.geometry().contains(local_position):
                return False
            self.dismiss_click_active = True
            self._cancel_routed_control_press()
            self._close_track_panel()
            return True
        return self._dismiss_track_panel_at(event.globalPosition().toPoint())

    def _close_track_panel(self, reveal_controls: bool = True) -> None:
        panel = self.track_panel
        self.track_panel = None
        self.menu_open = False
        if panel is not None:
            mouse_grabber = QWidget.mouseGrabber()
            if mouse_grabber is not None and (
                mouse_grabber is panel or panel.isAncestorOf(mouse_grabber)
            ):
                mouse_grabber.releaseMouse()
            panel.hide()
            panel.deleteLater()
        if reveal_controls and self.movie:
            self._show_controls()
        if panel is not None:
            QTimer.singleShot(
                0, lambda: self._restore_overlay_input(force=True)
            )
            QTimer.singleShot(
                80, lambda: self._restore_overlay_input(force=True)
            )

    def _application_owns_foreground(self) -> bool:
        active = QApplication.activeWindow()
        main_window = self.window()
        if active in {self.overlay, main_window}:
            return True
        if sys.platform != "win32":
            return active is not None
        try:
            user32 = ctypes.windll.user32
            foreground = int(user32.GetForegroundWindow())
            foreground_root = int(user32.GetAncestor(foreground, 2))
            return foreground_root in {
                int(self.overlay.winId()),
                int(main_window.winId()),
            }
        except Exception:
            return False

    def _restore_overlay_input(self, force: bool = False) -> None:
        if not self.movie or not self.isVisible():
            return
        if not force and not self._application_owns_foreground():
            return
        self._sync_overlay_geometry()
        self.overlay.show()
        self.overlay.raise_()
        self.overlay.setFocus(Qt.OtherFocusReason)

    def _queue_overlay_input_restore(self) -> None:
        for delay in (0, 120, 360):
            QTimer.singleShot(delay, self._restore_overlay_input)

    def _set_playback_rate(self, rate: float, label: str) -> None:
        self.controller.set_rate(rate)
        self._show_feedback(label)

    def _subtitle_preference_key(self) -> str:
        if not self.movie:
            return ""
        return subtitle_preference_key_for_movie(self.movie)

    def _remember_subtitle_preference(
        self, track_id: int, label: str
    ) -> None:
        key = self._subtitle_preference_key()
        if not key:
            return
        preferences = self.settings.get("series_subtitles")
        if not isinstance(preferences, dict):
            preferences = {}
            self.settings["series_subtitles"] = preferences
        preferences[key] = {
            "off": track_id == -1,
            "label": label,
            "track_id": track_id,
        }
        self.subtitle_preference_applied = True
        self.settings_changed.emit()

    def _saved_subtitle_preference(self) -> Optional[dict]:
        key = self._subtitle_preference_key()
        preferences = self.settings.get("series_subtitles", {})
        if not key or not isinstance(preferences, dict):
            return None
        value = preferences.get(key)
        return value if isinstance(value, dict) else None

    def _apply_saved_subtitle_preference(self) -> None:
        if self.subtitle_preference_applied or not self.movie:
            return
        preference = self._saved_subtitle_preference()
        if not preference:
            return
        if preference.get("off"):
            self.subtitle_preference_applied = True
            self._select_subtitle(-1)
            return

        tracks = self.controller.subtitle_tracks()
        if not tracks:
            return
        saved_label = safe_description(str(preference.get("label", ""))).casefold()
        saved_track_id = int(preference.get("track_id", -1) or -1)
        match = next(
            (
                track_id
                for track_id, description in tracks
                if saved_label and safe_description(description).casefold() == saved_label
            ),
            None,
        )
        if match is None:
            match = next(
                (track_id for track_id, _description in tracks if track_id == saved_track_id),
                None,
            )
        if match is None:
            return
        self.subtitle_preference_applied = True
        self._select_subtitle(match)

    def _select_subtitle(self, track_id: int) -> None:
        if track_id == -1:
            if self.selected_subtitle != -1:
                self.last_subtitle_selection = self.selected_subtitle
            self.controller.select_subtitle(-1)
            self.selected_subtitle = -1
        else:
            self.controller.select_subtitle(track_id)
            self.selected_subtitle = track_id
        self.last_subtitle_selection = self.selected_subtitle
        self._queue_overlay_input_restore()


class DordieWatchWindow(QMainWindow):
    WM_ENTERSIZEMOVE = 0x0231
    WM_EXITSIZEMOVE = 0x0232

    def __init__(self, launch_manifest_url: Optional[str] = None) -> None:
        super().__init__()
        self.store = DordieWatchStore()
        _saved_roots, saved_movies, self.settings = self.store.load()
        self.video_folder = project_videos_dir()
        self.video_folder.mkdir(parents=True, exist_ok=True)
        self.roots = [str(self.video_folder.resolve())]
        self.movies = [
            movie
            for movie in saved_movies
            if path_is_within(movie.path, self.video_folder)
        ]
        for movie in self.movies:
            folder = (
                Path(movie.collection)
                if movie.collection
                else collection_folder_for_video(Path(movie.path), self.video_folder)
            )
            linked_media_id = (
                collection_database_id(folder) if folder.is_dir() else None
            )
            if linked_media_id:
                movie.media_id = linked_media_id
            database_cover = database_cover_for_movie(
                movie, self.store.website_cover_dir
            )
            if database_cover:
                movie.cover = database_cover
                movie.thumbnail = database_cover
            else:
                movie.cover = ""
                movie.thumbnail = catalog_placeholder(
                    self.store, Path(movie.path), movie.title
                )
        self.scan_task: Optional[LibraryScanTask] = None
        self.scan_token = 0
        self.scan_progress_map: dict[str, tuple[int, float, bool]] = {}
        self.scan_seen_paths: set[str] = set()
        self.website_task: Optional[WebsiteMediaTask] = None
        self.website_library_task: Optional[WebsiteLibraryTask] = None
        self.sync_website_after_scan = False
        self.pending_website_payload: Optional[dict] = None
        self.setWindowTitle(APP_NAME)
        self.resize(1500, 900)
        self.setMinimumSize(980, 640)
        self.escape_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.escape_shortcut.activated.connect(self._handle_escape)

        self.pages = QStackedWidget()
        self.setCentralWidget(self.pages)
        self.home = HomePage()
        self.collection_page = CollectionPage()
        self.player = PlayerPage(self.store, self.settings)
        self.pages.addWidget(self.home)
        self.pages.addWidget(self.collection_page)
        self.pages.addWidget(self.player)
        self.player_return_page: QWidget = self.home
        self.close_after_player = False
        self.home.refresh_requested.connect(self.refresh_libraries)
        self.home.movie_activated.connect(self.open_collection)
        self.home.search.textChanged.connect(self.rebuild_home)
        self.collection_page.back_requested.connect(self.show_home)
        self.collection_page.movie_activated.connect(self.play_movie)
        self.player.back_requested.connect(self.show_previous_page)
        self.player.progress_saved.connect(self.save_progress)
        self.player.settings_changed.connect(self.save_library)
        self.rebuild_home()

        if mpv is None or MPV_RUNTIME is None:
            QTimer.singleShot(
                0,
                lambda: QMessageBox.warning(
                    self,
                    APP_NAME,
                    "The playback engine is unavailable. Rebuild the app with mpv included.",
                ),
            )
        # A saved catalog is ready to use immediately. Only a brand-new
        # library needs an initial lightweight file enumeration.
        if not self.movies:
            QTimer.singleShot(0, self.refresh_libraries)
        if launch_manifest_url:
            QTimer.singleShot(
                0,
                lambda url=launch_manifest_url: self.open_website_media(url),
            )

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32" and hasattr(self, "player"):
            try:
                native_message = ctypes.wintypes.MSG.from_address(int(message))
            except (TypeError, ValueError):
                return super().nativeEvent(event_type, message)
            if native_message.message == self.WM_ENTERSIZEMOVE:
                if self.pages.currentWidget() is self.player:
                    self.player.begin_interactive_resize()
            elif native_message.message == self.WM_EXITSIZEMOVE:
                if self.pages.currentWidget() is self.player:
                    self.player.end_interactive_resize()
        return super().nativeEvent(event_type, message)

    def rebuild_home(self, *_args) -> None:
        self.home.rebuild(self.roots, self.movies, self.home.search.text())

    def scan_folder(self, folder: Path) -> None:
        if not folder.is_dir():
            return
        root = str(folder.resolve())
        if self.scan_task:
            self.scan_task.cancel()
        self.scan_token += 1
        token = self.scan_token
        self.scan_progress_map = {
            movie.path: (movie.progress_ms, movie.last_played, movie.completed)
            for movie in self.movies
        }
        self.scan_seen_paths = set()
        self.home.set_scanning(f"Scanning {Path(root).name}…")
        task = LibraryScanTask(Path(root), self.store, self.movies)
        self.scan_task = task
        task.signals.movie.connect(
            lambda payload, active=token: self._scan_movie(payload, active)
        )
        task.signals.progress.connect(
            lambda current, total, name, active=token: self._scan_progress(
                current, total, name, active
            )
        )
        task.signals.finished.connect(
            lambda scanned_root, active=token: self._scan_finished(
                scanned_root, active
            )
        )
        task.signals.failed.connect(
            lambda message, active=token: self._scan_failed(message, active)
        )
        QThreadPool.globalInstance().start(task.runnable)

    def _scan_movie(self, payload: dict, token: int) -> None:
        if token != self.scan_token:
            return
        movie = Movie.from_dict(payload)
        if movie.path in self.scan_progress_map:
            movie.progress_ms, movie.last_played, movie.completed = (
                self.scan_progress_map[movie.path]
            )
        self.scan_seen_paths.add(movie.path)
        self.movies = [item for item in self.movies if item.path != movie.path]
        self.movies.append(movie)

    def _scan_progress(
        self, current: int, total: int, name: str, token: int
    ) -> None:
        if token != self.scan_token:
            return
        title = textwrap.shorten(name, width=44, placeholder="…")
        self.home.set_scanning(f"{current} / {total}  {title}", current, total)

    def _scan_finished(self, root: str, token: int) -> None:
        if token != self.scan_token:
            return
        self.scan_task = None
        self.movies = [
            movie
            for movie in self.movies
            if not path_is_within(movie.path, root)
            or movie.path in self.scan_seen_paths
        ]
        self.home.set_scanning(None)
        self.save_library()
        self.rebuild_home()
        if self.pending_website_payload:
            payload = self.pending_website_payload
            self.pending_website_payload = None
            self._apply_website_media(payload)
        if self.sync_website_after_scan:
            self.sync_website_after_scan = False
            self._refresh_website_library()

    def _scan_failed(self, message: str, token: int) -> None:
        if token != self.scan_token:
            return
        self.scan_task = None
        self.sync_website_after_scan = False
        self.home.set_scanning(None)
        self.save_library()
        self.rebuild_home()
        QMessageBox.warning(self, APP_NAME, f"Could not scan this folder:\n\n{message}")
        if self.pending_website_payload:
            payload = self.pending_website_payload
            self.pending_website_payload = None
            self._apply_website_media(payload)

    def refresh_libraries(self) -> None:
        self.sync_website_after_scan = True
        self.scan_folder(self.video_folder)

    def _refresh_website_library(self) -> None:
        if self.website_library_task:
            return
        library_url = str(
            self.settings.get("dordielist_library_url") or ""
        ).strip()
        parsed_url = urllib.parse.urlparse(library_url)
        media_ids = sorted(
            {
                movie.media_id
                for movie in self.movies
                if movie.media_id is not None
            }
        )
        if (
            parsed_url.scheme.casefold() not in {"http", "https"}
            or not parsed_url.netloc
            or not media_ids
        ):
            return

        self.home.set_scanning("Syncing with DordieList…")
        task = WebsiteLibraryTask(library_url, media_ids, self.store)
        self.website_library_task = task
        task.signals.loaded.connect(self._website_library_loaded)
        task.signals.failed.connect(self._website_library_failed)
        QThreadPool.globalInstance().start(task.runnable)

    def _website_library_loaded(self, payloads: list[dict]) -> None:
        self.website_library_task = None
        if not self.scan_task and not self.website_task:
            self.home.set_scanning(None)
        update_movies_from_website(self.movies, payloads, self.store)
        self.save_library()
        self.rebuild_home()

    def _website_library_failed(self, message: str) -> None:
        self.website_library_task = None
        if not self.scan_task and not self.website_task:
            self.home.set_scanning(None)
        QMessageBox.warning(
            self,
            APP_NAME,
            f"Could not refresh data from DordieList:\n\n{message}",
        )

    def open_website_media(self, manifest_url: str) -> None:
        if self.website_task:
            return
        if not self.scan_task:
            self.scan_folder(self.video_folder)
        if not self.scan_task:
            self.home.set_scanning("Connecting to DordieList…")
        task = WebsiteMediaTask(manifest_url, self.store)
        self.website_task = task
        task.signals.loaded.connect(self._website_media_loaded)
        task.signals.failed.connect(self._website_media_failed)
        QThreadPool.globalInstance().start(task.runnable)

    def _website_media_loaded(self, payload: dict) -> None:
        self.website_task = None
        library_url = str(payload.get("library_url") or "").strip()
        parsed_library_url = urllib.parse.urlparse(library_url)
        if (
            parsed_library_url.scheme.casefold() in {"http", "https"}
            and parsed_library_url.netloc
        ):
            self.settings["dordielist_library_url"] = library_url
            self.save_library()
        if not self.scan_task:
            self.home.set_scanning(None)
        self._apply_website_media(payload)

    def _website_media_failed(self, message: str) -> None:
        self.website_task = None
        if not self.scan_task:
            self.home.set_scanning(None)
        QMessageBox.warning(
            self,
            APP_NAME,
            f"Could not open this title from DordieList:\n\n{message}",
        )

    def _apply_website_media(self, payload: dict) -> None:
        collections = build_collections(self.movies, self.roots)
        collection = match_website_collection(payload, collections)
        if collection is None and self.scan_task:
            self.pending_website_payload = payload
            return
        if collection is None:
            collection = self._choose_collection_for_database_media(
                payload, collections
            )
        if collection is None:
            return

        media_id = int(payload["id"])
        folder = Path(collection.folder)
        try:
            if folder.is_dir() and collection_database_id(folder) != media_id:
                link_collection_to_database_id(folder, media_id)
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self,
                APP_NAME,
                f"Could not save the database ID in this local folder:\n\n{error}",
            )
            return

        for movie in collection.movies:
            movie.media_id = media_id
        update_movies_from_website(
            collection.movies, [payload], self.store
        )

        self.save_library()
        self.rebuild_home()
        refreshed = match_website_collection(
            payload, build_collections(self.movies, self.roots)
        )
        if refreshed:
            self.showNormal()
            self.raise_()
            self.activateWindow()
            self.open_collection(refreshed)

    def _choose_collection_for_database_media(
        self,
        payload: dict,
        collections: Iterable[LibraryCollection],
    ) -> Optional[LibraryCollection]:
        available = [
            collection
            for collection in collections
            if not {
                movie.media_id
                for movie in collection.movies
                if movie.media_id is not None
            }
        ]
        if not available:
            QMessageBox.warning(
                self,
                APP_NAME,
                "No unlinked local video folders are available for this database entry.",
            )
            return None

        available.sort(key=lambda item: natural_sort_key(Path(item.folder).name))
        labels: list[str] = []
        by_label: dict[str, LibraryCollection] = {}
        for collection in available:
            folder_name = Path(collection.folder).name
            label = (
                folder_name
                if folder_name not in by_label
                else str(Path(collection.folder))
            )
            labels.append(label)
            by_label[label] = collection

        media_id = int(payload["id"])
        display_title = str(payload.get("display_title") or "this title").strip()
        selected, accepted = QInputDialog.getItem(
            self,
            "Connect DordieList database ID",
            (
                f"Database ID {media_id}: {display_title}\n\n"
                "Choose the local video folder to link:"
            ),
            labels,
            0,
            False,
        )
        if not accepted:
            return None
        return by_label.get(selected)

    def open_collection(self, collection: LibraryCollection) -> None:
        if len(collection.movies) == 1:
            self.play_movie(collection.movies[0])
            return
        self.collection_page.set_collection(collection)
        self.pages.setCurrentWidget(self.collection_page)

    def play_movie(self, movie: Movie) -> None:
        if not Path(movie.path).is_file():
            QMessageBox.warning(self, APP_NAME, "This video is no longer available.")
            return
        current_page = self.pages.currentWidget()
        self.player_return_page = (
            current_page
            if current_page in {self.home, self.collection_page}
            else self.home
        )
        self.pages.setCurrentWidget(self.player)
        self.player.play_movie(movie)

    def show_previous_page(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        self.pages.setCurrentWidget(self.player_return_page)
        if self.player_return_page is self.home:
            self.rebuild_home()
        if self.close_after_player:
            self.close_after_player = False
            QTimer.singleShot(0, self.close)

    def show_home(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        self.pages.setCurrentWidget(self.home)
        self.rebuild_home()

    def _handle_escape(self) -> None:
        if self.player.track_panel and self.player.track_panel.isVisible():
            self.player._close_track_panel()
        elif self.isFullScreen():
            self.showNormal()
            set_player_button_icon(self.player.fullscreen_button, "fullscreen")
            self.player.fullscreen_button.setToolTip("Fullscreen (F)")
            self.player._show_controls(keep=True)
        elif self.pages.currentWidget() is self.player:
            self.player.close_player()

    def save_progress(self, movie: Movie, progress: int, completed: bool) -> None:
        movie.progress_ms = 0 if completed else max(0, progress)
        movie.completed = completed
        movie.last_played = time.time()
        self.save_library()

    def save_library(self) -> None:
        self.store.save(self.roots, self.movies, self.settings)

    def closeEvent(self, event) -> None:
        if self.scan_task:
            self.scan_task.cancel()
        if self.pages.currentWidget() is self.player and self.player.movie:
            self.close_after_player = True
            event.ignore()
            self.player.close_player()
            return
        self.save_library()
        super().closeEvent(event)


STYLESHEET = """
* {
    font-family: "Segoe UI";
    color: #f2f2f2;
    font-size: 12px;
}
QMainWindow, QStackedWidget, #homeContent, #homeScroll,
#homeScroll > QWidget > QWidget, #collectionContent, #collectionScroll,
#collectionScroll > QWidget > QWidget {
    background: #050505;
}
#homeHeader {
    background: #101010;
    border-bottom: 1px solid #1d1d1d;
}
#collectionHeader {
    background: #101010;
    border-bottom: 1px solid #1d1d1d;
}
#collectionBack {
    background: transparent;
    border: none;
    color: #ffffff;
    font-size: 15px;
    font-weight: 700;
    padding: 9px 12px;
}
#collectionBack:hover {
    color: #e50914;
}
#collectionHeaderTitle {
    color: #ffffff;
    font-size: 16px;
    font-weight: 700;
}
#collectionTitle {
    color: #ffffff;
    font-size: 36px;
    font-weight: 800;
}
#collectionDetails {
    color: #b5b5b5;
    font-size: 15px;
}
#brandLogo {
    color: #e50914;
    font-size: 34px;
    font-weight: 900;
}
#brandName {
    color: #ffffff;
    font-size: 14px;
    font-weight: 800;
    letter-spacing: 1px;
}
#navActive {
    color: #ffffff;
    font-weight: 700;
}
#navItem {
    color: #a8a8a8;
}
#homeSearchBox {
    background: transparent;
    border: none;
}
#homeSearchBox[expanded="true"] {
    background: #151515;
    border: 2px solid #5c5c5c;
    border-radius: 28px;
}
#homeSearchButton {
    background: transparent;
    border: none;
    padding: 0;
    margin: 0;
}
#homeSearchButton:hover, #homeSearchButton:pressed {
    background: transparent;
    border: none;
}
#homeSearchInput {
    background: transparent;
    border: none;
    color: #ffffff;
    font-size: 16px;
    padding: 0 0 0 4px;
    selection-background-color: #e50914;
}
#homeRefreshIcon {
    background: transparent;
    border: none;
    padding: 0;
    margin: 0;
}
#homeRefreshIcon:hover, #homeRefreshIcon:pressed {
    background: transparent;
    border: none;
}
#scanStrip {
    background: #171717;
}
#scanStrip QLabel {
    color: #aaaaaa;
}
#scanStrip QProgressBar {
    border: none;
    background: #333333;
}
#scanStrip QProgressBar::chunk {
    background: #e50914;
}
#heroKicker {
    color: #e50914;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 2px;
}
#heroTitle {
    color: #ffffff;
    font-size: 38px;
    font-weight: 800;
    max-width: 650px;
}
#heroMeta {
    color: #d0d0d0;
    font-size: 13px;
}
#heroPlay {
    background: #ffffff;
    color: #101010;
    border: none;
    border-radius: 4px;
    padding: 10px 22px;
    font-size: 14px;
    font-weight: 700;
}
#heroPlay:hover {
    background: #d8d8d8;
}
#rowHeading {
    font-size: 19px;
    font-weight: 700;
    color: #f4f4f4;
}
#rowScroll, #rowScroll > QWidget > QWidget {
    background: transparent;
}
#homeEmpty {
    color: #8c8c8c;
    font-size: 17px;
}
QScrollBar:horizontal {
    height: 8px;
    background: transparent;
}
QScrollBar::handle:horizontal {
    background: #444444;
    min-width: 40px;
    border-radius: 4px;
}
QScrollBar:vertical {
    width: 9px;
    background: #080808;
}
QScrollBar::handle:vertical {
    background: #444444;
    min-height: 40px;
    border-radius: 4px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0;
    height: 0;
}
#videoSurface {
    background: #000000;
}
#playerOverlay {
    background: transparent;
}
#playerTop {
    background: transparent;
}
#playerBottom {
    background: transparent;
}
#playerTitle {
    font-size: 15px;
    font-weight: 600;
    color: #ffffff;
    padding: 0 18px;
}
#playerIcon {
    background: transparent;
    border: none;
    color: #ffffff;
    font-size: 20px;
    padding: 2px;
    min-width: 56px;
    min-height: 52px;
}
#playerIcon:hover {
    color: #ffffff;
    background: transparent;
}
#playerIcon:pressed {
    color: #ffffff;
    background: transparent;
}
#playerTime {
    color: #ffffff;
    font-size: 12px;
    font-weight: 600;
}
#timeline::groove:horizontal {
    height: 4px;
    background: rgba(255, 255, 255, 105);
    border-radius: 2px;
}
#timeline:hover::groove:horizontal {
    height: 6px;
    border-radius: 3px;
}
#timeline::sub-page:horizontal {
    background: #e50914;
    border-radius: 2px;
}
#timeline::handle:horizontal {
    background: #e50914;
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
#timeline:hover::handle:horizontal {
    background: #e50914;
    width: 16px;
    margin: -6px 0;
    border-radius: 8px;
}
#volumeSlider::groove:horizontal {
    height: 3px;
    background: #656565;
}
#volumeSlider::sub-page:horizontal {
    background: #ffffff;
}
#volumeSlider::handle:horizontal {
    background: #ffffff;
    width: 10px;
    margin: -4px 0;
    border-radius: 5px;
}
#volumePopup {
    background: rgba(40, 40, 40, 245);
    border-radius: 4px;
}
#volumeSliderVertical::groove:vertical {
    width: 10px;
    background: #8d8d8d;
    border-radius: 2px;
}
#volumeSliderVertical::add-page:vertical {
    background: #e50914;
    border-radius: 2px;
}
#volumeSliderVertical::sub-page:vertical {
    background: #8d8d8d;
    border-radius: 2px;
}
#volumeSliderVertical::handle:vertical {
    background: #e50914;
    height: 22px;
    margin: 0 -6px;
    border-radius: 11px;
}
#trackPanel {
    background: rgba(38, 38, 38, 248);
    border: none;
}
#trackColumn, #trackContents, #trackScroll,
#trackScroll > QWidget > QWidget {
    background: transparent;
    border: none;
}
#trackPanelTitle {
    color: #ffffff;
    font-size: 20px;
    font-weight: 700;
    padding: 0 8px 7px 8px;
}
#trackOption {
    background: transparent;
    border: none;
    border-radius: 2px;
    color: #b8b8b8;
    font-size: 15px;
    min-height: 42px;
    padding: 5px 10px;
    text-align: left;
}
#trackOption:hover {
    background: #383838;
    color: #ffffff;
}
#trackOption:disabled {
    color: #ffffff;
}
#trackOption[active="true"] {
    color: #ffffff;
    font-weight: 600;
}
#trackDivider {
    background: #4a4a4a;
    border: none;
    min-width: 1px;
    max-width: 1px;
}
#playerToast {
    background: rgba(18, 18, 18, 235);
    border: 1px solid #444444;
    border-radius: 5px;
    padding: 9px 15px;
}
#seekPreview {
    background: rgba(8, 8, 8, 235);
    border: 1px solid rgba(255, 255, 255, 45);
    border-radius: 4px;
}
#seekPreviewImage {
    background: #000000;
    border-radius: 2px;
}
#seekTooltip {
    background: transparent;
    border: none;
    color: #ffffff;
    font-size: 12px;
    padding: 2px 5px;
}
#playerFeedback {
    background: rgba(0, 0, 0, 165);
    border-radius: 22px;
    color: #ffffff;
    font-size: 18px;
    font-weight: 700;
    min-height: 44px;
    padding: 0 18px;
}
#playerIconFeedback {
    background: rgba(0, 0, 0, 170);
    border: none;
    border-radius: 44px;
    min-width: 88px;
    max-width: 88px;
    min-height: 88px;
    max-height: 88px;
    padding: 0;
}
QMenu, #playerMenu {
    background: #1e1e1e;
    border: 1px solid #4a4a4a;
    padding: 5px;
}
QMenu::item {
    padding: 7px 30px 7px 12px;
}
QMenu::item:selected {
    background: #3a3a3a;
}
QMenu::separator {
    height: 1px;
    background: #444444;
    margin: 5px;
}
QMessageBox {
    background: #202020;
}
QMessageBox QPushButton {
    background: #333333;
    border: 1px solid #555555;
    border-radius: 4px;
    padding: 6px 14px;
}
"""


def build_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#e50914"))
    painter.drawRoundedRect(6, 6, 52, 52, 10, 10)
    painter.setPen(QPen(QColor("#ffffff"), 7))
    painter.drawLine(22, 45, 22, 19)
    painter.drawLine(22, 19, 42, 45)
    painter.drawLine(42, 45, 42, 19)
    painter.end()
    return QIcon(pixmap)


def main() -> int:
    install_crash_logging()
    if "--register-protocol" in sys.argv:
        return 0 if register_url_scheme() else 1

    register_url_scheme()
    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName("DordieWatch")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(build_icon())
    manifest_url = website_launch_manifest(sys.argv[1:])
    window = DordieWatchWindow(manifest_url)
    window.show()
    screenshot_path = next(
        (
            argument.split("=", 1)[1]
            for argument in sys.argv[1:]
            if argument.startswith("--screenshot=")
        ),
        None,
    )
    if screenshot_path:
        def save_screenshot() -> None:
            window.grab().save(screenshot_path)
            app.quit()

        QTimer.singleShot(2000, save_screenshot)
    elif "--smoke-test" in sys.argv:
        QTimer.singleShot(700, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
