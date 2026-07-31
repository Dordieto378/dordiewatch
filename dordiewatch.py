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

APP_FONT_FAMILY = "Netflix Sans"


def bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", SOURCE_ROOT))


def app_font_family() -> str:
    return APP_FONT_FAMILY


def app_qfont(point_size: int, weight=None):
    return QFont(app_font_family(), point_size, QFont.Normal if weight is None else weight)


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
    QPointF,
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
    QFontDatabase,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QOpenGLContext,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRegion,
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


def load_app_font(app: QApplication) -> str:
    global APP_FONT_FAMILY
    candidates = [
        bundle_root() / "font" / "NetflixSans-Bold.otf",
        SOURCE_ROOT / "font" / "NetflixSans-Bold.otf",
    ]
    for font_path in candidates:
        if not font_path.is_file():
            continue
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id < 0:
            continue
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            APP_FONT_FAMILY = families[0]
            app.setFont(QFont(APP_FONT_FAMILY, 10))
            return APP_FONT_FAMILY
    app.setFont(QFont(APP_FONT_FAMILY, 10))
    return APP_FONT_FAMILY


APP_NAME = "DordieWatch"
APP_VERSION = 4
EPISODE_PREVIEW_CACHE_VERSION = "episode-preview-v2"
EPISODE_PREVIEW_PLACEHOLDER_MARKER = ".placeholder"
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


_DEBUG_LOG_HANDLE = None
_DEBUG_LOG_LOCK = threading.Lock()
_DEBUG_LOG_STARTED = time.monotonic()


def _debug_log_path() -> Path:
    return app_data_dir() / "debug.log"


def install_debug_logging() -> None:
    global _DEBUG_LOG_HANDLE
    try:
        path = _debug_log_path()
        if path.is_file() and path.stat().st_size > 8 * 1024 * 1024:
            path.replace(path.with_suffix(".previous.log"))
        _DEBUG_LOG_HANDLE = path.open("w", encoding="utf-8")
        diagnostic_log(
            "app.debug_log.start",
            path=str(path),
            argv=" ".join(sys.argv),
            frozen=bool(getattr(sys, "frozen", False)),
            source_root=str(SOURCE_ROOT),
            mpv_runtime=str(MPV_RUNTIME) if MPV_RUNTIME else "",
        )
    except OSError:
        _DEBUG_LOG_HANDLE = None


def diagnostic_log(event: str, **fields) -> None:
    handle = _DEBUG_LOG_HANDLE
    if handle is None:
        return
    elapsed = time.monotonic() - _DEBUG_LOG_STARTED
    parts = [f"{elapsed:010.3f}", event]
    for key, value in fields.items():
        if isinstance(value, bool):
            text = "true" if value else "false"
        elif value is None:
            text = "none"
        else:
            text = str(value)
        text = text.replace("\r", "\\r").replace("\n", "\\n")
        if len(text) > 280:
            text = text[:277] + "..."
        parts.append(f"{key}={text}")
    line = " | ".join(parts) + "\n"
    with _DEBUG_LOG_LOCK:
        try:
            handle.write(line)
            handle.flush()
        except OSError:
            pass


def diagnostic_path_summary(path: object) -> str:
    if not path:
        return "none"
    try:
        candidate = Path(str(path))
        if candidate.is_file():
            stat = candidate.stat()
            return f"file:{candidate}|size:{stat.st_size}|mtime:{stat.st_mtime_ns}"
        if candidate.exists():
            return f"exists:{candidate}"
        return f"missing:{candidate}"
    except OSError as error:
        return f"error:{path}|{error!r}"


def diagnostic_tracks_summary(tracks: object) -> str:
    if not isinstance(tracks, list):
        return str(type(tracks).__name__)
    parts: list[str] = []
    for index, track in enumerate(tracks[:12]):
        if isinstance(track, dict):
            parts.append(
                "{" + ",".join(
                    f"{key}={track.get(key)}"
                    for key in ("id", "type", "title", "lang", "codec", "external", "selected")
                    if key in track
                ) + "}"
            )
        else:
            parts.append(str(track))
    if len(tracks) > 12:
        parts.append(f"...+{len(tracks) - 12}")
    return "; ".join(parts)


def widget_snapshot(widget: QWidget) -> str:
    try:
        geometry = widget.geometry()
        return (
            f"{geometry.x()},{geometry.y()} "
            f"{geometry.width()}x{geometry.height()} "
            f"visible={widget.isVisible()} enabled={widget.isEnabled()}"
        )
    except Exception as error:
        return f"unavailable:{error}"


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


