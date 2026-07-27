# DordieWatch

A Netflix-inspired local movie and series library with a custom PySide6 and
mpv/libmpv player.

## Library layout

Put each movie or series in its own top-level folder inside `videos`:

```text
videos/
  16589/
    Episode 01.mkv
    Episode 02.mkv
```

The app treats each top-level folder as one library title. Artwork files in
video folders are ignored. A linked title uses only the cover returned by the
DordieList database; an unlinked title displays a neutral generated
placeholder.

The saved catalog is shown immediately when DordieWatch opens. Video files are
not decoded during startup; use the refresh button when video files change.
Playback progress and series subtitle choices are saved automatically.

## DordieList website connection

DordieWatch registers the `dordiewatch://` Windows URL protocol when it starts.
After opening the app once, the **Play in DordieWatch** button on an anime or
hentai page in DordieList will:

1. send the website's media ID and a short-lived signed metadata URL to the app;
2. find the top-level local folder linked to that exact database ID;
3. save the media ID on every episode and in that folder's
   `.dordielist.json` marker;
4. cache and display the cover image from the DordieList database; and
5. open the matching movie or series in DordieWatch.

The video files remain local. When an ID has not been linked yet, DordieWatch
shows the available local folders and asks you to choose the correct one once.
Folder names are never used to infer a database connection. Later launches
resolve the folder only through the saved database ID.

A top-level folder named exactly after the numeric database ID, such as
`videos/16589`, is linked directly without needing a marker file.

The Refresh button rescans the local `videos` folder and then asks DordieList
for current metadata and covers for every linked database ID. New folders with
a numeric ID or `.dordielist.json` marker are therefore connected during the
same refresh. Open any anime or hentai from the website once after installing
this version so DordieWatch can save its signed refresh connection.

## Run from source

Requirements:

- Python 3.10+
- PySide6
- Pillow
- FFmpeg and FFprobe
- mpv/libmpv runtime in `runtime\mpv`

```powershell
python -m pip install -r requirements.txt
python dordiewatch.py
```

Project folders are resolved relative to `dordiewatch.py`, so the project can
be moved without changing hard-coded paths.

## Player controls

- Press `Space` / `K` or use the play button - play or pause
- Press `Left` / `Right` or `J` / `L` - seek 10 seconds
- Click or drag the timeline - seek directly
- Press `Up` / `Down` - change volume
- Press `M` - mute
- Press `C` - toggle subtitles
- Press `F` - toggle fullscreen
- Press `Escape` - leave fullscreen or return to the library
- Use the bottom-right subtitle menu - choose embedded subtitles or audio

## Build

```powershell
.\build.ps1
```

The build replaces `dist\DordieWatch\DordieWatch.exe` and bundles mpv, FFmpeg,
and FFprobe. It also registers that executable as the handler for
`dordiewatch://` links for the current Windows user.
