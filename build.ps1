param(
    [string]$FfmpegPath = "",
    [string]$FfprobePath = "",
    [string]$MpvRuntimePath = ""
)

if (-not $MpvRuntimePath) {
    $MpvRuntimePath = Join-Path $PSScriptRoot "runtime\mpv"
}

if (-not $FfmpegPath) {
    $ffmpegCommand = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($ffmpegCommand) {
        $FfmpegPath = $ffmpegCommand.Source
    }
}

if (-not $FfprobePath) {
    $ffprobeCommand = Get-Command ffprobe -ErrorAction SilentlyContinue
    if ($ffprobeCommand) {
        $FfprobePath = $ffprobeCommand.Source
    }
}

$arguments = @(
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "DordieWatch",
    "--paths", "vendor",
    "--hidden-import", "mpv",
    "--collect-all", "PIL",
    "dordiewatch.py"
)

if ($FfmpegPath -and (Test-Path -LiteralPath $FfmpegPath)) {
    $arguments += @("--add-binary", "$FfmpegPath;.")
}

if ($FfprobePath -and (Test-Path -LiteralPath $FfprobePath)) {
    $arguments += @("--add-binary", "$FfprobePath;.")
}

$libMpv = Join-Path $MpvRuntimePath "libmpv-2.dll"

if (Test-Path -LiteralPath $libMpv) {
    $arguments += @("--add-binary", "$libMpv;mpv")
}

python -m PyInstaller @arguments
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$builtExecutable = Join-Path $PSScriptRoot "dist\DordieWatch\DordieWatch.exe"
if (Test-Path -LiteralPath $builtExecutable) {
    try {
        $protocolRoot = "HKCU:\Software\Classes\dordiewatch"
        [void](New-Item -Path $protocolRoot -Force -ErrorAction Stop)
        Set-Item -Path $protocolRoot -Value "URL:DordieWatch Protocol" -ErrorAction Stop
        New-ItemProperty -Path $protocolRoot -Name "URL Protocol" -Value "" -PropertyType String -Force -ErrorAction Stop | Out-Null

        $defaultIcon = Join-Path $protocolRoot "DefaultIcon"
        [void](New-Item -Path $defaultIcon -Force -ErrorAction Stop)
        Set-Item -Path $defaultIcon -Value "`"$builtExecutable`",0" -ErrorAction Stop

        $openCommand = Join-Path $protocolRoot "shell\open\command"
        [void](New-Item -Path $openCommand -Force -ErrorAction Stop)
        Set-Item -Path $openCommand -Value "`"$builtExecutable`" `"%1`"" -ErrorAction Stop
    } catch {
        Write-Warning "DordieWatch was built, but the dordiewatch:// URL protocol could not be registered."
    }
}