def format_episode_runtime(milliseconds: int | float) -> str:
    if not milliseconds:
        return ""
    minutes = max(1, int(float(milliseconds) // 60000))
    return f"{minutes}m"


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


def draw_frame_fit(painter: QPainter, target: QRect, pixmap: QPixmap) -> None:
    painter.fillRect(target, QColor("#111111"))
    if pixmap.isNull():
        return
    scaled = pixmap.scaled(
        target.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
    )
    x = target.x() + (target.width() - scaled.width()) // 2
    y = target.y() + (target.height() - scaled.height()) // 2
    painter.drawPixmap(QPoint(x, y), scaled)


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
            media_title_from_folder_name(folder.stem if folder_is_file else folder.name),
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

    for collection in collections:
        if any(movie.media_id == media_id for movie in collection.movies):
            return collection
        folder = collection_filesystem_folder(collection)
        if folder.is_dir() and media_id in collection_database_ids(folder):
            return collection
    return None


MEDIA_LINK_FILENAME = ".dordielist.json"
MEDIA_ID_FOLDER_PATTERN = re.compile(r"\[(\d+)\]")
TRAILING_MEDIA_IDS_PATTERN = re.compile(r"(?:\s*\[\d+\])+\s*$")
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def media_ids_from_folder_name(name: str) -> list[int]:
    clean_name = str(name).strip()
    ids: list[int] = []
    for raw_id in MEDIA_ID_FOLDER_PATTERN.findall(clean_name):
        try:
            media_id = int(raw_id)
        except ValueError:
            continue
        if media_id > 0 and media_id not in ids:
            ids.append(media_id)
    if ids:
        return ids
    if clean_name.isdigit():
        media_id = int(clean_name)
        return [media_id] if media_id > 0 else []
    return []


def media_id_from_folder_name(name: str) -> Optional[int]:
    ids = media_ids_from_folder_name(name)
    return ids[0] if ids else None


def media_title_from_folder_name(name: str) -> str:
    title = TRAILING_MEDIA_IDS_PATTERN.sub("", str(name)).strip()
    return title or str(name).strip()


def safe_media_folder_title(title: str, fallback: str = "Anime") -> str:
    clean_title = media_title_from_folder_name(title or "").strip() or fallback
    clean_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", clean_title)
    clean_title = re.sub(r"\s+", " ", clean_title).strip(" .")
    if not clean_title:
        clean_title = fallback
    if clean_title.upper() in WINDOWS_RESERVED_NAMES:
        clean_title = f"{clean_title} Title"
    return clean_title[:140].rstrip(" .") or fallback


def media_folder_name(display_title: str, media_ids: int | Iterable[int]) -> str:
    if isinstance(media_ids, int):
        ordered_ids = [media_ids]
    else:
        ordered_ids = []
        for raw_id in media_ids:
            try:
                media_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if media_id > 0 and media_id not in ordered_ids:
                ordered_ids.append(media_id)
    suffix = "".join(f" [{media_id}]" for media_id in ordered_ids)
    return f"{safe_media_folder_title(display_title)}{suffix}"


def collection_filesystem_folder(collection: LibraryCollection) -> Path:
    candidate = Path(collection.folder)
    if candidate.is_dir():
        return candidate
    for movie in collection.movies:
        if movie.collection and Path(movie.collection).is_dir():
            return Path(movie.collection)
    for movie in collection.movies:
        parent = Path(movie.path).parent
        if parent.is_dir():
            return parent
    return candidate


def update_collection_paths_after_folder_rename(
    collection: LibraryCollection, old_folder: Path, new_folder: Path
) -> None:
    try:
        old_resolved = old_folder.resolve()
    except OSError:
        old_resolved = old_folder
    for movie in collection.movies:
        try:
            movie_path = Path(movie.path).resolve()
            relative = movie_path.relative_to(old_resolved)
            movie.path = str(new_folder / relative)
        except (OSError, ValueError):
            pass
        movie.collection = str(new_folder)
    collection.folder = str(new_folder)


def collection_database_ids(folder: Path) -> list[int]:
    ids = media_ids_from_folder_name(folder.name)
    marker = folder / MEDIA_LINK_FILENAME
    if marker.is_file():
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
            marker_values = payload.get("media_ids", [])
            if not isinstance(marker_values, list):
                marker_values = []
            if payload.get("media_id") is not None:
                marker_values.append(payload.get("media_id"))
            for raw_id in marker_values:
                try:
                    media_id = int(raw_id)
                except (TypeError, ValueError):
                    continue
                if media_id > 0 and media_id not in ids:
                    ids.append(media_id)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    return ids


def collection_database_id(folder: Path) -> Optional[int]:
    ids = collection_database_ids(folder)
    return ids[0] if ids else None


def link_collection_to_database_id(
    folder: Path, media_id: int, display_title: str = ""
) -> Path:
    media_id = int(media_id)
    if media_id <= 0 or not folder.is_dir():
        raise ValueError("The local folder or DordieList media ID is invalid.")

    ids = collection_database_ids(folder)
    if media_id not in ids:
        ids.append(media_id)
    folder_has_visible_ids = bool(media_ids_from_folder_name(folder.name))
    base_title = media_title_from_folder_name(folder.name) if folder_has_visible_ids else display_title or folder.name
    target_name = media_folder_name(base_title, ids)
    target = folder.with_name(target_name)
    try:
        same_target = folder.resolve() == target.resolve()
    except OSError:
        same_target = str(folder) == str(target)
    if same_target:
        return folder
    if target.exists():
        raise FileExistsError(f"A folder already exists with this DordieList name: {target}")
    folder.rename(target)
    return target


class DordieWatchStore:
    def __init__(self) -> None:
        self.base_dir = app_data_dir()
        self.preview_dir = self.base_dir / "previews"
        self.website_cover_dir = self.base_dir / "website-covers"
        self.subtitle_cache_dir = self.base_dir / "subtitle-cache"
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        self.website_cover_dir.mkdir(parents=True, exist_ok=True)
        self.subtitle_cache_dir.mkdir(parents=True, exist_ok=True)
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


def episode_still_for_movie(movie: Movie) -> str:
    frames = usable_episode_preview_frames(movie)
    if frames:
        return frames[0]
    return ""


def is_placeholder_preview_path(path: str | Path) -> bool:
    preview_path = Path(path)
    parent = preview_path.parent
    if (parent / EPISODE_PREVIEW_PLACEHOLDER_MARKER).is_file():
        return True
    # Legacy placeholder caches had only preview-01.jpg plus thumbnail.jpg and
    # no marker. Treat one-frame preview caches as invalid so they regenerate.
    if (
        preview_path.name in {"thumbnail.jpg", "preview-01.jpg"}
        and (parent / "preview-01.jpg").is_file()
        and not (parent / "preview-02.jpg").is_file()
    ):
        return True
    return False


def usable_episode_preview_frames(movie: Movie) -> list[str]:
    frames = [
        path
        for path in movie.preview_frames
        if Path(path).is_file() and not is_placeholder_preview_path(path)
    ]
    return frames if len(frames) >= 2 else []


def has_episode_preview_frames(movie: Movie) -> bool:
    return bool(usable_episode_preview_frames(movie))


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
        candidate_ids: list[int] = []
        if movie.media_id is not None:
            candidate_ids.append(movie.media_id)
        if movie.collection:
            for media_id in collection_database_ids(Path(movie.collection)):
                if media_id not in candidate_ids:
                    candidate_ids.append(media_id)
        payload = next(
            (media_by_id[media_id] for media_id in candidate_ids if media_id in media_by_id),
            None,
        )
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
        elif previous_cover and previous_cover_url == movie.cover_source_url:
            movie.cover = previous_cover
        else:
            movie.cover = ""
        if not episode_still_for_movie(movie):
            movie.thumbnail = catalog_placeholder(store, Path(movie.path), movie.title)
        updated += 1
    return updated


def generate_previews(
    video: Path, output_dir: Path, duration_ms: int, ffmpeg: Optional[str]
) -> tuple[str, tuple[str, ...]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    thumbnail = output_dir / "thumbnail.jpg"
    placeholder_marker = output_dir / EPISODE_PREVIEW_PLACEHOLDER_MARKER
    existing = sorted(output_dir.glob("preview-*.jpg"))
    if (
        thumbnail.is_file()
        and len(existing) >= 2
        and not placeholder_marker.is_file()
    ):
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
                if frame.is_file() and frame.stat().st_size > 0:
                    frames.append(frame)
            except (OSError, subprocess.SubprocessError):
                continue

    if not frames:
        fallback = output_dir / "preview-01.jpg"
        try:
            _placeholder_image(fallback, video.stem)
            placeholder_marker.write_text(
                "ffmpeg preview extraction failed\n", encoding="utf-8"
            )
            frames.append(fallback)
        except OSError:
            return "", ()
    else:
        try:
            placeholder_marker.unlink(missing_ok=True)
        except OSError:
            pass

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
        self.ffmpeg = find_binary("ffmpeg")
        self.ffprobe = find_binary("ffprobe")
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
                if (
                    not movie.duration_ms
                    or not movie.width
                    or not movie.height
                ):
                    duration_ms, width, height = probe_video(path, self.ffprobe)
                    movie.duration_ms = movie.duration_ms or duration_ms
                    movie.width = movie.width or width
                    movie.height = movie.height or height
                preview_dir = (
                    self.store.preview_dir
                    / cache_key(
                        path,
                        (
                            f"{EPISODE_PREVIEW_CACHE_VERSION}:"
                            f"{stat.st_size}:{stat.st_mtime}"
                        ),
                    )
                )
                thumbnail, preview_frames = generate_previews(
                    path,
                    preview_dir,
                    movie.duration_ms,
                    self.ffmpeg,
                )
                if thumbnail and Path(thumbnail).is_file():
                    movie.thumbnail = thumbnail
                if preview_frames:
                    movie.preview_frames = preview_frames
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


class PreviewGenerationTask:
    def __init__(
        self,
        movies: Iterable[Movie],
        store: DordieWatchStore,
        task_key: str,
    ) -> None:
        from PySide6.QtCore import QRunnable

        class Runnable(QRunnable):
            def __init__(inner, owner: "PreviewGenerationTask") -> None:
                super().__init__()
                inner.owner = owner

            def run(inner) -> None:
                inner.owner.run()

        self.movies = tuple(Movie.from_dict(movie.to_dict()) for movie in movies)
        self.store = store
        self.task_key = task_key
        self.signals = ScanSignals()
        self.runnable = Runnable(self)
        self.cancelled = threading.Event()
        self.ffmpeg = find_binary("ffmpeg")
        self.ffprobe = find_binary("ffprobe")

    def cancel(self) -> None:
        self.cancelled.set()

    def run(self) -> None:
        total = len(self.movies)
        diagnostic_log(
            "preview_task.start",
            key=self.task_key,
            total=total,
            ffmpeg=self.ffmpeg or "",
            ffprobe=self.ffprobe or "",
        )
        try:
            for index, movie in enumerate(self.movies, 1):
                if self.cancelled.is_set():
                    diagnostic_log("preview_task.cancelled", key=self.task_key)
                    return
                if has_episode_preview_frames(movie):
                    self.signals.movie.emit(movie.to_dict())
                    self.signals.progress.emit(index, total, movie.title)
                    continue
                path = Path(movie.path)
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if (
                    not movie.duration_ms
                    or not movie.width
                    or not movie.height
                ):
                    duration_ms, width, height = probe_video(path, self.ffprobe)
                    movie.duration_ms = movie.duration_ms or duration_ms
                    movie.width = movie.width or width
                    movie.height = movie.height or height
                preview_dir = (
                    self.store.preview_dir
                    / cache_key(
                        path,
                        (
                            f"{EPISODE_PREVIEW_CACHE_VERSION}:"
                            f"{stat.st_size}:{stat.st_mtime}"
                        ),
                    )
                )
                thumbnail, preview_frames = generate_previews(
                    path,
                    preview_dir,
                    movie.duration_ms,
                    self.ffmpeg,
                )
                movie.preview_frames = preview_frames
                if thumbnail and Path(thumbnail).is_file():
                    movie.thumbnail = thumbnail
                diagnostic_log(
                    "preview_task.movie",
                    key=self.task_key,
                    title=movie.title,
                    frames=len(usable_episode_preview_frames(movie)),
                    thumbnail=movie.thumbnail,
                )
                self.signals.movie.emit(movie.to_dict())
                self.signals.progress.emit(index, total, movie.title)
            self.signals.finished.emit(self.task_key)
            diagnostic_log("preview_task.finished", key=self.task_key, total=total)
        except Exception as error:
            diagnostic_log("preview_task.failed", key=self.task_key, error=repr(error))
            try:
                self.signals.failed.emit(str(error))
            except RuntimeError:
                return



class SubtitleCacheSignals(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)


class SubtitleCacheTask:
    def __init__(
        self,
        movies: Iterable[Movie],
        store: DordieWatchStore,
        task_key: str,
    ) -> None:
        from PySide6.QtCore import QRunnable

        class Runnable(QRunnable):
            def __init__(inner, owner: "SubtitleCacheTask") -> None:
                super().__init__()
                inner.owner = owner

            def run(inner) -> None:
                inner.owner.run()

        self.movies = tuple(Movie.from_dict(movie.to_dict()) for movie in movies)
        self.store = store
        self.task_key = task_key
        self.signals = SubtitleCacheSignals()
        self.runnable = Runnable(self)
        self.cancelled = threading.Event()
        self.ffmpeg = find_binary("ffmpeg")
        self.ffprobe = find_binary("ffprobe")

    def cancel(self) -> None:
        self.cancelled.set()

    def run(self) -> None:
        total = len(self.movies)
        existing_tracks = 0
        ready_tracks = 0
        try:
            for index, movie in enumerate(self.movies, 1):
                if self.cancelled.is_set():
                    return
                self.signals.progress.emit(index - 1, total, movie.title)
                before = cached_subtitle_tracks_for_movie(
                    movie,
                    self.store.subtitle_cache_dir,
                    self.ffprobe,
                    self.ffmpeg,
                    create=False,
                )
                existing_tracks += len(before)
                after = cached_subtitle_tracks_for_movie(
                    movie,
                    self.store.subtitle_cache_dir,
                    self.ffprobe,
                    self.ffmpeg,
                    create=True,
                )
                ready_tracks += len(after)
                self.signals.progress.emit(index, total, movie.title)
            self.signals.finished.emit(
                {
                    "key": self.task_key,
                    "videos": total,
                    "tracks": ready_tracks,
                    "created": max(0, ready_tracks - existing_tracks),
                    "already": existing_tracks,
                }
            )
        except Exception as error:
            diagnostic_log("subtitle_cache_task.failed", key=self.task_key, error=repr(error))
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
            for path in usable_episode_preview_frames(self.movie)
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
        painter.setFont(app_qfont(10, QFont.DemiBold))
        title = painter.fontMetrics().elidedText(
            self.movie.title, Qt.ElideRight, self.card_width
        )
        painter.drawText(
            QRect(0, self.card_height + 8, self.card_width, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            title,
        )
        painter.setPen(QColor("#8d8d8d"))
        painter.setFont(app_qfont(8))
        painter.drawText(
            QRect(0, self.card_height + 27, self.card_width, 14),
            Qt.AlignLeft | Qt.AlignVCenter,
            f"{format_duration(self.movie.duration_ms)}  -  {format_bytes(self.movie.size)}",
        )


class MovieRow(QWidget):
    movie_activated = Signal(object)

    def __init__(self, title: str, movies: list[Movie]) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(9)
        if title.strip():
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
    activated = Signal(object, object)

    def __init__(self, collection: LibraryCollection, width: int = 190) -> None:
        super().__init__()
        self.collection = collection
        self.card_width = width
        self.card_height = round(width * 1.5)
        self.cover = QPixmap(collection.cover)
        self.setFixedSize(width, self.card_height + 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(collection.title)



    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            source_rect = QRect(
                self.mapToGlobal(QPoint(0, 0)),
                QSize(self.card_width, self.card_height),
            )
            self.activated.emit(self.collection, source_rect)
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
        painter.setFont(app_qfont(10, QFont.DemiBold))
        title = painter.fontMetrics().elidedText(
            self.collection.title, Qt.ElideRight, self.card_width
        )
        painter.drawText(
            QRect(0, self.card_height + 7, self.card_width, 19),
            Qt.AlignLeft | Qt.AlignVCenter,
            title,
        )

class CollectionRow(QWidget):
    collection_activated = Signal(object, object)

    def __init__(
        self, title: str, collections: list[LibraryCollection]
    ) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 10)
        layout.setSpacing(9)
        if title.strip():
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


class CollectionGrid(QWidget):
    collection_activated = Signal(object, object)

    CARD_WIDTH = 190
    CARD_SPACING = 14

    def __init__(
        self, title: str, collections: list[LibraryCollection]
    ) -> None:
        super().__init__()
        self.collections = collections
        self.cards: list[CollectionCard] = []
        self._columns = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 18)
        layout.setSpacing(12)
        if title.strip():
            heading = QLabel(title)
            heading.setObjectName("rowHeading")
            layout.addWidget(heading)
        self.grid_host = QWidget()
        self.grid_host.setMinimumWidth(0)
        self.grid_host.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self.grid_host)
        for collection in collections:
            card = CollectionCard(collection, self.CARD_WIDTH)
            card.setParent(self.grid_host)
            card.activated.connect(self.collection_activated)
            self.cards.append(card)
        self._reflow()

    def minimumSizeHint(self) -> QSize:
        size = super().minimumSizeHint()
        return QSize(self.CARD_WIDTH, size.height())

    def sizeHint(self) -> QSize:
        size = super().sizeHint()
        return QSize(self.CARD_WIDTH, size.height())

    def _target_columns(self) -> int:
        available_width = max(
            self.CARD_WIDTH,
            self.grid_host.width() if self.grid_host.width() > 0 else self.width(),
        )
        return max(
            1,
            (available_width + self.CARD_SPACING)
            // (self.CARD_WIDTH + self.CARD_SPACING),
        )

    def _reflow(self) -> None:
        columns = self._target_columns()
        self._columns = columns
        card_height = 0
        for index, card in enumerate(self.cards):
            row, column = divmod(index, columns)
            card_height = card.height()
            x = column * (self.CARD_WIDTH + self.CARD_SPACING)
            y = row * (card.height() + 22)
            card.setGeometry(x, y, card.width(), card.height())
            card.show()
        row_count = (len(self.cards) + columns - 1) // columns if self.cards else 0
        height = (
            row_count * card_height + max(0, row_count - 1) * 22
            if row_count
            else 0
        )
        self.grid_host.setMinimumHeight(height)
        self.grid_host.setMaximumHeight(height)
        self.grid_host.updateGeometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._reflow()


class HomeHeroOverlay(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        horizontal = QLinearGradient(0, 0, self.width(), 0)
        horizontal.setColorAt(0.0, QColor(0, 0, 0, 248))
        horizontal.setColorAt(0.52, QColor(0, 0, 0, 145))
        horizontal.setColorAt(1.0, QColor(0, 0, 0, 45))
        painter.fillRect(self.rect(), horizontal)
        vertical = QLinearGradient(0, 0, 0, self.height())
        vertical.setColorAt(0.0, QColor(0, 0, 0, 25))
        vertical.setColorAt(0.58, QColor(0, 0, 0, 25))
        vertical.setColorAt(0.84, QColor(5, 5, 5, 185))
        vertical.setColorAt(1.0, QColor(5, 5, 5, 255))
        painter.fillRect(self.rect(), vertical)


class HeroWidget(QWidget):
    play_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.collection: Optional[LibraryCollection] = None
        self.movie: Optional[Movie] = None
        self.preview_path = ""
        self.preview_started = False
        self.pixmap = QPixmap()
        self.setMinimumHeight(380)
        self.setMaximumHeight(470)
        self.video_surface = MpvPreviewVideoSurface(self)
        self.preview_controller = MpvController(self.video_surface)
        self.video_surface.hide()
        self.overlay = HomeHeroOverlay(self)
        layout = QVBoxLayout(self.overlay)
        layout.setContentsMargins(50, 40, 50, 50)
        layout.addStretch()
        self.kicker = QLabel("")
        self.kicker.setObjectName("heroKicker")
        self.title = QLabel("")
        self.title.setObjectName("heroTitle")
        self.title.setWordWrap(True)
        self.meta = QLabel("")
        self.meta.setObjectName("heroMeta")
        button_row = QHBoxLayout()
        self.play = QPushButton("▶  Play")
        self.play.setObjectName("heroPlay")
        self.play.setText("Play")
        self.play.setIcon(build_solid_play_icon())
        self.play.setIconSize(QSize(30, 30))
        self.play.clicked.connect(self._emit_play)
        button_row.addWidget(self.play)
        button_row.addStretch()
        layout.addWidget(self.kicker)
        layout.addWidget(self.title)
        layout.addWidget(self.meta)
        layout.addSpacing(10)
        layout.addLayout(button_row)

    def set_feature(
        self,
        collection: Optional[LibraryCollection],
        movie: Optional[Movie] = None,
    ) -> None:
        self.collection = collection
        representative = movie or (collection.representative if collection else None)
        self.movie = representative
        new_preview_path = representative.path if representative else ""
        if new_preview_path != self.preview_path:
            self.stop_preview()
            self.preview_path = new_preview_path
        still_path = episode_still_for_movie(representative) if representative else ""
        self.pixmap = QPixmap(
            still_path
            or (representative.thumbnail if representative else "")
            or (collection.cover if collection else "")
        )
        if collection and representative:
            self.title.setText(collection.title)
            self.meta.hide()
            self.kicker.hide()
            self.play.setText("Play")
            self.play.show()
            self.update()
            QTimer.singleShot(120, self.start_preview)
            return
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
            self.meta.hide()
            self.play.hide()
            self.kicker.hide()
            self.stop_preview()
        self.update()

    def _emit_play(self) -> None:
        if self.movie:
            self.play_requested.emit(self.movie)

    def start_preview(self) -> None:
        if self.preview_started or not self.preview_path:
            return
        self.preview_started = True
        self.video_surface.setGeometry(self.rect())
        if self.preview_controller.open_preview(self.preview_path):
            QTimer.singleShot(220, self._show_preview_surface)
        else:
            self.preview_started = False

    def _show_preview_surface(self) -> None:
        if not self.preview_started:
            return
        self.video_surface.setGeometry(self.rect())
        self.video_surface.show()
        self.video_surface.lower()
        self.overlay.raise_()

    def stop_preview(self) -> None:
        self.preview_started = False
        try:
            self.preview_controller.stop()
        except Exception:
            pass
        self.video_surface.hide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.video_surface.setGeometry(self.rect())
        self.overlay.setGeometry(self.rect())
        self.video_surface.lower()
        self.overlay.raise_()

    def paintEvent(self, event) -> None:
        if self.video_surface.isVisible():
            return
        painter = QPainter(self)
        draw_cover(painter, self.rect(), self.pixmap)


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


def build_solid_play_icon(color: str = "#111111") -> QIcon:
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.transparent)
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">
      <path fill="{color}" d="M17 10L39 24L17 38Z"/>
    </svg>
    """
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(6, 6, 36, 36))
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
    movie_activated = Signal(object, object)
    hero_play_requested = Signal(object)

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
        self.content_layout.setContentsMargins(0, 30, 0, 45)
        self.content_layout.setSpacing(8)

        self.rows = QWidget()
        self.rows_layout = QVBoxLayout(self.rows)
        self.rows_layout.setContentsMargins(38, 0, 38, 0)
        self.rows_layout.setSpacing(14)
        self.content_layout.addWidget(self.rows)
        self.content_layout.addStretch()
        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll, 1)

        self.scroll.verticalScrollBar().valueChanged.connect(self._update_header_background)
        self.refresh_button.clicked.connect(self.refresh_requested)
        self.search_box.width_changed.connect(self._position_search_box)
        self.header.installEventFilter(self)
        self.header_controls.installEventFilter(self)
        self.refresh_button.installEventFilter(self)
        self._search_position_pending = False
        self.search_box.raise_()
        self._update_header_background(0)
        self._schedule_position_search_box()

    def _update_header_background(self, value: Optional[int] = None) -> None:
        if value is None:
            value = self.scroll.verticalScrollBar().value()
        opacity = max(0.0, min(1.0, value / 90.0))
        background_alpha = int(245 * opacity)
        border_alpha = int(255 * opacity)
        self.header.setStyleSheet(
            "QFrame#homeHeader {"
            f"background: rgba(16, 16, 16, {background_alpha});"
            f"border-bottom: 1px solid rgba(29, 29, 29, {border_alpha});"
            "}"
        )

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
        if filtered:
            self._add_collection_row("", filtered)

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
        row = CollectionGrid(title, collections)
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


class EpisodeListItem(QWidget):
    activated = Signal(object)

    def __init__(self, index: int, movie: Movie) -> None:
        super().__init__()
        self.index = index
        self.movie = movie
        still_path = episode_still_for_movie(movie)
        self.thumbnail = QPixmap(still_path)
        self.current_pixmap = self.thumbnail
        self.preview_pixmaps: list[QPixmap] = []
        self.preview_index = 0
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(310)
        self.preview_timer.timeout.connect(self._advance_preview)
        self.hovered = False
        self.setMinimumHeight(124)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

    def enterEvent(self, event) -> None:
        self.hovered = True
        self.preview_pixmaps = [
            QPixmap(path)
            for path in usable_episode_preview_frames(self.movie)
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
        painter.setPen(QColor("#dcdcdc"))
        painter.setFont(app_qfont(18, QFont.Normal))
        number_rect = QRect(18, 0, 42, self.height())
        painter.drawText(number_rect, Qt.AlignCenter, str(self.index))

        thumb_width = 150
        thumb_height = 84
        thumb_rect = QRect(74, (self.height() - thumb_height) // 2, thumb_width, thumb_height)
        clip = QPainterPath()
        clip.addRoundedRect(thumb_rect, 4, 4)
        painter.save()
        painter.setClipPath(clip)
        draw_cover(painter, thumb_rect, self.current_pixmap)
        if self.hovered:
            painter.fillRect(thumb_rect, QColor(0, 0, 0, 48))
            center = thumb_rect.center()
            radius = 25
            play_rect = QRect(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
            painter.setBrush(QColor(0, 0, 0, 50))
            painter.setPen(QPen(QColor(255, 255, 255, 230), 1.6))
            painter.drawEllipse(play_rect)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 245))
            painter.drawPolygon(
                [
                    QPoint(center.x() - 7, center.y() - 13),
                    QPoint(center.x() - 7, center.y() + 13),
                    QPoint(center.x() + 14, center.y()),
                ]
            )
        painter.restore()

        duration = format_episode_runtime(self.movie.duration_ms)
        if duration:
            painter.setPen(QColor("#f2f2f2"))
            painter.setFont(app_qfont(12, QFont.Bold))
            painter.drawText(
                QRect(self.width() - 96, 24, 72, 28),
                Qt.AlignRight | Qt.AlignVCenter,
                duration,
            )

        text_left = thumb_rect.right() + 18
        text_right = self.width() - 112
        painter.setPen(QColor("#ffffff"))
        painter.setFont(app_qfont(11, QFont.DemiBold))
        title = f"Episode {self.index}"
        title = painter.fontMetrics().elidedText(
            title, Qt.ElideRight, max(80, text_right - text_left)
        )
        painter.drawText(
            QRect(text_left, 29, max(80, text_right - text_left), 24),
            Qt.AlignLeft | Qt.AlignVCenter,
            title,
        )


class EpisodeRangeButton(QToolButton):
    def __init__(self, label: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._arrow_progress = 0.0
        self.arrow_animation = QPropertyAnimation(self, b"arrowProgress", self)
        self.arrow_animation.setDuration(150)
        self.arrow_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.setObjectName("seriesEpisodeRangeButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setPopupMode(QToolButton.InstantPopup)
        self.setText(label)
        self.setFont(app_qfont(11, QFont.DemiBold))
        self.setMinimumSize(198, 40)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        return QSize(max(198, metrics.horizontalAdvance(self.text()) + 62), 40)

    def arrow_progress(self) -> float:
        return self._arrow_progress

    def set_arrow_progress(self, value: float) -> None:
        self._arrow_progress = max(0.0, min(1.0, float(value)))
        self.update()

    arrowProgress = Property(float, arrow_progress, set_arrow_progress)

    def set_menu_open(self, opened: bool) -> None:
        self.arrow_animation.stop()
        self.arrow_animation.setStartValue(self._arrow_progress)
        self.arrow_animation.setEndValue(1.0 if opened else 0.0)
        self.arrow_animation.start()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        border_rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        painter.setPen(QPen(QColor("#6a6a6a" if self.underMouse() else "#585858"), 1))
        painter.setBrush(QColor("#242424"))
        painter.drawRoundedRect(border_rect, 3, 3)

        text_rect = rect.adjusted(12, 0, -46, 0)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(app_qfont(11, QFont.DemiBold))
        label = painter.fontMetrics().elidedText(self.text(), Qt.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, label)

        progress = self._arrow_progress
        center = QPoint(rect.right() - 21, rect.center().y())
        top_y = -3 + (6 * progress)
        tip_y = 4 - (8 * progress)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ffffff"))
        painter.drawPolygon(
            [
                QPointF(center.x() - 5, center.y() + top_y),
                QPointF(center.x() + 5, center.y() + top_y),
                QPointF(center.x(), center.y() + tip_y),
            ]
        )

class ThinCloseButton(QToolButton):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("seriesClose")
        self.setFixedSize(40, 40)
        self.setCursor(Qt.PointingHandCursor)
        self.setAutoRaise(False)
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(20, 20, 20, 220))
        painter.drawEllipse(self.rect().adjusted(0, 0, -1, -1))
        pen = QPen(QColor("#ffffff"), 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        center = self.rect().center()
        half = 6
        painter.drawLine(
            center.x() - half,
            center.y() - half,
            center.x() + half,
            center.y() + half,
        )
        painter.drawLine(
            center.x() + half,
            center.y() - half,
            center.x() - half,
            center.y() + half,
        )


class SeriesHeroOverlay(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        horizontal = QLinearGradient(0, 0, self.width(), 0)
        horizontal.setColorAt(0.0, QColor(0, 0, 0, 225))
        horizontal.setColorAt(0.50, QColor(0, 0, 0, 90))
        horizontal.setColorAt(1.0, QColor(0, 0, 0, 20))
        painter.fillRect(self.rect(), horizontal)
        vertical = QLinearGradient(0, 0, 0, self.height())
        vertical.setColorAt(0.0, QColor(0, 0, 0, 15))
        vertical.setColorAt(0.58, QColor(0, 0, 0, 30))
        vertical.setColorAt(0.82, QColor(24, 24, 24, 175))
        vertical.setColorAt(1.0, QColor(24, 24, 24, 255))
        painter.fillRect(self.rect(), vertical)


class SeriesHero(QWidget):
    play_requested = Signal()
    close_requested = Signal()

    def __init__(self, collection: LibraryCollection) -> None:
        super().__init__()
        self.collection = collection
        representative = collection.representative
        self.pixmap = QPixmap(representative.thumbnail or collection.cover)
        self.preview_path = representative.path
        self.preview_started = False
        self.setMinimumHeight(430)
        self.setMaximumHeight(520)
        self.video_surface = MpvPreviewVideoSurface(self)
        self.preview_controller = MpvController(self.video_surface)
        self.video_surface.hide()
        self.overlay = SeriesHeroOverlay(self)
        self.overlay.setObjectName("seriesHeroOverlay")
        layout = QVBoxLayout(self.overlay)
        layout.setContentsMargins(48, 20, 20, 38)
        top = QHBoxLayout()
        top.addStretch()
        close_button = ThinCloseButton()
        close_button.clicked.connect(self.close_requested)
        top.addWidget(close_button)
        layout.addLayout(top)
        layout.addStretch()
        self.title = QLabel(collection.title)
        self.title.setObjectName("seriesTitle")
        self.meta = QLabel(f"{len(collection.movies)} Episodes")
        self.meta.setObjectName("seriesMeta")
        self.meta.setVisible(len(collection.movies) > 1)
        self.play = QPushButton("▶  Play")
        self.play.setObjectName("seriesPlay")
        self.play.setText("Play")
        self.play.setIcon(build_solid_play_icon())
        self.play.setIconSize(QSize(30, 30))
        self.play.setFixedWidth(132)
        self.play.clicked.connect(self.play_requested)
        layout.addWidget(self.title)
        layout.addSpacing(8)
        layout.addWidget(self.play)
        if len(collection.movies) > 1:
            layout.addSpacing(18)
            layout.addWidget(self.meta)

    def start_preview(self) -> None:
        if self.preview_started:
            return
        self.preview_started = True
        if self.preview_controller.open_preview(self.preview_path):
            self.video_surface.show()
            self.video_surface.lower()
            self.overlay.raise_()

    def stop_preview(self) -> None:
        self.preview_started = False
        self.preview_controller.stop()
        if hasattr(self.video_surface, "detach_player"):
            self.video_surface.detach_player()
        self.video_surface.hide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.video_surface.setGeometry(self.rect())
        self.overlay.setGeometry(self.rect())
        self.video_surface.lower()
        self.overlay.raise_()

    def paintEvent(self, event) -> None:
        if self.video_surface.isVisible():
            return
        painter = QPainter(self)
        draw_cover(painter, self.rect(), self.pixmap)


class PopupSnapshot(QWidget):
    def __init__(
        self,
        pixmap: QPixmap,
        target_geometry: QRect,
        parent: QWidget,
        start_geometry: Optional[QRect] = None,
    ) -> None:
        super().__init__(parent)
        self.pixmap = pixmap
        self.target_geometry = QRect(target_geometry)
        self.start_geometry = QRect(start_geometry or target_geometry)
        self._progress = 0.0
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setGeometry(parent.rect())

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(1.0, float(value)))
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    def paintEvent(self, event) -> None:
        if self.pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        progress = self._progress
        eased = 1.0 - pow(1.0 - progress, 3)
        start = self.start_geometry
        end = self.target_geometry
        x = int(start.x() + (end.x() - start.x()) * eased)
        y = int(start.y() + (end.y() - start.y()) * eased)
        width = max(1, int(start.width() + (end.width() - start.width()) * eased))
        height = max(1, int(start.height() + (end.height() - start.height()) * eased))
        target = QRect(
            x,
            y,
            width,
            height,
        )
        painter.setOpacity(progress)
        painter.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(target), 14, 14)
        painter.setClipPath(clip)
        painter.drawPixmap(target, self.pixmap)


class PlayerLaunchTransitionOverlay(QWidget):
    black_reached = Signal()
    finished = Signal()

    def __init__(self, pixmap: QPixmap, parent: QWidget) -> None:
        super().__init__(parent)
        self.base_pixmap = pixmap.scaled(
            parent.size(),
            Qt.IgnoreAspectRatio,
            Qt.SmoothTransformation,
        )
        self._progress = 0.0
        self.animation = QPropertyAnimation(self, b"progress", self)
        self.animation.setDuration(700)
        self.animation.setEasingCurve(QEasingCurve.InOutCubic)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.finished.connect(self._black_reached)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setGeometry(parent.rect())

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(1.0, float(value)))
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    def start(self) -> None:
        self.show()
        self.raise_()
        self.animation.start()

    def _black_reached(self) -> None:
        self._progress = 1.0
        self.update()
        self.black_reached.emit()

    def finish(self) -> None:
        self.hide()
        self.finished.emit()
        self.deleteLater()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        progress = self._progress
        painter.fillRect(self.rect(), QColor("#000000"))
        scale = 1.0 + (0.095 * progress)
        width = max(1, int(self.width() * scale))
        height = max(1, int(self.height() * scale))
        target = QRect(
            (self.width() - width) // 2,
            (self.height() - height) // 2,
            width,
            height,
        )
        painter.setOpacity(max(0.0, 1.0 - progress * 0.18))
        painter.drawPixmap(target, self.base_pixmap)

        black_progress = max(0.0, (progress - 0.18) / 0.82)
        painter.setOpacity(min(1.0, black_progress * 1.12))
        painter.fillRect(self.rect(), QColor("#000000"))


class SeriesDetailsDialog(QWidget):
    movie_activated = Signal(object)
    subtitle_cache_requested = Signal(object)
    finished = Signal()

    def __init__(
        self,
        collection: LibraryCollection,
        parent: Optional[QWidget] = None,
        origin_geometry: Optional[QRect] = None,
    ) -> None:
        super().__init__(parent)
        self.collection = collection
        self.origin_geometry = QRect(origin_geometry) if origin_geometry is not None else None
        self._closing_animation_started = False
        self._launching_player = False
        self._finished_emitted = False
        self.snapshot_overlay: Optional[PopupSnapshot] = None
        self.popup_animation: Optional[QPropertyAnimation] = None
        self.close_animation_group: Optional[QParallelAnimationGroup] = None
        self._popup_final_geometry: Optional[QRect] = None
        self.setObjectName("seriesDialog")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_StyledBackground)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.hero = SeriesHero(collection)
        self.hero.close_requested.connect(self.request_close)
        self.hero.play_requested.connect(lambda: self._play_movie(collection.representative))
        self.cache_button: Optional[QPushButton] = None
        self.subtitle_cache_busy = False
        self.subtitle_cache_text = "Cache Subtitles"

        scroll = QScrollArea()
        scroll.setObjectName("seriesScroll")
        self.scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        content = QWidget()
        content.setObjectName("seriesContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 28, 0, 28)
        content_layout.setSpacing(0)
        content_layout.setAlignment(Qt.AlignTop)
        self.panel = QWidget()
        self.panel.setObjectName("seriesPanel")
        self.panel.setMinimumWidth(720)
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(0, 0, 0, 42)
        panel_layout.setSpacing(0)
        panel_layout.setAlignment(Qt.AlignTop)
        panel_layout.addWidget(self.hero)

        self.episode_page_start = 0
        self.episode_page_size = 12
        self.episodes_shell: Optional[QWidget] = None
        self.episodes_layout: Optional[QVBoxLayout] = None
        if len(collection.movies) > 1:
            self.episodes_shell = QWidget()
            self.episodes_layout = QVBoxLayout(self.episodes_shell)
            self.episodes_layout.setContentsMargins(48, 28, 48, 0)
            self.episodes_layout.setSpacing(0)
            self._rebuild_episode_rows()
            panel_layout.addWidget(self.episodes_shell)
        else:
            panel_layout.addWidget(self._build_movie_cache_row())
            panel_layout.addStretch()
        content_layout.addWidget(self.panel, 0, Qt.AlignHCenter | Qt.AlignTop)
        self._outside_click_widgets = {content, scroll.viewport()}
        content.installEventFilter(self)
        scroll.viewport().installEventFilter(self)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def set_collection(self, collection: LibraryCollection) -> None:
        self.collection = collection
        self.hero.collection = collection
        self.hero.title.setText(collection.title)
        self.hero.meta.setText(f"{len(collection.movies)} Episodes")
        self.hero.meta.setVisible(len(collection.movies) > 1)
        try:
            self.hero.play_requested.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.hero.play_requested.connect(
            lambda: self._play_movie(collection.representative)
        )
        self.episode_page_start = 0
        self._rebuild_episode_rows()

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            child = item.widget()
            child_layout = item.layout()
            if child is not None:
                child.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)

    def _episode_range_label(self, start: int, end: int) -> str:
        if start == end:
            return f"Episode {start}"
        if end == start + 1:
            return f"Episode {start} and {end}"
        return f"Episodes {start} - {end}"

    def _episode_ranges(self) -> list[tuple[int, int]]:
        total = len(self.collection.movies)
        page_size = self.episode_page_size
        return [
            (start, min(start + page_size, total))
            for start in range(0, total, page_size)
        ]

    def _set_episode_page(self, start: int) -> None:
        self.episode_page_start = start
        self._rebuild_episode_rows()

    def _build_episode_range_button(self) -> QToolButton:
        ranges = self._episode_ranges()
        selected_start = min(self.episode_page_start, max(0, len(self.collection.movies) - 1))
        selected_range = next(
            ((start, end) for start, end in ranges if start <= selected_start < end),
            ranges[0],
        )
        self.episode_page_start = selected_range[0]
        button = EpisodeRangeButton(
            self._episode_range_label(selected_range[0] + 1, selected_range[1])
        )
        menu = QMenu(button)
        menu.setObjectName("seriesEpisodeRangeMenu")

        def sync_menu_width() -> None:
            menu.setFixedWidth(button.width())
            button.set_menu_open(True)

        menu.aboutToShow.connect(sync_menu_width)
        menu.aboutToHide.connect(lambda: button.set_menu_open(False))
        for start, end in ranges:
            label = self._episode_range_label(start + 1, end)
            action = menu.addAction(label)
            action.triggered.connect(lambda _checked=False, page_start=start: self._set_episode_page(page_start))
        button.setMenu(menu)
        return button

    def _build_cache_button(self) -> QPushButton:
        button = QPushButton("Cache Subtitles")
        button.setObjectName("seriesCacheButton")
        button.setFixedWidth(172)
        button.clicked.connect(lambda: self.subtitle_cache_requested.emit(self.collection))
        self.cache_button = button
        self._sync_cache_button()
        return button

    def _sync_cache_button(self) -> None:
        button = self.cache_button
        if button is None:
            return
        button.setEnabled(not self.subtitle_cache_busy)
        button.setText(self.subtitle_cache_text or "Cache Subtitles")

    def _build_movie_cache_row(self) -> QWidget:
        row_widget = QWidget()
        row_widget.setObjectName("seriesMovieCacheRow")
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(48, 28, 48, 0)
        row.setSpacing(0)
        row.addStretch()
        row.addWidget(self._build_cache_button())
        return row_widget

    def _rebuild_episode_rows(self) -> None:
        if self.episodes_layout is None:
            return
        self._clear_layout(self.episodes_layout)
        total = len(self.collection.movies)
        if self.episode_page_start >= total:
            self.episode_page_start = 0
        heading_row = QHBoxLayout()
        heading = QLabel("Episodes")
        heading.setObjectName("seriesEpisodesHeading")
        heading_row.addWidget(heading)
        heading_row.addStretch()
        heading_row.addWidget(self._build_cache_button())
        if total > self.episode_page_size:
            heading_row.addSpacing(12)
            heading_row.addWidget(self._build_episode_range_button())
        else:
            heading_row.addSpacing(12)
            series_name = QLabel(self.collection.title)
            series_name.setObjectName("seriesEpisodesName")
            heading_row.addWidget(series_name)
        self.episodes_layout.addLayout(heading_row)
        self.episodes_layout.addSpacing(16)

        start = self.episode_page_start
        end = min(start + self.episode_page_size, total)
        visible_movies = self.collection.movies[start:end]
        for offset, movie in enumerate(visible_movies):
            episode_number = start + offset + 1
            item = EpisodeListItem(episode_number, movie)
            item.activated.connect(self._play_movie)
            self.episodes_layout.addWidget(item)
            if offset != len(visible_movies) - 1:
                divider = QFrame()
                divider.setObjectName("seriesEpisodeDivider")
                divider.setFixedHeight(1)
                self.episodes_layout.addWidget(divider)
        self.episodes_layout.addStretch()

    def show_centered(self) -> None:
        final_geometry = self._centered_geometry()
        self._popup_final_geometry = QRect(final_geometry)
        start_pos = QPoint(final_geometry.x(), final_geometry.y())
        self.setGeometry(final_geometry)
        self.move(start_pos)
        self._update_panel_width()
        self._apply_rounded_mask()
        self.ensurePolished()
        if self.layout() is not None:
            self.layout().activate()

        parent = self.parentWidget()
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        self.show()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)
        QTimer.singleShot(0, self._update_panel_width)

        if parent is None:
            effect.setOpacity(1.0)
            self.setGraphicsEffect(None)
            self.setGeometry(final_geometry)
            QTimer.singleShot(80, self.hero.start_preview)
            return

        group = QParallelAnimationGroup(self)
        self.popup_animation = group

        position_animation = QPropertyAnimation(self, b"pos", group)
        position_animation.setDuration(460)
        position_animation.setEasingCurve(QEasingCurve.OutCubic)
        position_animation.setStartValue(start_pos)
        position_animation.setEndValue(final_geometry.topLeft())

        opacity_animation = QPropertyAnimation(effect, b"opacity", group)
        opacity_animation.setDuration(430)
        opacity_animation.setEasingCurve(QEasingCurve.OutCubic)
        opacity_animation.setStartValue(0.0)
        opacity_animation.setEndValue(1.0)

        group.addAnimation(position_animation)
        group.addAnimation(opacity_animation)
        group.finished.connect(lambda active=effect: self._finish_open_animation(active))
        group.start()
        QTimer.singleShot(620, lambda active=effect: self._finish_open_animation(active))

    def _render_snapshot(self) -> QPixmap:
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.transparent)
        self.render(pixmap)
        return pixmap

    def _default_start_geometry(self, final_geometry: QRect) -> QRect:
        start = QRect(final_geometry)
        start.moveTop(final_geometry.y() + 18)
        return start

    def _center_scaled_geometry(self, geometry: QRect, scale: float) -> QRect:
        target = QRect(geometry)
        target.moveTop(geometry.y() + 22)
        return target

    def _finish_open_animation(self, effect: QGraphicsOpacityEffect) -> None:
        if self._closing_animation_started:
            return
        if self.popup_animation is not None:
            self.popup_animation.stop()
            self.popup_animation = None
        final_geometry = self._popup_final_geometry or self._centered_geometry()
        self.setGeometry(final_geometry)
        effect.setOpacity(1.0)
        self.setGraphicsEffect(None)
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)
        QTimer.singleShot(80, self.hero.start_preview)


    def _centered_geometry(self) -> QRect:
        parent = self.parentWidget()
        if not parent:
            return self.geometry()
        return QRect(parent.rect())

    def _panel_width(self) -> int:
        parent = self.parentWidget()
        if not parent:
            return 980
        return min(980, max(740, int(parent.width() * 0.70)))

    def _update_panel_width(self) -> None:
        if hasattr(self, "panel"):
            self.panel.setFixedWidth(self._panel_width())
            if len(self.collection.movies) == 1:
                viewport_height = max(
                    self.height(),
                    self.scroll.viewport().height()
                    if hasattr(self, "scroll")
                    else 0,
                )
                outer_gap = 28 * 2
                target_height = max(
                    self.hero.minimumHeight() + 42,
                    viewport_height - outer_gap,
                )
                self.panel.setFixedHeight(target_height)
                self.panel.updateGeometry()
            else:
                self.panel.setMinimumHeight(0)
                self.panel.setMaximumHeight(16777215)

    def recenter(self) -> None:
        if not self._closing_animation_started:
            if self.popup_animation is not None:
                self.popup_animation.stop()
                self.popup_animation = None
            if self.snapshot_overlay is not None:
                self.snapshot_overlay.hide()
                self.snapshot_overlay.deleteLater()
                self.snapshot_overlay = None
            self.setGeometry(self._centered_geometry())

    def closeEvent(self, event) -> None:
        if self._closing_animation_started:
            event.ignore()
            return
        event.ignore()
        self.request_close()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched in getattr(self, "_outside_click_widgets", set())
            and event.type() == QEvent.MouseButtonPress
            and hasattr(event, "button")
            and event.button() == Qt.LeftButton
        ):
            position = event.globalPosition().toPoint()
            panel_position = self.panel.mapFromGlobal(position)
            if not self.panel.rect().contains(panel_position):
                self.request_close()
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def request_close(self) -> None:
        self._start_close_animation()

    def _start_close_animation(self) -> None:
        if self._closing_animation_started:
            return
        self._closing_animation_started = True
        parent = self.parentWidget()
        if self.popup_animation is not None:
            self.popup_animation.stop()
            self.popup_animation = None
        if self.snapshot_overlay is not None:
            self.snapshot_overlay.hide()
            self.snapshot_overlay.deleteLater()
            self.snapshot_overlay = None

        if self.close_animation_group is not None:
            self.close_animation_group.stop()
            self.close_animation_group = None

        if parent is None or not self.isVisible():
            QTimer.singleShot(30, self._finish_close_animation)
            return

        current_geometry = self.geometry()
        end_geometry = self._center_scaled_geometry(current_geometry, 0.72)
        try:
            self.hero.stop_preview()
        except Exception:
            pass
        effect = self.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(effect)
        effect.setOpacity(1.0)
        if parent is not None and hasattr(parent, "_hide_series_backdrop"):
            parent._hide_series_backdrop()
        group = QParallelAnimationGroup(self)
        self.close_animation_group = group

        position_animation = QPropertyAnimation(self, b"pos", group)
        position_animation.setDuration(360)
        position_animation.setEasingCurve(QEasingCurve.InCubic)
        position_animation.setStartValue(current_geometry.topLeft())
        position_animation.setEndValue(end_geometry.topLeft())

        opacity_animation = QPropertyAnimation(effect, b"opacity", group)
        opacity_animation.setDuration(360)
        opacity_animation.setEasingCurve(QEasingCurve.InCubic)
        opacity_animation.setStartValue(1.0)
        opacity_animation.setEndValue(0.0)

        group.addAnimation(position_animation)
        group.addAnimation(opacity_animation)
        group.finished.connect(self._finish_close_animation)
        group.start()
        QTimer.singleShot(500, self._finish_close_animation)

    def _finish_close_animation(self) -> None:
        if self._finished_emitted:
            return
        self.hide()
        effect = self.graphicsEffect()
        if isinstance(effect, QGraphicsOpacityEffect):
            effect.setOpacity(0.0)
        self.setGraphicsEffect(None)
        parent = self.parentWidget()
        if parent is not None and hasattr(parent, "_finish_series_backdrop_hide"):
            parent._finish_series_backdrop_hide()
        if self.popup_animation is not None:
            self.popup_animation.stop()
            self.popup_animation = None
        if self.close_animation_group is not None:
            self.close_animation_group.stop()
            self.close_animation_group = None
        if self.snapshot_overlay is not None:
            self.snapshot_overlay.hide()
            self.snapshot_overlay.deleteLater()
            self.snapshot_overlay = None
        try:
            self.hero.stop_preview()
        except Exception:
            pass
        self._finished_emitted = True
        self.finished.emit()
        self.deleteLater()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.request_close()
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_panel_width()
        self._apply_rounded_mask()

    def _apply_rounded_mask(self) -> None:
        self.clearMask()

    def set_subtitle_cache_busy(self, busy: bool, text: str = "") -> None:
        self.subtitle_cache_busy = busy
        self.subtitle_cache_text = text or ("Caching..." if busy else "Cache Subtitles")
        self._sync_cache_button()

    def set_subtitle_cache_status(self, text: str) -> None:
        self.subtitle_cache_busy = False
        self.subtitle_cache_text = text or "Cache Subtitles"
        self._sync_cache_button()

    def _play_movie(self, movie: Movie) -> None:
        if self._launching_player:
            return
        self._launching_player = True
        self.movie_activated.emit(movie)


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

SUBTITLE_EXTENSIONS = (".ass", ".ssa", ".srt")
SUBTITLE_CODEC_EXTENSIONS = {
    "ass": ".ass",
    "ssa": ".ssa",
    "subrip": ".srt",
    "srt": ".srt",
}
SUBTITLE_FOLDER_NAMES = {"subs", "sub", "subtitle", "subtitles"}
DIALOGUE_STYLE_NAMES = {"main", "default"}
SUBTITLE_STYLE_CACHE_VERSION = "netflix-sans-bold-dialogue-v2"
SUBTITLE_RESUME_PREROLL_MS = 1500


def bundled_font_dir() -> Path:
    bundled = bundle_root() / "font"
    return bundled if bundled.is_dir() else SOURCE_ROOT / "font"


def movie_subtitle_folder(movie: Movie) -> Path:
    video = Path(movie.path)
    folder = Path(movie.collection) if movie.collection else video.parent
    if folder.is_file():
        folder = folder.parent
    return folder


def external_subtitle_source_for_movie(movie: Movie) -> Optional[Path]:
    video = Path(movie.path)
    folder = movie_subtitle_folder(movie)
    if not folder.is_dir():
        diagnostic_log(
            "subtitle.external.folder_missing",
            movie=movie.title,
            video=str(video),
            folder=str(folder),
        )
        return None
    subtitle_dirs: list[Path] = []
    try:
        for child in folder.iterdir():
            if child.is_dir() and child.name.casefold() in SUBTITLE_FOLDER_NAMES:
                subtitle_dirs.append(child)
    except OSError as error:
        diagnostic_log(
            "subtitle.external.folder_scan_error",
            movie=movie.title,
            folder=str(folder),
            error=repr(error),
        )
        return None
    subtitle_dirs.sort(key=lambda path: natural_sort_key(path.name))
    diagnostic_log(
        "subtitle.external.scan",
        movie=movie.title,
        video=str(video),
        folder=str(folder),
        subtitle_dirs=";".join(path.name for path in subtitle_dirs) or "none",
    )
    for subtitle_dir in subtitle_dirs:
        exact_matches = [subtitle_dir / f"{video.stem}{extension}" for extension in SUBTITLE_EXTENSIONS]
        for candidate in exact_matches:
            if candidate.is_file():
                diagnostic_log(
                    "subtitle.external.exact_match",
                    movie=movie.title,
                    source=diagnostic_path_summary(candidate),
                )
                return candidate
        try:
            loose_matches = [
                item
                for item in subtitle_dir.iterdir()
                if item.is_file()
                and item.suffix.casefold() in SUBTITLE_EXTENSIONS
                and item.stem.casefold() == video.stem.casefold()
            ]
        except OSError as error:
            diagnostic_log(
                "subtitle.external.dir_error",
                movie=movie.title,
                subtitle_dir=str(subtitle_dir),
                error=repr(error),
            )
            continue
        if loose_matches:
            loose_matches.sort(
                key=lambda path: (
                    SUBTITLE_EXTENSIONS.index(path.suffix.casefold())
                    if path.suffix.casefold() in SUBTITLE_EXTENSIONS
                    else 99,
                    natural_sort_key(path.name),
                )
            )
            diagnostic_log(
                "subtitle.external.loose_match",
                movie=movie.title,
                source=diagnostic_path_summary(loose_matches[0]),
            )
            return loose_matches[0]
    diagnostic_log("subtitle.external.none", movie=movie.title, video=str(video), folder=str(folder))
    return None


def _read_subtitle_text(path: Path) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return path.read_text(encoding=encoding), encoding
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace"), "utf-8"


def _replace_ass_field(value: str, replacement: str) -> str:
    leading = value[: len(value) - len(value.lstrip())]
    trailing = value[len(value.rstrip()) :]
    return f"{leading}{replacement}{trailing}"


ASS_EVENT_SORT_MARKER = "; DordieWatch: ASS events sorted chronologically"


def _ass_time_to_ms(value: str) -> int:
    try:
        hours, minutes, seconds = value.strip().split(":", 2)
        return int(round((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000))
    except (TypeError, ValueError):
        return 2**63 - 1


def _ass_event_sort_key(item: tuple[int, str]) -> tuple[int, int, int]:
    index, line = item
    try:
        _prefix, payload = line.split(":", 1)
        parts = payload.split(",", 9)
        if len(parts) >= 3:
            return (_ass_time_to_ms(parts[1]), _ass_time_to_ms(parts[2]), index)
    except ValueError:
        pass
    return (2**63 - 1, 2**63 - 1, index)


def _sort_ass_event_lines(lines: list[str]) -> tuple[list[str], int]:
    output: list[str] = []
    index = 0
    reordered_events = 0
    marker_present = any(ASS_EVENT_SORT_MARKER in line for line in lines[:40])
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.casefold() != "[events]":
            output.append(line)
            index += 1
            continue
        output.append(line)
        index += 1
        event_block: list[str] = []
        while index < len(lines):
            current = lines[index]
            current_stripped = current.strip()
            if current_stripped.startswith("[") and current_stripped.endswith("]"):
                break
            event_block.append(current)
            index += 1
        prefix_lines: list[str] = []
        event_lines: list[tuple[int, str]] = []
        suffix_lines: list[str] = []
        seen_event = False
        for block_index, block_line in enumerate(event_block):
            lower = block_line.lstrip().casefold()
            if lower.startswith(("dialogue:", "comment:")):
                seen_event = True
                event_lines.append((block_index, block_line))
            elif not seen_event:
                prefix_lines.append(block_line)
            else:
                suffix_lines.append(block_line)
        sorted_events = sorted(event_lines, key=_ass_event_sort_key)
        if [line for _idx, line in sorted_events] != [line for _idx, line in event_lines]:
            reordered_events += len(event_lines)
        output.extend(prefix_lines)
        output.extend(line for _idx, line in sorted_events)
        output.extend(suffix_lines)
    if not marker_present:
        insert_at = 0
        for idx, line in enumerate(output):
            if line.strip().casefold() == "[script info]":
                insert_at = idx + 1
                break
        newline = "\r\n" if any(line.endswith("\r\n") for line in output[:20]) else "\n"
        output.insert(insert_at, f"{ASS_EVENT_SORT_MARKER}{newline}")
    return output, reordered_events


def ensure_ass_cache_normalized(path: Path) -> None:
    if path.suffix.casefold() not in {".ass", ".ssa"} or not path.is_file():
        return
    try:
        text, encoding = _read_subtitle_text(path)
        if ASS_EVENT_SORT_MARKER in "\n".join(text.splitlines()[:40]):
            return
        lines = text.splitlines(keepends=True)
        sorted_lines, reordered_events = _sort_ass_event_lines(lines)
        path.write_text("".join(sorted_lines), encoding=encoding if encoding != "cp1252" else "utf-8")
        diagnostic_log(
            "subtitle.ass.cache_normalized",
            path=diagnostic_path_summary(path),
            encoding=encoding,
            reordered_events=reordered_events,
        )
    except OSError as error:
        diagnostic_log("subtitle.ass.cache_normalize_error", path=str(path), error=repr(error))


def rewrite_ass_dialogue_styles(source: Path, target: Path) -> None:
    text, encoding = _read_subtitle_text(source)
    lines = text.splitlines(keepends=True)
    output: list[str] = []
    in_styles = False
    format_fields: list[str] = []
    style_names: list[str] = []
    rewritten_styles: list[str] = []
    dialogue_events = 0
    for line in lines:
        stripped = line.strip()
        lower = stripped.casefold()
        if lower.startswith("dialogue:"):
            dialogue_events += 1
        if stripped.startswith("[") and stripped.endswith("]"):
            in_styles = lower in {"[v4+ styles]", "[v4 styles]"}
            output.append(line)
            continue
        if in_styles and lower.startswith("format:"):
            format_fields = [field.strip().casefold() for field in line.split(":", 1)[1].split(",")]
            output.append(line)
            continue
        if in_styles and lower.startswith("style:") and format_fields:
            prefix, payload = line.split(":", 1)
            newline = ""
            if payload.endswith("\r\n"):
                payload = payload[:-2]
                newline = "\r\n"
            elif payload.endswith("\n"):
                payload = payload[:-1]
                newline = "\n"
            parts = payload.split(",", max(0, len(format_fields) - 1))
            try:
                name_index = format_fields.index("name")
                font_index = format_fields.index("fontname")
            except ValueError:
                output.append(line)
                continue
            bold_index = format_fields.index("bold") if "bold" in format_fields else -1
            required_length = max(name_index, font_index, bold_index)
            if len(parts) > required_length:
                style_name_raw = parts[name_index].strip()
                style_name = style_name_raw.casefold()
                style_names.append(style_name_raw)
                if style_name in DIALOGUE_STYLE_NAMES:
                    parts[font_index] = _replace_ass_field(parts[font_index], APP_FONT_FAMILY)
                    if bold_index >= 0:
                        parts[bold_index] = _replace_ass_field(parts[bold_index], "-1")
                    rewritten_styles.append(style_name_raw)
                    line = f"{prefix}:{','.join(parts)}{newline}"
        output.append(line)
    output, reordered_events = _sort_ass_event_lines(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(output), encoding=encoding if encoding != "cp1252" else "utf-8")
    diagnostic_log(
        "subtitle.ass.rewrite",
        source=diagnostic_path_summary(source),
        target=diagnostic_path_summary(target),
        encoding=encoding,
        font=APP_FONT_FAMILY,
        dialogue_events=dialogue_events,
        reordered_events=reordered_events,
        styles=";".join(style_names[:24]) or "none",
        rewritten=";".join(rewritten_styles) or "none",
    )


def cached_external_subtitle_for_movie(
    movie: Movie, cache_dir: Path, create: bool = True
) -> Optional[Path]:
    source = external_subtitle_source_for_movie(movie)
    if source is None:
        diagnostic_log("subtitle.external.cache.no_source", movie=movie.title, create=create)
        return None
    if source.suffix.casefold() not in {".ass", ".ssa"}:
        diagnostic_log(
            "subtitle.external.cache.direct",
            movie=movie.title,
            source=diagnostic_path_summary(source),
            reason="not_ass_ssa",
        )
        return source
    try:
        stat = source.stat()
        identity = f"external|{SUBTITLE_STYLE_CACHE_VERSION}|{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{APP_FONT_FAMILY}"
    except OSError as error:
        diagnostic_log("subtitle.external.cache.stat_error", movie=movie.title, source=str(source), error=repr(error))
        return None
    digest = hashlib.sha1(identity.encode("utf-8", errors="replace")).hexdigest()
    target = cache_dir / f"{digest}{source.suffix.casefold()}"
    if target.is_file():
        ensure_ass_cache_normalized(target)
        diagnostic_log(
            "subtitle.external.cache.hit",
            movie=movie.title,
            source=diagnostic_path_summary(source),
            target=diagnostic_path_summary(target),
            digest=digest,
        )
        return target
    if not create:
        diagnostic_log(
            "subtitle.external.cache.miss_no_create",
            movie=movie.title,
            source=diagnostic_path_summary(source),
            target=str(target),
            digest=digest,
        )
        return None
    try:
        diagnostic_log(
            "subtitle.external.cache.create",
            movie=movie.title,
            source=diagnostic_path_summary(source),
            target=str(target),
            digest=digest,
        )
        rewrite_ass_dialogue_styles(source, target)
        return target
    except OSError as error:
        diagnostic_log("subtitle.cache.error", source=str(source), error=repr(error))
        return source


def subtitle_track_label_from_stream(stream: dict, fallback: str) -> str:
    tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
    title = safe_description(str(tags.get("title", ""))).strip()
    lang = safe_description(str(tags.get("language", ""))).strip().upper()
    codec = safe_description(str(stream.get("codec_name", ""))).strip().upper()
    parts = [title, lang, codec]
    label = " - ".join(part for part in parts if part and part != "UNKNOWN")
    return label or fallback


def probe_subtitle_streams(path: Path, ffprobe: Optional[str]) -> list[dict]:
    if not ffprobe:
        diagnostic_log("subtitle.probe.no_ffprobe", video=str(path))
        return []
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "s",
        "-show_entries",
        "stream=index,codec_name:stream_tags=title,language",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=25,
            **process_options(),
        )
        data = json.loads(result.stdout or "{}")
        streams = [stream for stream in (data.get("streams") or []) if isinstance(stream, dict)]
        diagnostic_log(
            "subtitle.probe.result",
            video=str(path),
            returncode=result.returncode,
            stream_count=len(streams),
            streams=diagnostic_tracks_summary(streams),
            stderr=(result.stderr or "").strip()[:500],
        )
        return streams
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, json.JSONDecodeError) as error:
        diagnostic_log("subtitle.probe.error", video=str(path), error=repr(error))
        return []


def cached_embedded_subtitles_for_movie(
    movie: Movie,
    cache_dir: Path,
    ffprobe: Optional[str],
    ffmpeg: Optional[str],
    create: bool = True,
) -> list[tuple[Path, str, str]]:
    if not ffmpeg or not ffprobe:
        diagnostic_log(
            "subtitle.embedded.tools_missing",
            movie=movie.title,
            ffprobe=bool(ffprobe),
            ffmpeg=bool(ffmpeg),
            create=create,
        )
        return []
    video = Path(movie.path)
    try:
        stat = video.stat()
    except OSError as error:
        diagnostic_log("subtitle.embedded.video_stat_error", movie=movie.title, video=str(video), error=repr(error))
        return []
    tracks: list[tuple[Path, str, str]] = []
    streams = probe_subtitle_streams(video, ffprobe)
    diagnostic_log(
        "subtitle.embedded.scan",
        movie=movie.title,
        video=str(video),
        create=create,
        stream_count=len(streams),
    )
    for stream in streams:
        codec = safe_description(str(stream.get("codec_name", ""))).casefold()
        extension = SUBTITLE_CODEC_EXTENSIONS.get(codec)
        if not extension:
            diagnostic_log(
                "subtitle.embedded.unsupported_codec",
                movie=movie.title,
                stream=stream.get("index"),
                codec=codec,
            )
            continue
        try:
            stream_index = int(stream.get("index"))
        except (TypeError, ValueError):
            diagnostic_log("subtitle.embedded.bad_stream_index", movie=movie.title, stream=stream)
            continue
        label = subtitle_track_label_from_stream(stream, f"Subtitle {len(tracks) + 1}")
        language = safe_description(str((stream.get("tags") or {}).get("language", ""))).strip()
        identity = (
            f"embedded|{SUBTITLE_STYLE_CACHE_VERSION}|{video.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|"
            f"{stream_index}|{codec}|{APP_FONT_FAMILY}"
        )
        digest = hashlib.sha1(identity.encode("utf-8", errors="replace")).hexdigest()
        raw_target = cache_dir / f"{digest}.raw{extension}"
        final_target = cache_dir / f"{digest}{extension}"
        if final_target.is_file():
            ensure_ass_cache_normalized(final_target)
            diagnostic_log(
                "subtitle.embedded.cache.hit",
                movie=movie.title,
                stream=stream_index,
                codec=codec,
                label=label,
                language=language,
                target=diagnostic_path_summary(final_target),
                digest=digest,
            )
        else:
            if not create:
                diagnostic_log(
                    "subtitle.embedded.cache.miss_no_create",
                    movie=movie.title,
                    stream=stream_index,
                    codec=codec,
                    label=label,
                    target=str(final_target),
                    digest=digest,
                )
                continue
            cache_dir.mkdir(parents=True, exist_ok=True)
            command = [
                ffmpeg,
                "-y",
                "-v",
                "error",
                "-i",
                str(video),
                "-map",
                f"0:{stream_index}",
                "-c:s",
                "copy",
                str(raw_target),
            ]
            try:
                diagnostic_log(
                    "subtitle.embedded.extract.start",
                    movie=movie.title,
                    stream=stream_index,
                    codec=codec,
                    label=label,
                    raw=str(raw_target),
                    final=str(final_target),
                )
                result = subprocess.run(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=45,
                    **process_options(),
                )
                if result.returncode != 0 or not raw_target.is_file():
                    diagnostic_log(
                        "subtitle.embedded.extract.failed",
                        video=str(video),
                        stream=stream_index,
                        error=(result.stderr or "").strip()[:500],
                    )
                    continue
                if extension in {".ass", ".ssa"}:
                    rewrite_ass_dialogue_styles(raw_target, final_target)
                else:
                    raw_target.replace(final_target)
                diagnostic_log(
                    "subtitle.embedded.extract.done",
                    movie=movie.title,
                    stream=stream_index,
                    target=diagnostic_path_summary(final_target),
                )
            except (OSError, subprocess.SubprocessError) as error:
                diagnostic_log(
                    "subtitle.embedded.extract.error",
                    video=str(video),
                    stream=stream_index,
                    error=repr(error),
                )
                continue
            finally:
                if raw_target.is_file() and raw_target != final_target:
                    try:
                        raw_target.unlink()
                    except OSError:
                        pass
        if final_target.is_file():
            tracks.append((final_target, label, language))
    diagnostic_log(
        "subtitle.embedded.scan.done",
        movie=movie.title,
        create=create,
        track_count=len(tracks),
        tracks="; ".join(f"{label}|{language}|{path.name}" for path, label, language in tracks),
    )
    return tracks


def cached_subtitle_tracks_for_movie(
    movie: Movie,
    cache_dir: Path,
    ffprobe: Optional[str],
    ffmpeg: Optional[str],
    create: bool = False,
) -> list[tuple[str, str, str, str]]:
    diagnostic_log(
        "subtitle.cache.tracks.start",
        movie=movie.title,
        video=str(movie.path),
        cache_dir=str(cache_dir),
        create=create,
    )
    tracks: list[tuple[str, str, str, str]] = []
    external_subtitle = cached_external_subtitle_for_movie(movie, cache_dir, create=create)
    if external_subtitle is not None:
        tracks.append((str(external_subtitle), "English", "eng", "external"))
    for subtitle_path, label, language in cached_embedded_subtitles_for_movie(
        movie, cache_dir, ffprobe, ffmpeg, create=create
    ):
        tracks.append((str(subtitle_path), label, language, "embedded"))
    diagnostic_log(
        "subtitle.cache.tracks.done",
        movie=movie.title,
        create=create,
        count=len(tracks),
        tracks="; ".join(
            f"{source}|{label}|{language}|{diagnostic_path_summary(path)}"
            for path, label, language, source in tracks
        ) or "none",
    )
    return tracks


class MpvVideoSurface(QOpenGLWidget):
    frame_update_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.player = None
        self.render_context = None
        self.render_qt_context = None
        self._gl_proc_callback = None
        self._last_paint_signature = None
        self._last_paint_log_at = 0.0
        self._last_resize_signature = None
        self.rendering_suspended = False
        self._suspend_skip_logged = False
        self.setAutoFillBackground(False)
        self.frame_update_requested.connect(self.update)
        diagnostic_log("video_surface.init", surface=widget_snapshot(self))

    def set_rendering_suspended(self, suspended: bool, reason: str = "") -> None:
        suspended = bool(suspended)
        if self.rendering_suspended == suspended:
            return
        self.rendering_suspended = suspended
        self._suspend_skip_logged = False
        diagnostic_log(
            "video_surface.rendering_suspended",
            suspended=suspended,
            reason=reason,
            surface=widget_snapshot(self),
        )
        if suspended:
            self._free_render_context(make_current=True)
        else:
            self.update()

    def attach_player(self, player) -> None:
        self.player = player
        diagnostic_log(
            "video_surface.attach_player",
            player_id=id(player),
            context_id=id(self.context()) if self.context() is not None else "none",
            surface=widget_snapshot(self),
        )
        if self.context() is not None and self.context().isValid():
            try:
                self.makeCurrent()
                self._ensure_render_context()
            finally:
                self.doneCurrent()
        self.update()

    def detach_player(self) -> None:
        diagnostic_log("video_surface.detach_player", surface=widget_snapshot(self))
        self._free_render_context(make_current=True)
        self.player = None

    def initializeGL(self) -> None:
        context = QOpenGLContext.currentContext()
        diagnostic_log(
            "video_surface.initialize_gl",
            context_id=id(context) if context is not None else "none",
            valid=bool(context and context.isValid()),
            surface=widget_snapshot(self),
        )
        if context is not None:
            try:
                context.aboutToBeDestroyed.connect(self._context_about_to_be_destroyed)
            except (RuntimeError, TypeError):
                pass
        self._ensure_render_context()

    def paintGL(self) -> None:
        if self.rendering_suspended:
            if not self._suspend_skip_logged:
                self._suspend_skip_logged = True
                diagnostic_log(
                    "video_surface.paint.skipped_suspended",
                    surface=widget_snapshot(self),
                )
            return
        context = QOpenGLContext.currentContext()
        if self.render_context is not None and context is not self.render_qt_context:
            diagnostic_log(
                "video_surface.context_changed",
                old_context_id=id(self.render_qt_context)
                if self.render_qt_context is not None
                else "none",
                new_context_id=id(context) if context is not None else "none",
                surface=widget_snapshot(self),
            )
            self._free_render_context(make_current=False)
        if self.rendering_suspended:
            return
        self._ensure_render_context()
        render_context = self.render_context
        if render_context is None or self.rendering_suspended:
            return
        scale = self.devicePixelRatioF()
        width = max(1, int(self.width() * scale))
        height = max(1, int(self.height() * scale))
        fbo = int(self.defaultFramebufferObject())
        signature = (
            width,
            height,
            fbo,
            id(context) if context is not None else 0,
            id(self.render_context),
        )
        now = time.monotonic()
        if signature != self._last_paint_signature or now - self._last_paint_log_at > 1.5:
            self._last_paint_signature = signature
            self._last_paint_log_at = now
            diagnostic_log(
                "video_surface.paint",
                target=f"{width}x{height}",
                widget=f"{self.width()}x{self.height()}",
                dpr=f"{scale:.3f}",
                fbo=fbo,
                context_id=id(context) if context is not None else "none",
                render_context_id=id(render_context),
            )
        try:
            if self.rendering_suspended:
                return
            render_context.update()
            if self.rendering_suspended:
                return
            render_context.render(
                opengl_fbo={
                    "w": width,
                    "h": height,
                    "fbo": fbo,
                    "internal_format": 0,
                },
                flip_y=True,
            )
            if not self.rendering_suspended:
                render_context.report_swap()
        except Exception as error:
            diagnostic_log("video_surface.paint.error", error=repr(error))

    def resizeGL(self, _width: int, _height: int) -> None:
        signature = (
            int(_width),
            int(_height),
            self.width(),
            self.height(),
            self.devicePixelRatioF(),
        )
        if signature != self._last_resize_signature:
            self._last_resize_signature = signature
            diagnostic_log(
                "video_surface.resize_gl",
                gl_size=f"{_width}x{_height}",
                widget=f"{self.width()}x{self.height()}",
                dpr=f"{self.devicePixelRatioF():.3f}",
                surface=widget_snapshot(self),
            )
        self.update()

    def _context_about_to_be_destroyed(self) -> None:
        diagnostic_log(
            "video_surface.context_about_to_be_destroyed",
            context_id=id(QOpenGLContext.currentContext())
            if QOpenGLContext.currentContext() is not None
            else "none",
            tracked_context_id=id(self.render_qt_context)
            if self.render_qt_context is not None
            else "none",
        )
        self._free_render_context(make_current=True)

    def _free_render_context(self, make_current: bool) -> None:
        if self.render_context is None:
            self.render_qt_context = None
            self._gl_proc_callback = None
            return
        diagnostic_log(
            "video_surface.render_context.free",
            render_context_id=id(self.render_context),
            qt_context_id=id(self.render_qt_context)
            if self.render_qt_context is not None
            else "none",
            make_current=make_current,
        )
        made_current = False
        try:
            if make_current:
                self.makeCurrent()
                made_current = True
            self.render_context.free()
        except Exception:
            pass
        finally:
            self.render_context = None
            self.render_qt_context = None
            self._gl_proc_callback = None
            if made_current:
                try:
                    self.doneCurrent()
                except Exception:
                    pass

    def _ensure_render_context(self) -> None:
        if (
            self.rendering_suspended
            or self.render_context is not None
            or self.player is None
            or mpv is None
        ):
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
            self.render_qt_context = context
            self.render_context.update_cb = self.frame_update_requested.emit
            diagnostic_log(
                "video_surface.render_context.create",
                render_context_id=id(self.render_context),
                qt_context_id=id(context),
                surface=widget_snapshot(self),
            )
        except Exception as error:
            self.render_context = None
            self.render_qt_context = None
            diagnostic_log("video_surface.render_context.create.error", error=repr(error))


class MpvPreviewVideoSurface(QOpenGLWidget):
    frame_update_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.player = None
        self.render_context = None
        self.render_qt_context = None
        self._gl_proc_callback = None
        self._last_paint_signature = None
        self._last_paint_log_at = 0.0
        self._last_resize_signature = None
        self.setAutoFillBackground(False)
        self.frame_update_requested.connect(self.update)
        diagnostic_log("preview_surface.init", surface=widget_snapshot(self))

    def attach_player(self, player) -> None:
        self.player = player
        diagnostic_log(
            "preview_surface.attach_player",
            player_id=id(player),
            context_id=id(self.context()) if self.context() is not None else "none",
            surface=widget_snapshot(self),
        )
        if self.context() is not None and self.context().isValid():
            try:
                self.makeCurrent()
                self._ensure_render_context()
            finally:
                self.doneCurrent()
        self.update()

    def detach_player(self) -> None:
        diagnostic_log("preview_surface.detach_player", surface=widget_snapshot(self))
        self._free_render_context(make_current=True)
        self.player = None

    def initializeGL(self) -> None:
        context = QOpenGLContext.currentContext()
        diagnostic_log(
            "preview_surface.initialize_gl",
            context_id=id(context) if context is not None else "none",
            valid=bool(context and context.isValid()),
            surface=widget_snapshot(self),
        )
        if context is not None:
            try:
                context.aboutToBeDestroyed.connect(self._context_about_to_be_destroyed)
            except (RuntimeError, TypeError):
                pass
        self._ensure_render_context()

    def paintGL(self) -> None:
        context = QOpenGLContext.currentContext()
        if self.render_context is not None and context is not self.render_qt_context:
            diagnostic_log(
                "preview_surface.context_changed",
                old_context_id=id(self.render_qt_context)
                if self.render_qt_context is not None
                else "none",
                new_context_id=id(context) if context is not None else "none",
                surface=widget_snapshot(self),
            )
            self._free_render_context(make_current=False)
        self._ensure_render_context()
        if self.render_context is None:
            return
        scale = self.devicePixelRatioF()
        width = max(1, int(self.width() * scale))
        height = max(1, int(self.height() * scale))
        fbo = int(self.defaultFramebufferObject())
        signature = (
            width,
            height,
            fbo,
            id(context) if context is not None else 0,
            id(self.render_context),
        )
        now = time.monotonic()
        if signature != self._last_paint_signature or now - self._last_paint_log_at > 1.5:
            self._last_paint_signature = signature
            self._last_paint_log_at = now
            diagnostic_log(
                "preview_surface.paint",
                target=f"{width}x{height}",
                widget=f"{self.width()}x{self.height()}",
                dpr=f"{scale:.3f}",
                fbo=fbo,
                context_id=id(context) if context is not None else "none",
                render_context_id=id(self.render_context),
            )
        try:
            self.render_context.update()
            self.render_context.render(
                opengl_fbo={
                    "w": width,
                    "h": height,
                    "fbo": fbo,
                    "internal_format": 0,
                },
                flip_y=True,
            )
            self.render_context.report_swap()
        except Exception as error:
            diagnostic_log("preview_surface.paint.error", error=repr(error))

    def resizeGL(self, _width: int, _height: int) -> None:
        signature = (
            int(_width),
            int(_height),
            self.width(),
            self.height(),
            self.devicePixelRatioF(),
        )
        if signature != self._last_resize_signature:
            self._last_resize_signature = signature
            diagnostic_log(
                "preview_surface.resize_gl",
                gl_size=f"{_width}x{_height}",
                widget=f"{self.width()}x{self.height()}",
                dpr=f"{self.devicePixelRatioF():.3f}",
                surface=widget_snapshot(self),
            )
        self.update()

    def _context_about_to_be_destroyed(self) -> None:
        diagnostic_log(
            "preview_surface.context_about_to_be_destroyed",
            context_id=id(QOpenGLContext.currentContext())
            if QOpenGLContext.currentContext() is not None
            else "none",
            tracked_context_id=id(self.render_qt_context)
            if self.render_qt_context is not None
            else "none",
        )
        self._free_render_context(make_current=True)

    def _free_render_context(self, make_current: bool) -> None:
        if self.render_context is None:
            self.render_qt_context = None
            self._gl_proc_callback = None
            return
        diagnostic_log(
            "preview_surface.render_context.free",
            render_context_id=id(self.render_context),
            qt_context_id=id(self.render_qt_context)
            if self.render_qt_context is not None
            else "none",
            make_current=make_current,
        )
        made_current = False
        try:
            if make_current:
                self.makeCurrent()
                made_current = True
            self.render_context.free()
        except Exception:
            pass
        finally:
            self.render_context = None
            self.render_qt_context = None
            self._gl_proc_callback = None
            if made_current:
                try:
                    self.doneCurrent()
                except Exception:
                    pass

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
            self.render_qt_context = context
            self.render_context.update_cb = self.frame_update_requested.emit
            diagnostic_log(
                "preview_surface.render_context.create",
                render_context_id=id(self.render_context),
                qt_context_id=id(context),
                surface=widget_snapshot(self),
            )
        except Exception as error:
            self.render_context = None
            self.render_qt_context = None
            diagnostic_log("preview_surface.render_context.create.error", error=repr(error))


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
        self._using_cached_embedded_subtitles = False
        self._last_valid_time_ms = 0
        self._last_valid_length_ms = 0
        self._last_subtitle_track_signature = ""
        self._last_selected_subtitle = "unset"
        self._last_subtitle_text_state = "unset"
        self._subtitle_empty_deadlines_logged: set[float] = set()
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._poll)
        if mpv is not None and MPV_RUNTIME is not None:
            try:
                options = {
                    "idle": True,
                    "vo": "libmpv",
                    "input_default_bindings": False,
                    "input_vo_keyboard": False,
                    "osc": False,
                    "osd_level": 0,
                    "config": False,
                    "terminal": False,
                    "hwdec": "auto-safe",
                    "sub_auto": "no",
                    "sub_ass_override": "no",
                    "audio_display": "no",
                    "keep_open": False,
                }
                font_dir = bundled_font_dir()
                if font_dir.is_dir():
                    options["sub_fonts_dir"] = str(font_dir)
                self.player = mpv.MPV(
                    **options,
                )
                diagnostic_log(
                    "mpv.controller.init",
                    player_id=id(self.player),
                    options=json.dumps(options, sort_keys=True),
                    surface_type=type(surface).__name__,
                )
                if hasattr(self.surface, "attach_player"):
                    self.surface.attach_player(self.player)
                self.fit_video()
            except Exception as error:
                diagnostic_log("mpv.controller.init.error", error=repr(error))
                self.error.emit(str(error))

    @property
    def available(self) -> bool:
        return self.player is not None

    def _mpv_property(self, name: str, default=None):
        if not self.player:
            return default
        try:
            return getattr(self.player, name.replace("-", "_"))
        except Exception:
            try:
                return self.player.command("get_property", name)
            except Exception:
                return default

    def _log_subtitle_state(self, event: str, **fields) -> None:
        if not self.player:
            diagnostic_log(event, player="none", **fields)
            return
        try:
            tracks = self.player.track_list or []
        except Exception as error:
            tracks = []
            fields["track_error"] = repr(error)
        sub_tracks = [
            track
            for track in tracks
            if isinstance(track, dict) and str(track.get("type", "")).casefold() == "sub"
        ]
        sub_text = self._mpv_property("sub-text", "")
        if sub_text is None:
            sub_text = ""
        diagnostic_log(
            event,
            generation=self._generation,
            sid=self._mpv_property("sid", "unknown"),
            secondary_sid=self._mpv_property("secondary-sid", "unknown"),
            sub_visibility=self._mpv_property("sub-visibility", "unknown"),
            sub_pos=self._mpv_property("sub-pos", "unknown"),
            current_ms=self.time(),
            length_ms=self.length(),
            paused=self._mpv_property("pause", "unknown"),
            idle=self._mpv_property("core-idle", "unknown"),
            sub_track_count=len(sub_tracks),
            sub_tracks=diagnostic_tracks_summary(sub_tracks),
            sub_text_empty=not bool(str(sub_text).strip()),
            sub_text_preview=str(sub_text).strip()[:120],
            **fields,
        )

    def _schedule_subtitle_state_logs(self, generation: int, prefix: str) -> None:
        for delay in (40, 120, 260, 600, 1200, 2500, 5000):
            QTimer.singleShot(
                delay,
                lambda active=generation, marker=delay: self._run_if_current(
                    active,
                    lambda: self._log_subtitle_state(f"{prefix}.{marker}ms"),
                ),
            )

    def open(
        self,
        path: str,
        start_ms: int = 0,
        volume: int = 80,
        autoplay: bool = True,
        subtitle_tracks: Optional[list[tuple[str, str, str, str]]] = None,
    ) -> bool:
        if not self.available:
            diagnostic_log("mpv.open.unavailable", path=path)
            self.error.emit("The bundled playback engine could not be loaded.")
            return False
        try:
            self._generation += 1
            generation = self._generation
            self._opened_at = time.monotonic()
            self._has_media = True
            self._ended_emitted = False
            self._last_valid_time_ms = 0
            self._last_valid_length_ms = 0
            self._last_subtitle_track_signature = ""
            self._last_selected_subtitle = "unset"
            self._last_subtitle_text_state = "unset"
            self._subtitle_empty_deadlines_logged.clear()
            managed_subtitles = list(subtitle_tracks or [])
            self._using_cached_embedded_subtitles = any(
                len(track) >= 4 and track[3] == "embedded" for track in managed_subtitles
            )
            diagnostic_log(
                "mpv.open",
                generation=generation,
                path=path,
                start_ms=start_ms,
                volume=volume,
                autoplay=autoplay,
                subtitle_tracks=len(managed_subtitles),
                subtitle_track_details="; ".join(
                    f"{source}|{title}|{language}|{diagnostic_path_summary(subtitle_path)}"
                    for subtitle_path, title, language, source in managed_subtitles
                ) or "none",
                cached_embedded=self._using_cached_embedded_subtitles,
                surface=widget_snapshot(self.surface),
            )
            defer_autoplay_for_subtitles = bool(autoplay and managed_subtitles)
            self.player.volume = max(0, min(100, int(volume)))
            self.player.mute = False
            self.player.pause = True if defer_autoplay_for_subtitles else not autoplay
            self.player.command("loadfile", str(path), "replace")
            self.player.pause = True if defer_autoplay_for_subtitles else not autoplay
            self._schedule_subtitle_state_logs(generation, "mpv.subtitle.state.after_open")
            if managed_subtitles:
                QTimer.singleShot(
                    35,
                    lambda tracks=managed_subtitles, active=generation, start=start_ms, release=defer_autoplay_for_subtitles: self._run_if_current(
                        active,
                        lambda: self.add_managed_subtitles(
                            tracks,
                            start_after=release,
                            start_ms=start,
                        ),
                    ),
                )
            self.fit_video()
            QTimer.singleShot(
                120,
                lambda: self._run_if_current(generation, self.fit_video),
            )
            if start_ms > 0 and not managed_subtitles:
                QTimer.singleShot(
                    250,
                    lambda: self._run_if_current(
                        generation, lambda: self.set_time(start_ms)
                    ),
                )
            self.timer.start()
            return True
        except Exception as error:
            diagnostic_log("mpv.open.error", path=path, error=repr(error))
            self.error.emit(str(error))
            return False

    def open_preview(self, path: str) -> bool:
        if not self.available:
            return False
        try:
            self._generation += 1
            diagnostic_log("mpv.preview.open", path=path, generation=self._generation)
            self._opened_at = time.monotonic()
            self._has_media = True
            self._ended_emitted = False
            for option, value in (
                ("loop-file", "inf"),
                ("sid", "no"),
                ("aid", "no"),
            ):
                try:
                    self.player.command("set", option, value)
                except Exception:
                    pass
            self.player.volume = 0
            self.player.mute = True
            self.player.pause = False
            self.player.command("loadfile", str(path), "replace")
            self.fit_video()
            self.timer.start()
            return True
        except Exception as error:
            diagnostic_log("mpv.preview.open.error", path=path, error=repr(error))
            return False

    def _run_if_current(self, generation: int, action) -> None:
        if generation == self._generation and self.player is not None:
            action()

    def add_managed_subtitles(
        self,
        tracks: list[tuple[str, str, str, str]],
        start_after: bool = False,
        start_ms: int = 0,
    ) -> None:
        if not self.player:
            return
        diagnostic_log(
            "mpv.subtitle.managed_add.start",
            generation=self._generation,
            count=len(tracks),
            start_after=start_after,
            start_ms=start_ms,
            tracks="; ".join(
                f"{source}|{title}|{language}|{diagnostic_path_summary(subtitle_path)}"
                for subtitle_path, title, language, source in tracks
            ) or "none",
        )
        first_added = True
        for subtitle_path, title, language, source_kind in tracks:
            if not subtitle_path:
                diagnostic_log("mpv.subtitle.managed_add.skip_empty", generation=self._generation)
                continue
            diagnostic_log(
                "mpv.subtitle.managed_add.before",
                generation=self._generation,
                path=diagnostic_path_summary(subtitle_path),
                title=title,
                language=language,
                source=source_kind,
            )
            flag = "select" if first_added else "auto"
            try:
                self.player.command(
                    "sub-add",
                    str(subtitle_path),
                    flag,
                    title or "English",
                    language or "eng",
                )
                first_added = False
                diagnostic_log(
                    "mpv.subtitle.managed_add",
                    path=subtitle_path,
                    title=title,
                    language=language,
                    source=source_kind,
                    flag=flag,
                )
            except Exception as error:
                diagnostic_log(
                    "mpv.subtitle.managed_add.error",
                    path=subtitle_path,
                    title=title,
                    error=repr(error),
                )
        tracks = self.subtitle_tracks()
        self._log_subtitle_state("mpv.subtitle.managed_add.after", listed_tracks=len(tracks))
        if tracks:
            self.select_subtitle(tracks[0][0])
            diagnostic_log(
                "mpv.subtitle.managed_selected",
                track_id=tracks[0][0],
                label=tracks[0][1],
            )
        target_ms = max(0, int(start_ms))
        if start_after:
            self.set_paused(False)
            if target_ms > 0:
                generation = self._generation
                QTimer.singleShot(
                    80,
                    lambda active=generation, target=target_ms, total=len(tracks): self._run_if_current(
                        active,
                        lambda: self._seek_after_subtitles_ready(active, target, total, 0),
                    ),
                )
            else:
                self._log_subtitle_state(
                    "mpv.subtitle.managed_add.start_at_zero", selected_tracks=len(tracks)
                )
        else:
            self.set_time(target_ms)
            self._log_subtitle_state("mpv.subtitle.managed_add.after_seek", selected_tracks=len(tracks))

    def _seek_after_subtitles_ready(
        self, generation: int, target_ms: int, selected_tracks: int, attempt: int
    ) -> None:
        if generation != self._generation or not self.player:
            return
        state = self.state() or {}
        idle = bool(state.get("idle"))
        if idle and attempt < 12:
            diagnostic_log(
                "mpv.subtitle.deferred_seek.wait",
                generation=generation,
                attempt=attempt,
                target_ms=target_ms,
                current_ms=self.time(),
                state=state,
            )
            QTimer.singleShot(
                80,
                lambda active=generation, target=target_ms, total=selected_tracks, next_attempt=attempt + 1: self._run_if_current(
                    active,
                    lambda: self._seek_after_subtitles_ready(
                        active, target, total, next_attempt
                    ),
                ),
            )
            return
        seek_ms = max(0, target_ms - SUBTITLE_RESUME_PREROLL_MS) if target_ms > 0 else 0
        diagnostic_log(
            "mpv.subtitle.deferred_seek.apply",
            generation=generation,
            attempt=attempt,
            target_ms=target_ms,
            seek_ms=seek_ms,
            preroll_ms=target_ms - seek_ms,
            current_ms=self.time(),
            state=state,
        )
        self.set_time(seek_ms)
        self._log_subtitle_state(
            "mpv.subtitle.managed_add.after_deferred_seek",
            selected_tracks=selected_tracks,
        )
        QTimer.singleShot(
            160,
            lambda active=generation: self._run_if_current(
                active,
                lambda: self._log_subtitle_state("mpv.subtitle.state.after_deferred_seek.160ms"),
            ),
        )

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
        diagnostic_log("mpv.fit_video")
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
        diagnostic_log("mpv.stop", generation=self._generation)
        self._generation += 1
        self.timer.stop()
        if self.player:
            try:
                self.player.command("set", "loop-file", "no")
            except Exception:
                pass
            try:
                self.player.stop()
            except Exception:
                pass
        self._has_media = False
        self._using_cached_embedded_subtitles = False
        self._opened_at = 0.0
        self._last_playing = False
        self._ended_emitted = False
        self._last_valid_time_ms = 0
        self._last_valid_length_ms = 0

    def quiet_for_close(self) -> None:
        diagnostic_log("mpv.quiet_for_close")
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
        new_value = not bool(self.player.pause)
        diagnostic_log("mpv.toggle_pause", paused=new_value)
        self.player.pause = new_value

    def set_paused(self, paused: bool) -> None:
        if self.player:
            try:
                diagnostic_log("mpv.set_paused", paused=paused)
                self.player.pause = bool(paused)
            except Exception:
                pass

    def set_time(self, milliseconds: int) -> None:
        if self.player:
            try:
                seconds = max(0, int(milliseconds)) / 1000.0
                diagnostic_log("mpv.seek", milliseconds=milliseconds)
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

    def set_muted(self, muted: bool) -> None:
        if self.player:
            try:
                self.player.mute = bool(muted)
            except Exception:
                pass

    def set_rate(self, rate: float) -> None:
        if self.player:
            self.player.speed = max(0.25, min(4.0, float(rate)))

    def _track_description(self, track: dict) -> str:
        title = safe_description(str(track.get("title", ""))).strip()
        is_external = bool(
            track.get("external")
            or track.get("external-filename")
            or track.get("external_filename")
        )
        if is_external and title:
            return title
        parts = [
            title,
            safe_description(str(track.get("lang", ""))).upper(),
            safe_description(str(track.get("codec", ""))).upper(),
        ]
        label = " - ".join(part for part in parts if part and part != "UNKNOWN")
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
        tracks = self._tracks_of_type("sub")
        if self._using_cached_embedded_subtitles:
            tracks = [
                track
                for track in tracks
                if bool(
                    track.get("external")
                    or track.get("external-filename")
                    or track.get("external_filename")
                )
            ]
        return [
            (int(track.get("id")), self._track_description(track))
            for track in tracks
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
            before = self._mpv_property("sid", "unknown")
            requested = "no" if int(track_id) == -1 else int(track_id)
            try:
                self.player.sid = requested
                after = self._mpv_property("sid", "unknown")
                diagnostic_log(
                    "mpv.subtitle.select",
                    generation=self._generation,
                    requested=requested,
                    before=before,
                    after=after,
                    tracks=diagnostic_tracks_summary(self.player.track_list or []),
                )
            except Exception as error:
                diagnostic_log(
                    "mpv.subtitle.select.error",
                    generation=self._generation,
                    requested=requested,
                    before=before,
                    error=repr(error),
                )

    def _emit_ended_once(self, reason: str, current: int, length: int) -> None:
        if self._ended_emitted:
            return
        diagnostic_log(
            "mpv.ended",
            reason=reason,
            current_ms=current,
            length_ms=length,
            last_current_ms=self._last_valid_time_ms,
            last_length_ms=self._last_valid_length_ms,
        )
        self._ended_emitted = True
        self._has_media = False
        self.ended.emit()

    def _poll(self) -> None:
        if not self.player:
            return
        current = self.time()
        length = self.length()
        state = self.state()
        if length > 0:
            self._last_valid_length_ms = length
        if current > 0:
            self._last_valid_time_ms = current
        try:
            track_list = self.player.track_list or []
        except Exception:
            track_list = []
        sub_tracks = [
            track
            for track in track_list
            if isinstance(track, dict) and str(track.get("type", "")).casefold() == "sub"
        ]
        sub_signature = diagnostic_tracks_summary(sub_tracks)
        if sub_signature != self._last_subtitle_track_signature:
            self._last_subtitle_track_signature = sub_signature
            diagnostic_log(
                "mpv.subtitle.tracks_changed",
                generation=self._generation,
                current_ms=current,
                length_ms=length,
                count=len(sub_tracks),
                tracks=sub_signature or "none",
            )
        sid_value = str(self._mpv_property("sid", "unknown"))
        if sid_value != self._last_selected_subtitle:
            self._last_selected_subtitle = sid_value
            diagnostic_log(
                "mpv.subtitle.sid_changed",
                generation=self._generation,
                current_ms=current,
                length_ms=length,
                sid=sid_value,
            )
        sub_text = str(self._mpv_property("sub-text", "") or "").strip()
        sub_text_state = "text" if sub_text else "empty"
        if sub_text_state != self._last_subtitle_text_state:
            self._last_subtitle_text_state = sub_text_state
            diagnostic_log(
                "mpv.subtitle.text_state_changed",
                generation=self._generation,
                current_ms=current,
                length_ms=length,
                state=sub_text_state,
                preview=sub_text[:120],
            )
        for deadline in (1.0, 3.0, 8.0):
            if (
                deadline not in self._subtitle_empty_deadlines_logged
                and self.opening_age() >= deadline
                and sid_value not in {"no", "-1", "None", "unknown"}
                and not sub_text
            ):
                self._subtitle_empty_deadlines_logged.add(deadline)
                diagnostic_log(
                    "mpv.subtitle.text_still_empty",
                    generation=self._generation,
                    age_seconds=deadline,
                    current_ms=current,
                    length_ms=length,
                    sid=sid_value,
                    sub_tracks=sub_signature or "none",
                )
        self.position_changed.emit(current, length)
        playing = self.is_playing()
        if playing != self._last_playing:
            self._last_playing = playing
            diagnostic_log(
                "mpv.playing_changed",
                playing=playing,
                current_ms=current,
                length_ms=length,
                state=state,
            )
            self.playing_changed.emit(playing)
        try:
            if bool(self.player.eof_reached):
                self._emit_ended_once("eof_reached", current, length)
                return
        except Exception:
            pass
        if (
            self._has_media
            and not self._ended_emitted
            and self.opening_age() > 2.0
            and current == 0
            and length == 0
            and bool(state and state.get("idle"))
            and self._last_valid_length_ms > 0
            and self._last_valid_time_ms >= max(0, self._last_valid_length_ms - 2500)
        ):
            self._emit_ended_once("idle_after_near_end", current, length)


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


class StaticIconButton(HoverIconButton):
    def set_hovered(self, hovered: bool) -> None:
        self._hovered = False
        self._size_animation.stop()
        self.setIconSize(self.base_icon_size)

    def setDown(self, down: bool) -> None:
        super().setDown(False)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.window().activateWindow()
            self.window().setFocus(Qt.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled():
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PlayerEpisodeMenuItem(QWidget):
    activated = Signal(object)

    def __init__(self, index: int, movie: Movie, active: bool) -> None:
        super().__init__()
        self.index = index
        self.movie = movie
        self.active = active
        self.thumbnail = QPixmap(episode_still_for_movie(movie) or movie.thumbnail)
        self.setCursor(Qt.ArrowCursor if active else Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFixedHeight(220 if active else 86)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and not self.active:
            self.activated.emit(self.movie)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        active_rect = rect.adjusted(1, 1, -2, -2)
        if self.active:
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.setBrush(QColor(24, 24, 24, 230))
            painter.drawRect(active_rect)
        painter.setPen(QColor("#f2f2f2"))
        painter.setFont(app_qfont(12, QFont.Bold))
        painter.drawText(QRect(24, 21, 34, 30), Qt.AlignCenter, str(self.index))
        title = f"Episode {self.index}"
        title_rect = QRect(76, 22, max(160, self.width() - 276), 28)
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, title)

        progress_width = 132
        progress_x = max(350, self.width() - progress_width - 126)
        progress_y = 32
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#8a8a8a"))
        painter.drawRect(QRect(progress_x, progress_y, progress_width, 2))
        if self.movie.duration_ms and self.movie.progress_ms:
            ratio = max(0.0, min(1.0, self.movie.progress_ms / self.movie.duration_ms))
            painter.setBrush(QColor("#e50914"))
            painter.drawRect(QRect(progress_x, progress_y, int(progress_width * ratio), 2))

        if not self.active:
            return

        thumb_rect = QRect(76, 74, 220, 124)
        clip = QPainterPath()
        clip.addRoundedRect(thumb_rect, 1, 1)
        painter.save()
        painter.setClipPath(clip)
        draw_frame_fit(painter, thumb_rect, self.thumbnail)
        painter.fillRect(thumb_rect, QColor(0, 0, 0, 90))
        painter.restore()

        painter.setPen(QColor("#ffffff"))
        painter.setFont(app_qfont(12, QFont.Bold))
        bars_x = thumb_rect.x() + 34
        bars_y = thumb_rect.y() + 49
        for offset, height in ((0, 16), (5, 24), (10, 18), (15, 28), (20, 13)):
            painter.drawLine(
                bars_x + offset,
                bars_y + (28 - height) // 2,
                bars_x + offset,
                bars_y + (28 + height) // 2,
            )
        painter.drawText(
            QRect(thumb_rect.x() + 70, thumb_rect.y() + 44, 130, 34),
            Qt.AlignLeft | Qt.AlignVCenter,
            "Now Playing",
        )


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


class NativePlayerResizeFilter(QAbstractNativeEventFilter):
    WM_ENTERSIZEMOVE = 0x0231
    WM_EXITSIZEMOVE = 0x0232
    WM_SIZING = 0x0214
    WM_WINDOWPOSCHANGED = 0x0047

    def __init__(self, window: "DordieWatchWindow") -> None:
        super().__init__()
        self.window = window

    def nativeEventFilter(self, event_type, message):
        if sys.platform != "win32":
            return False, 0
        try:
            native_message = ctypes.wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError):
            return False, 0

        if native_message.message not in {
            self.WM_ENTERSIZEMOVE,
            self.WM_EXITSIZEMOVE,
        }:
            return False, 0
        if not self._belongs_to_player_window(int(native_message.hWnd)):
            return False, 0

        player = self.window.player
        if native_message.message == self.WM_ENTERSIZEMOVE:
            player.begin_interactive_resize()
        elif native_message.message == self.WM_EXITSIZEMOVE:
            player.end_interactive_resize()
        return False, 0

    def _belongs_to_player_window(self, hwnd: int) -> bool:
        if self.window.pages.currentWidget() is not self.window.player:
            return False
        try:
            window_hwnd = int(self.window.winId())
        except RuntimeError:
            return False
        if hwnd == window_hwnd:
            return True
        try:
            return bool(ctypes.windll.user32.IsChild(window_hwnd, hwnd))
        except Exception:
            return False


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
    font = app_qfont(13)
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
    elif kind == "next":
        path = QPainterPath()
        path.moveTo(8, 7)
        path.lineTo(22, 16)
        path.lineTo(8, 25)
        path.closeSubpath()
        painter.setPen(QPen(QColor("#ffffff"), 2.1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        painter.drawLine(25, 7, 25, 25)
    elif kind == "episodes":
        layer_pen = QPen(QColor("#ffffff"), 2.45, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(layer_pen)
        painter.setBrush(Qt.NoBrush)

        middle = QPainterPath()
        middle.moveTo(11.0, 11.0)
        middle.lineTo(27.5, 11.0)
        middle.lineTo(27.5, 22.0)
        painter.drawPath(middle)
        painter.drawRoundedRect(QRectF(5.0, 16.0, 18.5, 10.5), 1.8, 1.8)
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
        self.ffmpeg = find_binary("ffmpeg")
        self.ffprobe = find_binary("ffprobe")
        self.movie: Optional[Movie] = None
        self.playlist: list[Movie] = []
        self.playlist_title = ""
        self.playlist_index = -1
        self.episode_menu_page_size = 12
        self.episode_menu_page_start = 0
        self.playback_blackout_token = 0
        self.fullscreen_fade_animation: Optional[QPropertyAnimation] = None
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
        self.interactive_resizing = False
        self.fullscreen_recovery_generation = 0
        self.menu_open = False
        self.track_panel: Optional[QFrame] = None
        self.routed_control_press: Optional[HoverIconButton] = None
        self.dismiss_click_active = False
        self.ignore_click_release = False
        self.control_hover_widgets: tuple[QWidget, ...] = ()
        self.last_subtitle_selection: int = -1
        self.last_nonzero_volume = max(1, int(settings.get("volume", 80)))
        self._last_resize_log_signature = None
        self._last_layout_log_signature = None
        self._last_pointer_log_at = 0.0
        self._last_pointer_log_pos = None
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
        self.playback_blackout = QFrame(self.overlay)
        self.playback_blackout.setObjectName("playerBlackout")
        self.playback_blackout.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.playback_blackout.hide()

        self.fullscreen_fade = QFrame(self)
        self.fullscreen_fade.setObjectName("playerBlackout")
        self.fullscreen_fade.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.fullscreen_fade_opacity = QGraphicsOpacityEffect(self.fullscreen_fade)
        self.fullscreen_fade.setGraphicsEffect(self.fullscreen_fade_opacity)
        self.fullscreen_fade_opacity.setOpacity(0.0)
        self.fullscreen_fade.hide()

        self.video_surface = MpvVideoSurface(self)
        self.video_surface.setObjectName("videoSurface")
        self.video_surface.setMouseTracking(True)
        self.video_surface.installEventFilter(self)
        self.controller = MpvController(self.video_surface)
        self._connect_controller_signals(self.controller)

        self.top_bar = QFrame(self.overlay)
        self.top_bar.setObjectName("playerTop")
        self.top_bar.setMouseTracking(True)
        self.top_bar.installEventFilter(self)
        self.top_opacity = QGraphicsOpacityEffect(self.top_bar)
        self.top_opacity.setOpacity(1.0)
        self.top_layout = QHBoxLayout(self.top_bar)
        self.top_layout.setContentsMargins(18, 18, 18, 18)
        self.back_button = StaticIconButton()
        self.back_button.setObjectName("playerIcon")
        set_player_button_icon(self.back_button, "back")
        self.back_button.setToolTip("Back (Esc)")
        self.title = QLabel("")
        self.title.setObjectName("playerTitle")
        self.top_layout.addWidget(self.back_button)
        self.top_layout.addStretch()
        self.back_button.clicked.connect(self.close_player)

        self.bottom_bar = QFrame(self.overlay)
        self.bottom_bar.setObjectName("playerBottom")
        self.bottom_bar.setMouseTracking(True)
        self.bottom_bar.installEventFilter(self)
        self.bottom_opacity = QGraphicsOpacityEffect(self.bottom_bar)
        self.bottom_opacity.setOpacity(1.0)
        self.bottom_layout = QVBoxLayout(self.bottom_bar)
        self.bottom_layout.setContentsMargins(20, 4, 20, 8)
        self.bottom_layout.setSpacing(8)
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
        self.bottom_layout.addLayout(progress_layout)
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
        self.next_episode_button = HoverIconButton()
        self.next_episode_button.setObjectName("playerIcon")
        set_player_button_icon(self.next_episode_button, "next")
        self.next_episode_button.setToolTip("Next episode")
        self.episode_menu_button = HoverIconButton()
        self.episode_menu_button.setObjectName("playerIcon")
        set_player_button_icon(self.episode_menu_button, "episodes")
        self.episode_menu_button.setToolTip("Episodes")
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
        right_controls.addWidget(self.next_episode_button)
        right_controls.addWidget(self.episode_menu_button)
        right_controls.addWidget(self.settings_button)
        right_controls.addWidget(self.fullscreen_button)
        controls.addLayout(left_controls, 1)
        controls.addWidget(self.title, 0, Qt.AlignCenter)
        controls.addLayout(right_controls, 1)
        self.bottom_layout.addLayout(controls)

        self.top_control_ghost = QLabel(self.overlay)
        self.top_control_ghost.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.top_control_ghost_opacity = QGraphicsOpacityEffect(self.top_control_ghost)
        self.top_control_ghost.setGraphicsEffect(self.top_control_ghost_opacity)
        self.top_control_ghost.hide()
        self.bottom_control_ghost = QLabel(self.overlay)
        self.bottom_control_ghost.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.bottom_control_ghost_opacity = QGraphicsOpacityEffect(self.bottom_control_ghost)
        self.bottom_control_ghost.setGraphicsEffect(self.bottom_control_ghost_opacity)
        self.bottom_control_ghost.hide()

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
            self.next_episode_button,
            self.episode_menu_button,
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
        self.next_episode_button.clicked.connect(self.play_next_episode)
        self.episode_menu_button.clicked.connect(self.open_episode_menu)
        self.settings_button.clicked.connect(self.open_settings_menu)
        self.fullscreen_button.clicked.connect(self._toggle_fullscreen)
        self._update_volume_icon(self.volume.value())
        self._update_episode_controls()
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
            self.next_episode_button,
            self.episode_menu_button,
            self.settings_button,
            self.fullscreen_button,
        )
        for widget in self.control_hover_widgets:
            widget.setMouseTracking(True)
            widget.installEventFilter(self)
        self.native_input_filter = None

    def _connect_controller_signals(self, controller: MpvController) -> None:
        controller.position_changed.connect(self._position_changed)
        controller.playing_changed.connect(self._playing_changed)
        controller.ended.connect(self._ended)
        controller.error.connect(self._show_error)

    def set_playlist(self, movies: list[Movie], current_movie: Movie, title: str = "") -> None:
        self.playlist = list(movies)
        self.playlist_title = title
        self.playlist_index = next(
            (index for index, movie in enumerate(self.playlist) if movie.path == current_movie.path),
            -1,
        )
        if self.playlist_index >= 0:
            self.episode_menu_page_start = (
                self.playlist_index // self.episode_menu_page_size
            ) * self.episode_menu_page_size
        else:
            self.episode_menu_page_start = 0
        self._update_episode_controls()

    def _update_episode_controls(self) -> None:
        has_series = len(self.playlist) > 1 and self.playlist_index >= 0
        has_next = has_series and self.playlist_index < len(self.playlist) - 1
        if hasattr(self, "episode_menu_button"):
            self.episode_menu_button.setVisible(has_series)
            self.episode_menu_button.setEnabled(has_series)
        if hasattr(self, "next_episode_button"):
            self.next_episode_button.setVisible(has_series)
            self.next_episode_button.setEnabled(has_next)

    def _show_playback_blackout(self) -> None:
        self.playback_blackout_token += 1
        token = self.playback_blackout_token
        self.playback_blackout.setGeometry(self.overlay.rect())
        self.playback_blackout.show()
        self.playback_blackout.raise_()
        self._stop_control_animation()
        self.top_bar.hide()
        self.bottom_bar.hide()
        self.volume_popup.hide()
        self.seek_preview.hide()
        QTimer.singleShot(3500, lambda token=token: self._hide_playback_blackout(token))

    def _hide_playback_blackout(self, token: Optional[int] = None) -> None:
        if token is not None and token != self.playback_blackout_token:
            return
        if self.playback_blackout.isVisible():
            self.playback_blackout.hide()
            self._show_controls()

    def _save_current_playback_progress(self) -> None:
        if not self.movie:
            return
        current = self.controller.time()
        length = self.controller.length() or self.movie.duration_ms
        completed = bool(length and current >= length * 0.92)
        self.progress_saved.emit(self.movie, current, completed)

    def play_next_episode(self) -> None:
        if self.playlist_index < 0 or self.playlist_index >= len(self.playlist) - 1:
            return
        self._save_current_playback_progress()
        next_movie = self.playlist[self.playlist_index + 1]
        self.playlist_index += 1
        self._show_playback_blackout()
        self._close_track_panel(reveal_controls=False)
        self.play_movie(next_movie, start_ms=0, autoplay=True)

    def _player_episode_range_label(self, start: int, end: int) -> str:
        if start == end:
            return f"Episode {start}"
        if end == start + 1:
            return f"Episode {start} and {end}"
        return f"Episodes {start} - {end}"

    def _player_episode_ranges(self) -> list[tuple[int, int]]:
        total = len(self.playlist)
        page_size = self.episode_menu_page_size
        return [(start, min(start + page_size, total)) for start in range(0, total, page_size)]

    def _switch_player_episode_page(self, start: int) -> None:
        self.episode_menu_page_start = start
        self.open_episode_menu(rebuild=True)

    def open_episode_range_menu(self) -> None:
        if len(self.playlist) <= self.episode_menu_page_size or self.playlist_index < 0:
            return
        if self.track_panel and self.track_panel.isVisible():
            self._close_track_panel(reveal_controls=False)

        self._restore_overlay_input(force=True)
        panel = QFrame(self.overlay)
        panel.setObjectName("episodePanel")
        panel.setMouseTracking(True)
        panel.setFocusPolicy(Qt.NoFocus)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel(self.playlist_title or "Episodes")
        title.setObjectName("episodeRangePanelTitle")
        title.setContentsMargins(22, 16, 22, 14)
        layout.addWidget(title)

        ranges_widget = QWidget()
        ranges_widget.setObjectName("episodeRangeContents")
        ranges_layout = QVBoxLayout(ranges_widget)
        ranges_layout.setContentsMargins(0, 0, 0, 0)
        ranges_layout.setSpacing(0)
        current_start = (
            self.playlist_index // self.episode_menu_page_size
        ) * self.episode_menu_page_size
        for start, end in self._player_episode_ranges():
            active = start == current_start
            label = self._player_episode_range_label(start + 1, end)
            button = QPushButton(("   " + label) if active else label)
            button.setObjectName("episodeRangeOption")
            button.setProperty("active", active)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)
            if active:
                button.setIcon(build_player_control_icon("check"))
                button.setIconSize(QSize(22, 22))
                button.setContentsMargins(0, 0, 0, 0)
            else:
                button.setContentsMargins(44, 0, 0, 0)
            button.clicked.connect(
                lambda _checked=False, page_start=start: self._switch_player_episode_page(page_start)
            )
            ranges_layout.addWidget(button)
        ranges_layout.addStretch()
        layout.addWidget(ranges_widget, 1)

        self.track_panel = panel
        self.menu_open = True
        panel.show()
        self._position_track_panel()
        panel.raise_()
        self._show_controls(keep=True)
        self.hide_timer.start()

    def open_episode_menu(self, rebuild: bool = False) -> None:
        if len(self.playlist) <= 1 or self.playlist_index < 0:
            return
        if self.track_panel and self.track_panel.isVisible():
            if not rebuild:
                self._close_track_panel()
                return
            self._close_track_panel(reveal_controls=False)

        if not rebuild:
            self.episode_menu_page_start = (
                self.playlist_index // self.episode_menu_page_size
            ) * self.episode_menu_page_size

        self._close_track_panel()
        self._restore_overlay_input(force=True)
        panel = QFrame(self.overlay)
        panel.setObjectName("episodePanel")
        panel.setMouseTracking(True)
        panel.setFocusPolicy(Qt.NoFocus)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("episodePanelScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        contents = QWidget()
        contents.setObjectName("episodePanelContents")
        rows = QVBoxLayout(contents)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)

        header_widget = QWidget()
        header_widget.setObjectName("episodePanelHeader")
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(24, 18, 18, 18)
        header.setSpacing(10)
        back = StaticIconButton()
        back.setObjectName("episodePanelBack")
        set_player_button_icon(back, "back")
        back.setFixedSize(26, 34)
        back.setIconSize(QSize(20, 20))
        back.setCursor(Qt.PointingHandCursor)
        back.setFocusPolicy(Qt.NoFocus)
        back.setVisible(len(self.playlist) > self.episode_menu_page_size)
        if len(self.playlist) > self.episode_menu_page_size:
            back.clicked.connect(self.open_episode_range_menu)
        title = QLabel(self._player_episode_range_label(self.episode_menu_page_start + 1, min(self.episode_menu_page_start + self.episode_menu_page_size, len(self.playlist))))
        title.setObjectName("episodePanelTitle")
        header.addWidget(back)
        header.addWidget(title, 1)
        rows.addWidget(header_widget)
        if self.episode_menu_page_start >= len(self.playlist):
            self.episode_menu_page_start = 0
        page_start = max(0, self.episode_menu_page_start)
        page_end = min(page_start + self.episode_menu_page_size, len(self.playlist))
        for index, movie in enumerate(self.playlist[page_start:page_end], start=page_start + 1):
            item = PlayerEpisodeMenuItem(index, movie, index - 1 == self.playlist_index)
            item.activated.connect(self._play_episode_from_menu)
            rows.addWidget(item)
        scroll.setWidget(contents)
        layout.addWidget(scroll, 1)

        self.track_panel = panel
        self.menu_open = True
        panel.show()
        self._position_track_panel()
        panel.raise_()
        self._show_controls(keep=True)
        self.hide_timer.start()

    def _play_episode_from_menu(self, movie: Movie) -> None:
        new_index = next(
            (index for index, playlist_movie in enumerate(self.playlist) if playlist_movie.path == movie.path),
            -1,
        )
        if new_index < 0:
            return
        self._save_current_playback_progress()
        self.playlist_index = new_index
        self._show_playback_blackout()
        self._close_track_panel(reveal_controls=False)
        self.play_movie(movie, start_ms=0, autoplay=True)

    def play_movie(
        self, movie: Movie, start_ms: Optional[int] = None, autoplay: bool = True
    ) -> None:
        diagnostic_log(
            "player.play_movie",
            title=movie.title,
            path=movie.path,
            start_ms=start_ms,
            autoplay=autoplay,
            player=widget_snapshot(self),
        )
        self._close_track_panel()
        self.playback_token += 1
        playback_token = self.playback_token
        self.close_pending = False
        self.back_button.setEnabled(True)
        self.movie = movie
        if self.playlist:
            self.playlist_index = next(
                (index for index, playlist_movie in enumerate(self.playlist) if playlist_movie.path == movie.path),
                self.playlist_index,
            )
        self._update_episode_controls()
        self.title.setText(movie.title)
        self.selected_subtitle = -1
        self.subtitle_preference_applied = False
        self._sync_video_surface_geometry()
        self.timeline.setRange(0, max(0, movie.duration_ms))
        saved_progress = 0 if movie.completed else max(0, int(movie.progress_ms or 0))
        start_position = max(0, int(start_ms)) if start_ms is not None else saved_progress
        self.timeline.setValue(start_position)
        subtitle_tracks = cached_subtitle_tracks_for_movie(
            movie,
            self.store.subtitle_cache_dir,
            self.ffprobe,
            self.ffmpeg,
            create=False,
        )
        diagnostic_log(
            "player.subtitle.cached_tracks",
            title=movie.title,
            count=len(subtitle_tracks),
            preference_key=self._subtitle_preference_key(),
            saved_preference=self._saved_subtitle_preference(),
            tracks="; ".join(
                f"{source}|{label}|{language}|{diagnostic_path_summary(path)}"
                for path, label, language, source in subtitle_tracks
            ) or "none",
        )
        set_player_button_icon(self.play_button, "pause" if autoplay else "play")
        self.play_button.setToolTip("Pause (K)" if autoplay else "Play (K)")
        self.playback_started_at = time.monotonic()
        self.controller.open(
            movie.path,
            start_position,
            int(self.settings.get("volume", 80)),
            autoplay=autoplay,
            subtitle_tracks=subtitle_tracks,
        )
        if not autoplay:
            QTimer.singleShot(
                160,
                lambda token=playback_token: self._run_for_playback(
                    token, lambda: self.controller.set_paused(True)
                ),
            )
        preference_delays = (90, 150, 240, 420, 800, 1300) if subtitle_tracks else (120, 300, 700, 1200)
        for delay in preference_delays:
            QTimer.singleShot(
                delay,
                lambda token=playback_token: self._run_for_playback(
                    token, self._apply_saved_subtitle_preference
                ),
            )
        self._sync_overlay_geometry()
        self.overlay.show()
        self.overlay.raise_()
        if self.playback_blackout.isVisible():
            self.playback_blackout.raise_()
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
        if hasattr(window, "is_player_fullscreen") and window.is_player_fullscreen():
            window.exit_player_fullscreen()
            set_player_button_icon(self.fullscreen_button, "fullscreen")
            self.fullscreen_button.setToolTip("Fullscreen (F)")
            QApplication.processEvents()
        elif window.isFullScreen():
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
        super().resizeEvent(event)
        window = self.window()
        player_fullscreen = (
            window.is_player_fullscreen()
            if hasattr(window, "is_player_fullscreen")
            else window.isFullScreen() if window else False
        )
        signature = (
            self.width(),
            self.height(),
            self.isVisible(),
            player_fullscreen,
        )
        if signature != self._last_resize_log_signature:
            self._last_resize_log_signature = signature
            diagnostic_log(
                "player.resize_event",
                player=widget_snapshot(self),
                window=widget_snapshot(window) if window else "none",
                fullscreen=player_fullscreen,
                native_fullscreen=window.isFullScreen() if window else False,
            )
        self._snap_layout_for_resize()

    def _stop_control_animation(self) -> None:
        if self.controls_animating and self.control_animation is not None:
            self.control_animation.stop()
            self.control_animation.deleteLater()
            self.control_animation = None
        self.controls_animating = False
        if hasattr(self, "top_control_ghost"):
            self.top_control_ghost.hide()
            self.bottom_control_ghost.hide()

    def _snap_layout_for_resize(self) -> None:
        self._stop_control_animation()
        video_suspended = bool(
            hasattr(self, "video_surface")
            and self.video_surface.rendering_suspended
        )
        if not video_suspended:
            self._sync_video_surface_geometry()
        self._sync_overlay_geometry()
        if not video_suspended:
            self.video_surface.lower()
        self._log_layout_snapshot("player.layout.snap")

    def _force_integrated_window_layout(self) -> None:
        self._stop_control_animation()
        self._sync_video_surface_geometry()
        self._sync_overlay_geometry()
        self.video_surface.lower()
        self.overlay.raise_()
        self.top_bar.raise_()
        self.bottom_bar.raise_()
        self.video_surface.update()
        self.overlay.update()
        self._log_layout_snapshot("player.layout.force")

    def recover_after_fullscreen_transition(self) -> None:
        self.fullscreen_recovery_generation += 1
        generation = self.fullscreen_recovery_generation
        if self.movie is None:
            return
        diagnostic_log(
            "player.fullscreen_recover",
            generation=generation,
            player=widget_snapshot(self),
            window=widget_snapshot(self.window()) if self.window() else "none",
            fullscreen=self.window().is_player_fullscreen()
            if hasattr(self.window(), "is_player_fullscreen")
            else self.window().isFullScreen()
            if self.window()
            else False,
            native_fullscreen=self.window().isFullScreen() if self.window() else False,
        )
        self._settle_fullscreen_layout(generation)
        for delay in (25, 75, 150, 300):
            QTimer.singleShot(
                delay,
                lambda active=generation: self._settle_fullscreen_layout(active),
            )

    def _settle_fullscreen_layout(self, generation: int) -> None:
        if generation != self.fullscreen_recovery_generation or self.movie is None:
            return
        self.controls_visible = True
        self.top_opacity.setOpacity(1.0)
        self.bottom_opacity.setOpacity(1.0)
        self._force_integrated_window_layout()
        self.overlay.show()
        self.overlay.raise_()
        if self.playback_blackout.isVisible():
            self.playback_blackout.raise_()
        self._restore_overlay_input(force=True)
        self.top_bar.show()
        self.bottom_bar.show()
        self.top_bar.move(0, 0)
        self.bottom_bar.move(0, self.overlay.height() - self.bottom_bar.height())
        self.top_bar.raise_()
        self.bottom_bar.raise_()

    def begin_interactive_resize(self) -> None:
        self.interactive_resizing = True
        self.fullscreen_recovery_generation += 1
        diagnostic_log(
            "player.interactive_resize.begin",
            player=widget_snapshot(self),
            window=widget_snapshot(self.window()) if self.window() else "none",
        )
        self.hide_timer.stop()
        self.volume_popup_timer.stop()
        self._update_icon_hovers(None)
        self._snap_layout_for_resize()

    def end_interactive_resize(self) -> None:
        self.interactive_resizing = False
        diagnostic_log(
            "player.interactive_resize.end",
            player=widget_snapshot(self),
            window=widget_snapshot(self.window()) if self.window() else "none",
        )
        self._settle_video_layout()
        if self.controller.is_playing() and self.controls_visible:
            self.hide_timer.start()

    def _settle_video_layout(self) -> None:
        self._force_integrated_window_layout()

    def _sync_video_surface_geometry(self) -> None:
        if self.video_surface.rendering_suspended:
            diagnostic_log(
                "player.video_surface_geometry.skipped_suspended",
                player=widget_snapshot(self),
                surface=widget_snapshot(self.video_surface),
                target=f"{self.width()}x{self.height()}",
            )
            return
        target = self.rect()
        if self.video_surface.geometry() != target:
            self.video_surface.setGeometry(target)
        self.video_surface.lower()

    def _player_fullscreen_active(self) -> bool:
        window = self.window()
        if hasattr(window, "is_player_fullscreen"):
            return bool(window.is_player_fullscreen())
        return bool(window and window.isFullScreen())

    def _control_bar_sizes(self) -> tuple[int, int]:
        if self._player_fullscreen_active():
            return 118, 136
        return 96, 108

    def _apply_control_bar_margins(self) -> None:
        if not hasattr(self, "top_layout") or not hasattr(self, "bottom_layout"):
            return
        if self._player_fullscreen_active():
            self.top_layout.setContentsMargins(28, 34, 28, 18)
            self.bottom_layout.setContentsMargins(28, 8, 28, 28)
        else:
            self.top_layout.setContentsMargins(18, 18, 18, 18)
            self.bottom_layout.setContentsMargins(20, 4, 20, 8)

    def _sync_overlay_geometry(self) -> None:
        if not hasattr(self, "overlay") or not hasattr(self, "top_bar"):
            return
        target = QRect(0, 0, self.width(), self.height())
        if self.overlay.geometry() != target:
            self.overlay.setGeometry(target)
        if hasattr(self, "playback_blackout"):
            self.playback_blackout.setGeometry(self.overlay.rect())
        if hasattr(self, "fullscreen_fade"):
            self.fullscreen_fade.setGeometry(target)
        self._apply_control_bar_margins()
        top_height, bottom_height = self._control_bar_sizes()
        self.top_bar.resize(self.overlay.width(), top_height)
        self.bottom_bar.resize(self.overlay.width(), bottom_height)
        if not self.controls_animating:
            top_hidden_offset = 16
            bottom_hidden_offset = 22
            self.top_bar.move(0, 0 if self.controls_visible else -top_hidden_offset)
            self.bottom_bar.move(
                0,
                self.overlay.height() - bottom_height + (0 if self.controls_visible else bottom_hidden_offset),
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
        if hasattr(self, "top_control_ghost"):
            self.top_control_ghost.raise_()
            self.bottom_control_ghost.raise_()
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
        if hasattr(self, "playback_blackout") and self.playback_blackout.isVisible():
            self.playback_blackout.raise_()
        if hasattr(self, "fullscreen_fade") and self.fullscreen_fade.isVisible():
            self.fullscreen_fade.raise_()

    def _log_layout_snapshot(self, event: str) -> None:
        signature = (
            event,
            self.width(),
            self.height(),
            self.video_surface.geometry().getRect(),
            self.overlay.geometry().getRect(),
            self.top_bar.geometry().getRect(),
            self.bottom_bar.geometry().getRect(),
            self.controls_visible,
            self.window().isFullScreen() if self.window() else False,
        )
        if signature == self._last_layout_log_signature:
            return
        self._last_layout_log_signature = signature
        diagnostic_log(
            event,
            player=widget_snapshot(self),
            surface=widget_snapshot(self.video_surface),
            overlay=widget_snapshot(self.overlay),
            top=widget_snapshot(self.top_bar),
            bottom=widget_snapshot(self.bottom_bar),
            controls_visible=self.controls_visible,
            fullscreen=self.window().isFullScreen() if self.window() else False,
        )

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
            elif (
                hasattr(window, "is_player_fullscreen")
                and window.is_player_fullscreen()
            ):
                self.hide_timer.stop()
                self._stop_control_animation()
                self.overlay.hide()
                window.exit_player_fullscreen()
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
        if self.playback_blackout.isVisible() and current > 100:
            self._hide_playback_blackout()
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
        frames = usable_episode_preview_frames(self.movie) if self.movie else ()
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
        if self.playlist_index >= 0 and self.playlist_index < len(self.playlist) - 1:
            next_movie = self.playlist[self.playlist_index + 1]
            self.playlist_index += 1
            self._show_playback_blackout()
            self._close_track_panel(reveal_controls=False)
            self.play_movie(next_movie, start_ms=0, autoplay=True)
            return
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
        else:
            self.top_bar.move(0, 0)
            self.bottom_bar.move(0, self.overlay.height() - self.bottom_bar.height())
        self.top_bar.raise_()
        self.bottom_bar.raise_()
        if hasattr(self, "top_control_ghost"):
            self.top_control_ghost.raise_()
            self.bottom_control_ghost.raise_()
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
        if hasattr(self, "playback_blackout") and self.playback_blackout.isVisible():
            self.playback_blackout.raise_()
        if hasattr(self, "fullscreen_fade") and self.fullscreen_fade.isVisible():
            self.fullscreen_fade.raise_()
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
        position = QCursor.pos()
        self._poll_control_press(position)
        moved_for_log = position != self._last_pointer_log_pos
        now = time.monotonic()
        if (
            moved_for_log
            and self.isVisible()
            and self.movie
            and (self.window().isFullScreen() if self.window() else False)
            and now - self._last_pointer_log_at > 0.25
        ):
            self._last_pointer_log_at = now
            self._last_pointer_log_pos = position
            local = self.mapFromGlobal(position)
            diagnostic_log(
                "player.pointer.sample",
                global_pos=f"{position.x()},{position.y()}",
                local_pos=f"{local.x()},{local.y()}",
                in_player=self.rect().contains(local),
                controls_visible=self.controls_visible,
                player=widget_snapshot(self),
            )
        if self.interactive_resizing:
            self.last_cursor_position = position
            self._update_icon_hovers(None)
            return
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
        if self.interactive_resizing:
            return
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

    def _snapshot_control_bar(self, widget: QWidget, ghost: QLabel) -> None:
        pixmap = QPixmap(widget.size())
        pixmap.fill(Qt.transparent)
        widget.render(pixmap)
        ghost.setPixmap(pixmap)
        ghost.resize(widget.size())
        ghost.move(widget.pos())
        ghost.show()
        ghost.raise_()

    def _animate_controls(self, showing: bool) -> None:
        if self.control_animation is not None:
            self.control_animation.stop()
            self.control_animation.deleteLater()
        self.top_control_ghost.hide()
        self.bottom_control_ghost.hide()

        top_hidden_offset = 16
        bottom_hidden_offset = 22
        top_visible = QPoint(0, 0)
        top_hidden = QPoint(0, -top_hidden_offset)
        bottom_visible = QPoint(0, self.overlay.height() - self.bottom_bar.height())
        bottom_hidden = QPoint(0, bottom_visible.y() + bottom_hidden_offset)
        self.top_bar.setAttribute(Qt.WA_TransparentForMouseEvents, not showing)
        self.bottom_bar.setAttribute(Qt.WA_TransparentForMouseEvents, not showing)

        if showing or self.interactive_resizing:
            self.control_animation = None
            self.controls_animating = False
            self.top_bar.show()
            self.bottom_bar.show()
            self.top_bar.move(top_visible)
            self.bottom_bar.move(bottom_visible)
            return

        self._snapshot_control_bar(self.top_bar, self.top_control_ghost)
        self._snapshot_control_bar(self.bottom_bar, self.bottom_control_ghost)
        self.top_control_ghost_opacity.setOpacity(1.0)
        self.bottom_control_ghost_opacity.setOpacity(1.0)
        self.top_bar.hide()
        self.bottom_bar.hide()

        group = QParallelAnimationGroup(self)
        self.control_animation = group
        self.controls_animating = True
        duration = 130
        curve = QEasingCurve.OutCubic
        for widget, end in (
            (self.top_control_ghost, top_hidden),
            (self.bottom_control_ghost, bottom_hidden),
        ):
            animation = QPropertyAnimation(widget, b"pos", group)
            animation.setDuration(duration)
            animation.setStartValue(widget.pos())
            animation.setEndValue(end)
            animation.setEasingCurve(curve)
            group.addAnimation(animation)
        for effect in (self.top_control_ghost_opacity, self.bottom_control_ghost_opacity):
            animation = QPropertyAnimation(effect, b"opacity", group)
            animation.setDuration(duration)
            animation.setStartValue(1.0)
            animation.setEndValue(0.0)
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
        self.top_control_ghost.hide()
        self.bottom_control_ghost.hide()
        if not self.controls_visible:
            self.top_bar.hide()
            self.bottom_bar.hide()
        else:
            self.top_bar.show()
            self.bottom_bar.show()
        self._sync_overlay_geometry()

    def _animate_fullscreen_fade(
        self,
        start: float,
        end: float,
        duration: int,
        on_finished=None,
    ) -> None:
        if self.fullscreen_fade_animation is not None:
            self.fullscreen_fade_animation.stop()
            self.fullscreen_fade_animation.deleteLater()
            self.fullscreen_fade_animation = None
        self.fullscreen_fade.setGeometry(self.rect())
        self.fullscreen_fade.show()
        self.fullscreen_fade.raise_()
        self.fullscreen_fade_opacity.setOpacity(start)
        animation = QPropertyAnimation(self.fullscreen_fade_opacity, b"opacity", self)
        animation.setDuration(duration)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setEasingCurve(QEasingCurve.InOutCubic)
        self.fullscreen_fade_animation = animation

        def finish() -> None:
            if end <= 0.0:
                self.fullscreen_fade.hide()
            if self.fullscreen_fade_animation is animation:
                self.fullscreen_fade_animation = None
            animation.deleteLater()
            if on_finished is not None:
                on_finished()

        animation.finished.connect(finish)
        animation.start()

    def _fade_fullscreen_blackout_out(self) -> None:
        self._animate_fullscreen_fade(
            float(self.fullscreen_fade_opacity.opacity()),
            0.0,
            260,
        )

    def _toggle_fullscreen(self) -> None:
        window = self.window()
        if hasattr(window, "toggle_player_fullscreen_with_fade"):
            window.toggle_player_fullscreen_with_fade()
            return
        if window is None:
            return
        entering = not window.isFullScreen()
        self.click_timer.stop()
        self.ignore_click_release = True
        self._close_track_panel(reveal_controls=False)
        self.hide_timer.stop()
        self._stop_control_animation()
        self.overlay.hide()
        window.showFullScreen() if entering else window.showNormal()
        set_player_button_icon(
            self.fullscreen_button,
            "windowed" if entering else "fullscreen",
        )
        self.fullscreen_button.setToolTip(
            "Exit fullscreen (F)" if entering else "Fullscreen (F)"
        )
        QTimer.singleShot(600, lambda: setattr(self, "ignore_click_release", False))

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
        available_subtitle_tracks = self.controller.subtitle_tracks()
        diagnostic_log(
            "player.subtitle.menu_open",
            movie=self.movie.title if self.movie else "none",
            current_sid=current_spu,
            available=len(available_subtitle_tracks),
            tracks="; ".join(f"{track_id}:{description}" for track_id, description in available_subtitle_tracks) or "none",
        )
        for track_id, description in available_subtitle_tracks:
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
        diagnostic_log(
            "player.subtitle.user_choose",
            movie=self.movie.title if self.movie else "none",
            track_id=track_id,
            label=label,
        )
        self._remember_subtitle_preference(track_id, label)
        self._select_subtitle(track_id)
        self._close_track_panel()
        self._queue_overlay_input_restore()

    def _position_track_panel(self) -> None:
        if not self.track_panel:
            return
        width = max(560, min(700, self.overlay.width() - 72))
        height = max(300, min(620, self.overlay.height() - 170))
        x = max(24, self.overlay.width() - width - 70)
        y = max(24, self.bottom_bar.y() - height - 10)
        self.track_panel.setFixedSize(width, height)
        self.track_panel.move(x, y)

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
        diagnostic_log(
            "player.subtitle.preference.saved",
            movie=self.movie.title if self.movie else "none",
            key=key,
            track_id=track_id,
            label=label,
            off=track_id == -1,
        )
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
            diagnostic_log(
                "player.subtitle.preference.skip",
                reason="already_applied_or_no_movie",
                applied=self.subtitle_preference_applied,
                movie=self.movie.title if self.movie else "none",
            )
            return
        preference = self._saved_subtitle_preference()
        if not preference:
            diagnostic_log(
                "player.subtitle.preference.none",
                movie=self.movie.title if self.movie else "none",
                key=self._subtitle_preference_key(),
            )
            return
        if preference.get("off"):
            diagnostic_log(
                "player.subtitle.preference.apply_off",
                movie=self.movie.title if self.movie else "none",
                preference=preference,
            )
            self.subtitle_preference_applied = True
            self._select_subtitle(-1)
            return

        tracks = self.controller.subtitle_tracks()
        if not tracks:
            diagnostic_log(
                "player.subtitle.preference.wait_no_tracks",
                movie=self.movie.title if self.movie else "none",
                preference=preference,
            )
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
        match_reason = "label"
        if match is None:
            match = next(
                (track_id for track_id, _description in tracks if track_id == saved_track_id),
                None,
            )
            match_reason = "track_id"
        if match is None:
            diagnostic_log(
                "player.subtitle.preference.no_match",
                movie=self.movie.title if self.movie else "none",
                preference=preference,
                tracks="; ".join(f"{track_id}:{description}" for track_id, description in tracks),
            )
            return
        diagnostic_log(
            "player.subtitle.preference.apply",
            movie=self.movie.title if self.movie else "none",
            preference=preference,
            match=match,
            match_reason=match_reason,
            tracks="; ".join(f"{track_id}:{description}" for track_id, description in tracks),
        )
        self.subtitle_preference_applied = True
        self._select_subtitle(match)

    def _select_subtitle(self, track_id: int) -> None:
        before = self.selected_subtitle
        if track_id == -1:
            if self.selected_subtitle != -1:
                self.last_subtitle_selection = self.selected_subtitle
            self.controller.select_subtitle(-1)
            self.selected_subtitle = -1
        else:
            self.controller.select_subtitle(track_id)
            self.selected_subtitle = track_id
        self.last_subtitle_selection = self.selected_subtitle
        diagnostic_log(
            "player.subtitle.selected",
            movie=self.movie.title if self.movie else "none",
            requested=track_id,
            before=before,
            after=self.selected_subtitle,
            last=self.last_subtitle_selection,
        )
        self._queue_overlay_input_restore()


class DordieWatchWindow(QMainWindow):
    GWL_STYLE = -16
    WS_CAPTION = 0x00C00000
    WS_THICKFRAME = 0x00040000
    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    SWP_FRAMECHANGED = 0x0020

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
            else:
                movie.cover = ""
            if not episode_still_for_movie(movie):
                movie.thumbnail = catalog_placeholder(
                    self.store, Path(movie.path), movie.title
                )
        self.scan_task: Optional[LibraryScanTask] = None
        self.preview_task: Optional[PreviewGenerationTask] = None
        self.preview_task_key = ""
        self.subtitle_cache_task: Optional[SubtitleCacheTask] = None
        self.subtitle_cache_task_key = ""
        self.subtitle_cache_token = 0
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
        self._was_fullscreen = False
        self._player_fullscreen = False
        self._player_fullscreen_restore_geometry: Optional[QRect] = None
        self._player_fullscreen_restore_state = Qt.WindowNoState
        self._player_fullscreen_restore_flags = self.windowFlags()
        self._player_fullscreen_restore_style: Optional[int] = None
        self._player_fullscreen_transitioning = False
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
        self.series_dialog: Optional[SeriesDetailsDialog] = None
        self.series_backdrop: Optional[QFrame] = None
        self.series_backdrop_animation: Optional[QPropertyAnimation] = None
        self.series_backdrop_hiding = False
        self.player_launch_overlay: Optional[PlayerLaunchTransitionOverlay] = None
        self.fullscreen_transition_cover = QFrame(
            None,
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint,
        )
        self.fullscreen_transition_cover.setObjectName("playerBlackout")
        self.fullscreen_transition_cover.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.fullscreen_transition_cover.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.fullscreen_transition_cover.setWindowOpacity(0.0)
        self.fullscreen_transition_cover.hide()
        self.fullscreen_transition_cover_animation: Optional[QPropertyAnimation] = None
        self.native_resize_filter: Optional[NativePlayerResizeFilter] = None
        app = QApplication.instance()
        if app is not None:
            self.native_resize_filter = NativePlayerResizeFilter(self)
            app.installNativeEventFilter(self.native_resize_filter)
            diagnostic_log("window.native_resize_filter.installed")
        self.close_after_player = False
        self.home.refresh_requested.connect(self.refresh_libraries)
        self.home.movie_activated.connect(self.open_collection)
        self.home.hero_play_requested.connect(self.play_movie_from_home_hero)
        self.home.search.textChanged.connect(self.rebuild_home)
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
        missing_episode_previews = any(
            not has_episode_preview_frames(movie)
            for movie in self.movies
        )
        # A saved catalog is ready to use immediately unless it predates
        # per-episode preview frames. In that case, refresh in the background.
        if not self.movies or missing_episode_previews:
            QTimer.singleShot(0, self.refresh_libraries)
        if launch_manifest_url:
            QTimer.singleShot(
                0,
                lambda url=launch_manifest_url: self.open_website_media(url),
            )

    def _fullscreen_cover_geometry(self) -> QRect:
        screen = self.windowHandle().screen() if self.windowHandle() else None
        if screen is None:
            screen = QApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QApplication.primaryScreen()
        geometry = screen.geometry() if screen is not None else self.frameGeometry()
        return QRect(
            geometry.x() - 2,
            geometry.y() - 2,
            geometry.width() + 4,
            geometry.height() + 4,
        )

    def _sync_fullscreen_transition_cover(self) -> None:
        if not hasattr(self, "fullscreen_transition_cover"):
            return
        self.fullscreen_transition_cover.setGeometry(self._fullscreen_cover_geometry())
        if self.fullscreen_transition_cover.isVisible():
            self.fullscreen_transition_cover.raise_()

    def _animate_fullscreen_transition_cover(
        self,
        start: float,
        end: float,
        duration: int,
        on_finished=None,
    ) -> None:
        if self.fullscreen_transition_cover_animation is not None:
            self.fullscreen_transition_cover_animation.stop()
            self.fullscreen_transition_cover_animation.deleteLater()
            self.fullscreen_transition_cover_animation = None
        self._sync_fullscreen_transition_cover()
        self.fullscreen_transition_cover.show()
        self.fullscreen_transition_cover.raise_()
        QApplication.processEvents()
        self.fullscreen_transition_cover.setWindowOpacity(start)
        animation = QPropertyAnimation(
            self.fullscreen_transition_cover,
            b"windowOpacity",
            self,
        )
        animation.setDuration(duration)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setEasingCurve(QEasingCurve.InOutCubic)
        self.fullscreen_transition_cover_animation = animation

        def finish() -> None:
            if end <= 0.0:
                self.fullscreen_transition_cover.hide()
            if self.fullscreen_transition_cover_animation is animation:
                self.fullscreen_transition_cover_animation = None
            animation.deleteLater()
            if on_finished is not None:
                on_finished()

        animation.finished.connect(finish)
        animation.start()

    def _fade_fullscreen_transition_cover_out(self) -> None:
        self._animate_fullscreen_transition_cover(
            float(self.fullscreen_transition_cover.windowOpacity()),
            0.0,
            360,
        )

    def toggle_player_fullscreen_with_fade(self) -> None:
        if self.pages.currentWidget() is not self.player or self.player.movie is None:
            return
        entering = not self.is_player_fullscreen()
        diagnostic_log(
            "window.fullscreen_fade_toggle",
            entering=entering,
            window=widget_snapshot(self),
            player=widget_snapshot(self.player),
        )
        self.player.click_timer.stop()
        self.player.ignore_click_release = True
        self.player._close_track_panel(reveal_controls=False)
        self.player.hide_timer.stop()
        self.player._stop_control_animation()

        def switch_state() -> None:
            self.player.overlay.hide()
            if entering:
                self.enter_player_fullscreen()
            else:
                self.exit_player_fullscreen()
            QTimer.singleShot(
                600,
                lambda: setattr(self.player, "ignore_click_release", False),
            )

        self._animate_fullscreen_transition_cover(0.0, 1.0, 320, switch_state)
    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and hasattr(self, "player"):
            is_fullscreen = self.isFullScreen()
            try:
                state_value = int(self.windowState())
            except TypeError:
                state_value = getattr(self.windowState(), "value", str(self.windowState()))
            diagnostic_log(
                "window.state_change",
                fullscreen=is_fullscreen,
                state=state_value,
                window=widget_snapshot(self),
                current_page=type(self.pages.currentWidget()).__name__,
            )
            if self._player_fullscreen_transitioning:
                return
            if is_fullscreen != self._was_fullscreen:
                self._was_fullscreen = is_fullscreen
                if self.pages.currentWidget() is self.player:
                    set_player_button_icon(
                        self.player.fullscreen_button,
                        "windowed" if is_fullscreen else "fullscreen",
                    )
                    self.player.fullscreen_button.setToolTip(
                        "Exit fullscreen (F)"
                        if is_fullscreen
                        else "Fullscreen (F)"
                    )
                    if not self.player.video_surface.rendering_suspended:
                        self.player.recover_after_fullscreen_transition()

    def is_player_fullscreen(self) -> bool:
        return self._player_fullscreen

    def _window_hwnd(self) -> Optional[int]:
        if sys.platform != "win32":
            return None
        try:
            return int(self.winId())
        except RuntimeError:
            return None

    def _get_native_window_style(self) -> Optional[int]:
        hwnd = self._window_hwnd()
        if hwnd is None:
            return None
        try:
            return int(ctypes.windll.user32.GetWindowLongPtrW(hwnd, self.GWL_STYLE))
        except Exception as error:
            diagnostic_log("window.native_style.get.error", error=repr(error))
            return None

    def _set_native_window_style(self, style: int) -> bool:
        hwnd = self._window_hwnd()
        if hwnd is None:
            return False
        try:
            ctypes.windll.user32.SetWindowLongPtrW(hwnd, self.GWL_STYLE, int(style))
            return True
        except Exception as error:
            diagnostic_log("window.native_style.set.error", error=repr(error))
            return False

    def _apply_native_window_frame_change(
        self,
        geometry: QRect,
        *,
        topmost: Optional[bool] = None,
    ) -> bool:
        hwnd = self._window_hwnd()
        if hwnd is None:
            return False
        z_order = 0
        flags = self.SWP_NOACTIVATE | self.SWP_FRAMECHANGED
        if topmost is True:
            z_order = self.HWND_TOPMOST
        elif topmost is False:
            z_order = self.HWND_NOTOPMOST
        else:
            flags |= self.SWP_NOZORDER
        try:
            ctypes.windll.user32.SetWindowPos(
                hwnd,
                z_order,
                int(geometry.x()),
                int(geometry.y()),
                int(geometry.width()),
                int(geometry.height()),
                flags,
            )
            diagnostic_log(
                "window.native_frame_change",
                geometry=geometry.getRect(),
                topmost=topmost,
            )
            return True
        except Exception as error:
            diagnostic_log("window.native_frame_change.error", error=repr(error))
            return False

    def enter_player_fullscreen(self) -> None:
        if self._player_fullscreen or self.player.movie is None:
            return
        diagnostic_log(
            "window.fullscreen.enter.before",
            window=widget_snapshot(self),
            player=widget_snapshot(self.player),
            surface=widget_snapshot(self.player.video_surface),
        )
        screen = self.windowHandle().screen() if self.windowHandle() else None
        if screen is None:
            screen = QApplication.primaryScreen()
        target_geometry = screen.geometry() if screen is not None else self.geometry()
        # Do not use the exact monitor rectangle. On Windows/Qt this can promote
        # the borderless window into native fullscreen, which changes the
        # QOpenGLWidget/libmpv resize path after exiting fullscreen. Make it
        # one pixel taller and keep it topmost so it still covers the taskbar
        # without entering Qt's native fullscreen state.
        target_geometry = QRect(
            target_geometry.x(),
            target_geometry.y(),
            target_geometry.width(),
            target_geometry.height() + 1,
        )
        self._player_fullscreen_restore_geometry = self.geometry()
        self._player_fullscreen_restore_state = self.windowState()
        self._player_fullscreen_restore_flags = self.windowFlags()
        self._player_fullscreen_restore_style = self._get_native_window_style()
        self._player_fullscreen = True
        self._player_fullscreen_transitioning = True
        self.player.hide_timer.stop()
        self.player._stop_control_animation()
        self.player.volume_popup.hide()
        self.player._close_track_panel(reveal_controls=False)
        if self._player_fullscreen_restore_style is not None:
            borderless_style = self._player_fullscreen_restore_style & ~(
                self.WS_CAPTION | self.WS_THICKFRAME
            )
            self._set_native_window_style(borderless_style)
            self._apply_native_window_frame_change(target_geometry, topmost=True)
            self.setGeometry(target_geometry)
        else:
            self.setGeometry(target_geometry)
        self.show()
        self.raise_()
        self.activateWindow()
        self._sync_fullscreen_transition_cover()
        diagnostic_log(
            "window.fullscreen.enter.after_show",
            window=widget_snapshot(self),
            player=widget_snapshot(self.player),
            surface=widget_snapshot(self.player.video_surface),
            target=target_geometry.getRect(),
            native_fullscreen=self.isFullScreen(),
            native_style=self._get_native_window_style(),
        )
        set_player_button_icon(self.player.fullscreen_button, "windowed")
        self.player.fullscreen_button.setToolTip("Exit fullscreen (F)")
        QTimer.singleShot(40, self._finish_fullscreen_transition)

    def exit_player_fullscreen(self) -> None:
        if not self._player_fullscreen:
            return
        diagnostic_log(
            "window.fullscreen.exit.before",
            window=widget_snapshot(self),
            player=widget_snapshot(self.player),
            surface=widget_snapshot(self.player.video_surface),
        )
        self.player.hide_timer.stop()
        self.player._stop_control_animation()
        self.player.volume_popup.hide()
        self.player._close_track_panel(reveal_controls=False)
        restore_geometry = self._player_fullscreen_restore_geometry
        restore_state = self._player_fullscreen_restore_state
        restore_flags = self._player_fullscreen_restore_flags
        restore_style = self._player_fullscreen_restore_style
        self._player_fullscreen = False
        self._player_fullscreen_transitioning = True
        if restore_style is not None and restore_geometry is not None:
            self._set_native_window_style(restore_style)
            self._apply_native_window_frame_change(restore_geometry, topmost=False)
            self.setGeometry(restore_geometry)
            self.show()
        else:
            self.setWindowFlags(restore_flags)
            self.setWindowState(restore_state & ~Qt.WindowFullScreen)
            if restore_geometry is not None:
                self.setGeometry(restore_geometry)
            if restore_state & Qt.WindowMaximized:
                self.showMaximized()
            else:
                self.showNormal()
        diagnostic_log(
            "window.fullscreen.exit.after_show_normal",
            window=widget_snapshot(self),
            player=widget_snapshot(self.player),
            surface=widget_snapshot(self.player.video_surface),
            native_fullscreen=self.isFullScreen(),
            native_style=self._get_native_window_style(),
        )
        self.raise_()
        self.activateWindow()
        self._sync_fullscreen_transition_cover()
        set_player_button_icon(self.player.fullscreen_button, "fullscreen")
        self.player.fullscreen_button.setToolTip("Fullscreen (F)")
        QTimer.singleShot(40, self._finish_fullscreen_transition)

    def _finish_fullscreen_transition(self) -> None:
        diagnostic_log(
            "window.fullscreen.transition.finish",
            window=widget_snapshot(self),
            player=widget_snapshot(self.player),
            surface=widget_snapshot(self.player.video_surface),
            fullscreen=self.is_player_fullscreen(),
            native_fullscreen=self.isFullScreen(),
        )
        if self.player.video_surface.rendering_suspended:
            self.player.video_surface.set_rendering_suspended(
                False, "fullscreen_transition_finished"
            )
        self.player.recover_after_fullscreen_transition()
        self._schedule_player_fullscreen_layout_settle()
        self._player_fullscreen_transitioning = False
        QTimer.singleShot(180, self._fade_fullscreen_transition_cover_out)

    def rebuild_home(self, *_args) -> None:
        self.home.rebuild(self.roots, self.movies, self.home.search.text())

    def refresh_open_series_dialog(self) -> None:
        dialog = self.series_dialog
        if dialog is None or dialog._closing_animation_started:
            return
        current_key = dialog.collection.folder
        updated = next(
            (
                collection
                for collection in build_collections(self.movies, self.roots)
                if collection.folder == current_key
            ),
            None,
        )
        if updated is not None:
            dialog.set_collection(updated)
            if (
                self.subtitle_cache_task is not None
                and self.subtitle_cache_task_key == updated.folder
            ):
                dialog.set_subtitle_cache_busy(True, "Caching...")

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
        self.refresh_open_series_dialog()
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
        media_id_set = {
            movie.media_id
            for movie in self.movies
            if movie.media_id is not None
        }
        for collection in build_collections(self.movies, self.roots):
            folder = collection_filesystem_folder(collection)
            if folder.is_dir():
                media_id_set.update(collection_database_ids(folder))
        media_ids = sorted(media_id for media_id in media_id_set if media_id is not None)
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
        self.refresh_open_series_dialog()

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
        display_title = str(payload.get("display_title") or "").strip()
        folder = collection_filesystem_folder(collection)
        try:
            if folder.is_dir():
                linked_folder = link_collection_to_database_id(folder, media_id, display_title)
                if linked_folder != folder:
                    update_collection_paths_after_folder_rename(
                        collection, folder, linked_folder
                    )
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self,
                APP_NAME,
                f"Could not rename the local folder for this DordieList title:\n\n{error}",
            )
            return

        folder_ids = collection_database_ids(collection_filesystem_folder(collection))
        primary_media_id = folder_ids[0] if folder_ids else media_id
        for movie in collection.movies:
            movie.media_id = primary_media_id
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
                "No unlinked local video folders are available for this DordieList title.",
            )
            return None

        available.sort(
            key=lambda item: natural_sort_key(str(collection_filesystem_folder(item)))
        )
        labels: list[str] = []
        by_label: dict[str, LibraryCollection] = {}
        for collection in available:
            folder = collection_filesystem_folder(collection)
            folder_name = folder.name
            label = folder_name if folder_name not in by_label else str(folder)
            labels.append(label)
            by_label[label] = collection

        media_id = int(payload["id"])
        display_title = str(payload.get("display_title") or "this title").strip()
        selected, accepted = QInputDialog.getItem(
            self,
            "Connect DordieList title",
            (
                f"{display_title} [{media_id}]\n\n"
                "Choose the local video folder to rename and link:"
            ),
            labels,
            0,
            False,
        )
        if not accepted:
            return None
        return by_label.get(selected)

    def open_collection(
        self,
        collection: LibraryCollection,
        source_geometry: Optional[QRect] = None,
    ) -> None:
        if self.series_dialog is not None:
            self.series_dialog.request_close()
        self._show_series_backdrop()
        origin_geometry = None
        if isinstance(source_geometry, QRect):
            origin_geometry = QRect(
                self.mapFromGlobal(source_geometry.topLeft()),
                source_geometry.size(),
            )
        dialog = SeriesDetailsDialog(collection, self, origin_geometry)
        self.series_dialog = dialog
        dialog.movie_activated.connect(self.play_movie)
        dialog.subtitle_cache_requested.connect(self.cache_subtitles_for_collection)
        if self.subtitle_cache_task_key == collection.folder and self.subtitle_cache_task is not None:
            dialog.set_subtitle_cache_busy(True, "Caching...")
        dialog.finished.connect(
            lambda *_args, active=dialog: self._clear_series_dialog(active)
        )
        dialog.show_centered()
        dialog.raise_()
        self.start_series_preview_generation(collection)

    def _set_home_activity_idle_if_possible(self) -> None:
        if (
            not self.scan_task
            and not self.website_task
            and not self.website_library_task
            and not self.subtitle_cache_task
        ):
            self.home.set_scanning(None)

    def cache_subtitles_for_collection(self, collection: LibraryCollection) -> None:
        if not collection.movies:
            return
        if self.subtitle_cache_task is not None:
            dialog = self.series_dialog
            if dialog is not None and dialog.collection.folder == collection.folder:
                dialog.set_subtitle_cache_busy(True, "Caching...")
            return
        self.subtitle_cache_token += 1
        token = self.subtitle_cache_token
        task = SubtitleCacheTask(collection.movies, self.store, collection.folder)
        self.subtitle_cache_task = task
        self.subtitle_cache_task_key = collection.folder
        self.home.set_scanning(f"Caching subtitles for {collection.title}...", 0, len(collection.movies))
        dialog = self.series_dialog
        if dialog is not None and dialog.collection.folder == collection.folder:
            dialog.set_subtitle_cache_busy(True, "Checking...")
        task.signals.progress.connect(
            lambda current, total, title, active=token: self._subtitle_cache_progress(
                active, current, total, title
            )
        )
        task.signals.finished.connect(
            lambda payload, active=token: self._subtitle_cache_finished(active, payload)
        )
        task.signals.failed.connect(
            lambda message, active=token: self._subtitle_cache_failed(active, message)
        )
        QThreadPool.globalInstance().start(task.runnable)

    def _subtitle_cache_progress(
        self, token: int, current: int, total: int, title: str
    ) -> None:
        if token != self.subtitle_cache_token:
            return
        self.home.set_scanning(f"Caching subtitles {current} / {total}  {title}", current, total)
        dialog = self.series_dialog
        if dialog is not None and dialog.collection.folder == self.subtitle_cache_task_key:
            dialog.set_subtitle_cache_busy(True, f"Caching {current}/{total}")

    def _subtitle_cache_finished(self, token: int, payload: dict) -> None:
        if token != self.subtitle_cache_token:
            return
        self.subtitle_cache_task = None
        key = str(payload.get("key") or "")
        tracks = int(payload.get("tracks") or 0)
        videos = int(payload.get("videos") or 0)
        created = int(payload.get("created") or 0)
        if tracks <= 0:
            message = "No Subtitles"
        elif created <= 0:
            message = "Cache Ready"
        else:
            message = "Cache Ready"
        dialog = self.series_dialog
        if dialog is not None and dialog.collection.folder == key:
            dialog.set_subtitle_cache_busy(False, message)
        self.subtitle_cache_task_key = ""
        self._set_home_activity_idle_if_possible()

    def _subtitle_cache_failed(self, token: int, message: str) -> None:
        if token != self.subtitle_cache_token:
            return
        self.subtitle_cache_task = None
        dialog = self.series_dialog
        if dialog is not None and dialog.collection.folder == self.subtitle_cache_task_key:
            dialog.set_subtitle_cache_busy(False, "Cache Failed")
        self.subtitle_cache_task_key = ""
        self._set_home_activity_idle_if_possible()

    def start_series_preview_generation(self, collection: LibraryCollection) -> None:
        if not collection.movies:
            return
        if not any(not has_episode_preview_frames(movie) for movie in collection.movies):
            return
        if self.preview_task is not None:
            self.preview_task.cancel()
        task = PreviewGenerationTask(collection.movies, self.store, collection.folder)
        self.preview_task = task
        self.preview_task_key = collection.folder
        task.signals.movie.connect(
            lambda payload, key=collection.folder: self._preview_movie_ready(
                payload, key
            )
        )
        task.signals.finished.connect(self._preview_generation_finished)
        task.signals.failed.connect(self._preview_generation_failed)
        QThreadPool.globalInstance().start(task.runnable)

    def _preview_movie_ready(self, payload: dict, key: str) -> None:
        movie = Movie.from_dict(payload)
        self.movies = [item for item in self.movies if item.path != movie.path]
        self.movies.append(movie)
        dialog = self.series_dialog
        if (
            dialog is not None
            and not dialog._closing_animation_started
            and dialog.collection.folder == key
        ):
            self.refresh_open_series_dialog()

    def _preview_generation_finished(self, key: str) -> None:
        if self.preview_task_key == key:
            self.preview_task = None
            self.preview_task_key = ""
        self.save_library()
        self.refresh_open_series_dialog()

    def _preview_generation_failed(self, message: str) -> None:
        diagnostic_log("preview_task.signal_failed", message=message)
        self.preview_task = None
        self.preview_task_key = ""

    def _clear_series_dialog(self, dialog: SeriesDetailsDialog) -> None:
        if self.series_dialog is dialog:
            self.series_dialog = None
            if (
                self.series_backdrop is not None
                and self.series_backdrop.isVisible()
                and not self.series_backdrop_hiding
            ):
                self._hide_series_backdrop()

    def _show_series_backdrop(self) -> None:
        self.series_backdrop_hiding = False
        if self.series_backdrop is None:
            self.series_backdrop = QFrame(self)
            self.series_backdrop.setObjectName("seriesBackdrop")
            self.series_backdrop.setGeometry(self.rect())
            self.series_backdrop.mousePressEvent = self._series_backdrop_mouse_press
        self.series_backdrop.setGeometry(self.rect())
        self.series_backdrop.show()
        self.series_backdrop.raise_()
        effect = self.series_backdrop.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(self.series_backdrop)
            self.series_backdrop.setGraphicsEffect(effect)
            effect.setOpacity(0.0)
        self.series_backdrop_animation = QPropertyAnimation(effect, b"opacity", self)
        self.series_backdrop_animation.setDuration(430)
        self.series_backdrop_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.series_backdrop_animation.setStartValue(effect.opacity())
        self.series_backdrop_animation.setEndValue(1.0)
        self.series_backdrop_animation.start()

    def _series_backdrop_mouse_press(self, event) -> None:
        dialog = self.series_dialog
        if dialog is None or dialog._closing_animation_started:
            event.accept()
            return
        dialog.request_close()
        event.accept()

    def _hide_series_backdrop(self) -> None:
        if self.series_backdrop is None:
            return
        if self.series_backdrop_hiding:
            return
        self.series_backdrop_hiding = True
        effect = self.series_backdrop.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            self.series_backdrop.hide()
            self.series_backdrop_hiding = False
            return
        animation = QPropertyAnimation(effect, b"opacity", self)
        self.series_backdrop_animation = animation
        animation.setDuration(380)
        animation.setEasingCurve(QEasingCurve.InCubic)
        animation.setStartValue(effect.opacity())
        animation.setEndValue(0.0)
        animation.finished.connect(self._finish_series_backdrop_hide)
        animation.start()

    def _finish_series_backdrop_hide(self) -> None:
        if self.series_backdrop_animation is not None:
            self.series_backdrop_animation.stop()
            self.series_backdrop_animation = None
        if self.series_backdrop is not None:
            effect = self.series_backdrop.graphicsEffect()
            if isinstance(effect, QGraphicsOpacityEffect):
                effect.setOpacity(0.0)
            self.series_backdrop.hide()
        self.series_backdrop_hiding = False

    def _library_movie_for_path(self, path: str) -> Optional[Movie]:
        try:
            target = str(Path(path).resolve()).casefold()
        except OSError:
            target = str(path).casefold()
        for movie in self.movies:
            try:
                current = str(Path(movie.path).resolve()).casefold()
            except OSError:
                current = str(movie.path).casefold()
            if current == target:
                return movie
        return None

    def _collection_for_movie(self, movie: Movie) -> Optional[LibraryCollection]:
        return next(
            (
                collection
                for collection in build_collections(self.movies, self.roots)
                if any(item.path == movie.path for item in collection.movies)
            ),
            None,
        )

    def _prepare_player_playlist(self, movie: Movie) -> None:
        collection = self._collection_for_movie(movie)
        if collection is None:
            self.player.set_playlist([movie], movie, "")
            return
        self.player.set_playlist(collection.movies, movie, collection.title)

    def play_movie(self, movie: Movie) -> None:
        library_movie = self._library_movie_for_path(movie.path)
        if library_movie is not None:
            movie = library_movie
        if not Path(movie.path).is_file():
            QMessageBox.warning(self, APP_NAME, "This video is no longer available.")
            return
        if self.series_dialog is not None:
            self._play_movie_from_series_dialog(movie, self.series_dialog, start_ms=None)
            return
        current_page = self.pages.currentWidget()
        self.player_return_page = (
            current_page
            if current_page in {self.home, self.collection_page}
            else self.home
        )
        self._prepare_player_playlist(movie)
        self.pages.setCurrentWidget(self.player)
        self.player.play_movie(movie)

    def play_movie_from_home_hero(self, movie: Movie) -> None:
        if not Path(movie.path).is_file():
            QMessageBox.warning(self, APP_NAME, "This video is no longer available.")
            return
        snapshot = self.grab()
        overlay = PlayerLaunchTransitionOverlay(snapshot, self)
        self.player_launch_overlay = overlay
        overlay.finished.connect(self._finish_player_launch_transition)
        overlay.black_reached.connect(
            lambda selected=Movie.from_dict(movie.to_dict()), active=overlay, requested_start=None: (
                self._start_player_after_launch_transition(selected, active, requested_start)
            )
        )
        overlay.start()
        self.home.hero.stop_preview()

    def _play_movie_from_series_dialog(
        self, movie: Movie, dialog: SeriesDetailsDialog, start_ms: Optional[int] = 0
    ) -> None:
        snapshot = self.grab()
        overlay = PlayerLaunchTransitionOverlay(snapshot, self)
        self.player_launch_overlay = overlay
        overlay.finished.connect(self._finish_player_launch_transition)
        overlay.black_reached.connect(
            lambda selected=Movie.from_dict(movie.to_dict()), active=overlay, requested_start=start_ms: (
                self._start_player_after_launch_transition(selected, active, requested_start)
            )
        )
        overlay.start()

        if self.preview_task:
            self.preview_task.cancel()
            self.preview_task = None
            self.preview_task_key = ""
        try:
            dialog.hero.preview_controller.quiet_for_close()
        except Exception:
            pass
        try:
            dialog.hero.stop_preview()
        except Exception:
            pass
        dialog.hide()
        dialog._finished_emitted = True
        dialog.deleteLater()
        if self.series_dialog is dialog:
            self.series_dialog = None
        if self.series_backdrop_animation is not None:
            self.series_backdrop_animation.stop()
            self.series_backdrop_animation = None
        if self.series_backdrop is not None:
            effect = self.series_backdrop.graphicsEffect()
            if isinstance(effect, QGraphicsOpacityEffect):
                effect.setOpacity(0.0)
            self.series_backdrop.hide()
        self.series_backdrop_hiding = False

        self.player_return_page = self.home

    def _start_player_after_launch_transition(
        self, movie: Movie, overlay: PlayerLaunchTransitionOverlay, start_ms: Optional[int] = None
    ) -> None:
        library_movie = self._library_movie_for_path(movie.path)
        if library_movie is not None:
            movie = library_movie
        current_page = self.pages.currentWidget()
        self.player_return_page = (
            current_page
            if current_page in {self.home, self.collection_page}
            else self.home
        )
        self._prepare_player_playlist(movie)
        self.pages.setCurrentWidget(self.player)
        diagnostic_log(
            "window.player_launch.start",
            title=movie.title,
            path=movie.path,
            requested_start_ms=start_ms,
            saved_progress_ms=movie.progress_ms,
        )
        self.player.play_movie(movie, start_ms=start_ms)
        QTimer.singleShot(180, overlay.finish)

    def _finish_player_launch_transition(self) -> None:
        self.player_launch_overlay = None

    def show_previous_page(self) -> None:
        if self.is_player_fullscreen():
            self.exit_player_fullscreen()
        self.pages.setCurrentWidget(self.player_return_page)
        if self.player_return_page is self.home:
            self.rebuild_home()
        if self.close_after_player:
            self.close_after_player = False
            QTimer.singleShot(0, self.close)

    def show_home(self) -> None:
        if self.is_player_fullscreen():
            self.exit_player_fullscreen()
        self.pages.setCurrentWidget(self.home)
        self.rebuild_home()

    def _handle_escape(self) -> None:
        if self.player.track_panel and self.player.track_panel.isVisible():
            self.player._close_track_panel()
        elif self.is_player_fullscreen():
            self.player.hide_timer.stop()
            self.player._stop_control_animation()
            self.player.overlay.hide()
            self.exit_player_fullscreen()
        elif self.pages.currentWidget() is self.player:
            self.player.close_player()

    def save_progress(self, movie: Movie, progress: int, completed: bool) -> None:
        target_movie = self._library_movie_for_path(movie.path) or movie
        target_movie.progress_ms = 0 if completed else max(0, int(progress))
        target_movie.completed = completed
        target_movie.last_played = time.time()
        if target_movie is not movie:
            movie.progress_ms = target_movie.progress_ms
            movie.completed = target_movie.completed
            movie.last_played = target_movie.last_played
        self.save_library()

    def save_library(self) -> None:
        self.store.save(self.roots, self.movies, self.settings)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        diagnostic_log(
            "window.resize_event",
            window=widget_snapshot(self),
            fullscreen=self.isFullScreen(),
            current_page=type(self.pages.currentWidget()).__name__
            if hasattr(self, "pages")
            else "none",
            player=widget_snapshot(self.player) if hasattr(self, "player") else "none",
        )
        if self.series_backdrop is not None:
            self.series_backdrop.setGeometry(self.rect())
        if self.series_dialog is not None:
            self.series_dialog.recenter()
            self.series_dialog.raise_()
        self._sync_fullscreen_transition_cover()
        if (
            hasattr(self, "player")
            and self.pages.currentWidget() is self.player
            and (self._player_fullscreen or self._player_fullscreen_transitioning)
        ):
            self._schedule_player_fullscreen_layout_settle()

    def _schedule_player_fullscreen_layout_settle(self) -> None:
        if not hasattr(self, "player") or self.pages.currentWidget() is not self.player:
            return
        if self.player.movie is None:
            return
        self.player.fullscreen_recovery_generation += 1
        generation = self.player.fullscreen_recovery_generation
        for delay in (0, 25, 75, 150, 300):
            QTimer.singleShot(
                delay,
                lambda active=generation: self.player._settle_fullscreen_layout(active),
            )

    def closeEvent(self, event) -> None:
        if self.scan_task:
            self.scan_task.cancel()
        if self.preview_task:
            self.preview_task.cancel()
        if self.subtitle_cache_task:
            self.subtitle_cache_task.cancel()
        if self.pages.currentWidget() is self.player and self.player.movie:
            self.close_after_player = True
            event.ignore()
            self.player.close_player()
            return
        if self.native_resize_filter is not None:
            app = QApplication.instance()
            if app is not None:
                app.removeNativeEventFilter(self.native_resize_filter)
            self.native_resize_filter = None
        self.save_library()
        super().closeEvent(event)


STYLESHEET = """
* {
    font-family: "Netflix Sans";
    color: #f2f2f2;
    font-size: 12px;
}
QMainWindow, QStackedWidget, #homeContent, #homeScroll,
#homeScroll > QWidget > QWidget, #collectionContent, #collectionScroll,
#collectionScroll > QWidget > QWidget {
    background: #050505;
}
#homeHeader {
    background: transparent;
    border-bottom: 1px solid transparent;
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
#seriesDialog {
    background: transparent;
    border: none;
}
#seriesPanel {
    background: #181818;
    border: none;
    border-radius: 14px;
}
#seriesBackdrop {
    background: rgba(0, 0, 0, 178);
    border: none;
}
#seriesScroll, #seriesScroll > QWidget > QWidget, #seriesContent {
    background: transparent;
}
#seriesHeroOverlay {
    background: transparent;
}
#seriesClose {
    background: transparent;
    border: none;
}
#seriesTitle {
    color: #ffffff;
    font-size: 52px;
    font-weight: 900;
}
#seriesMeta {
    color: #d4d4d4;
    font-size: 14px;
    font-weight: 600;
}
#seriesPlay {
    background: #ffffff;
    color: #111111;
    border: none;
    border-radius: 4px;
    padding: 9px 18px;
    font-size: 15px;
    font-weight: 800;
}
#seriesPlay:hover {
    background: #dcdcdc;
}
#seriesCacheButton {
    background: rgba(255, 255, 255, 0.12);
    color: #ffffff;
    border: 1px solid rgba(255, 255, 255, 0.42);
    border-radius: 4px;
    padding: 9px 14px;
    font-size: 14px;
    font-weight: 800;
}
#seriesCacheButton:hover {
    background: rgba(255, 255, 255, 0.18);
}
#seriesCacheButton:disabled {
    color: #bdbdbd;
    border-color: rgba(255, 255, 255, 0.25);
    background: rgba(255, 255, 255, 0.08);
}

#seriesEpisodesHeading {
    color: #ffffff;
    font-size: 24px;
    font-weight: 800;
}
#seriesEpisodesName {
    color: #ffffff;
    font-size: 16px;
    font-weight: 700;
}
#seriesEpisodeRangeButton {
    background: #242424;
    border: 1px solid #585858;
    border-radius: 3px;
    color: #ffffff;
    font-size: 11px;
    font-weight: 600;
    padding: 0;
}
#seriesEpisodeRangeButton:hover, #seriesEpisodeRangeButton:pressed {
    background: #242424;
    border: 1px solid #6a6a6a;
}

QMenu#seriesEpisodeRangeMenu {
    background: #1f1f1f;
    border: 1px solid #4b4b4b;
    padding: 14px 0;
}
QMenu#seriesEpisodeRangeMenu::item {
    color: #f2f2f2;
    font-size: 15px;
    font-weight: 800;
    padding: 11px 34px 11px 16px;
}
QMenu#seriesEpisodeRangeMenu::item:selected {
    background: #333333;
}

#playerBlackout {
    background: #000000;
    border: none;
}
#episodePanel {
    background: #262626;
    border: none;
}
#episodePanelScroll, #episodePanelScroll > QWidget > QWidget, #episodePanelContents {
    background: transparent;
}
#episodePanelBack {
    background: transparent;
    border: none;
    padding: 0;
    margin-right: 6px;
}
#episodePanelBack:hover, #episodePanelBack:pressed {
    background: transparent;
    border: none;
}
#episodePanelTitle {
    color: #ffffff;
    font-size: 28px;
    font-weight: 900;
}
#episodeRangePanelTitle {
    background: transparent;
    color: #ffffff;
    font-size: 28px;
    font-weight: 900;
}
#episodeRangeContents {
    background: #262626;
}
#episodeRangeOption {
    background: #262626;
    border: none;
    color: #f2f2f2;
    font-size: 23px;
    font-weight: 800;
    min-height: 54px;
    padding: 0 20px;
    text-align: left;
}
#episodeRangeOption[active="true"] {
    border: 2px solid #ffffff;
    padding-left: 12px;
}
#episodeRangeOption:hover, #episodeRangeOption:pressed {
    background: #262626;
}

#seriesEpisodeDivider {
    background: #383838;
    border: none;
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
    install_debug_logging()
    install_crash_logging()
    if "--register-protocol" in sys.argv:
        return 0 if register_url_scheme() else 1

    register_url_scheme()
    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName("DordieWatch")
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    primary_screen = app.primaryScreen()
    diagnostic_log(
        "app.qt.start",
        qt_platform=app.platformName(),
        primary_screen=primary_screen.name() if primary_screen else "none",
        screen_geometry=primary_screen.geometry().getRect()
        if primary_screen
        else "none",
        device_pixel_ratio=primary_screen.devicePixelRatio()
        if primary_screen
        else "none",
        share_gl_contexts=QApplication.testAttribute(Qt.AA_ShareOpenGLContexts),
    )
    app.setStyle("Fusion")
    loaded_font_family = load_app_font(app)
    app.setStyleSheet(STYLESHEET.replace("Netflix Sans", loaded_font_family))
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













































































