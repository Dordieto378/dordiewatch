[CmdletBinding()]
param(
    [ValidateSet("Debug", "Release")]
    [string] $Configuration = "Release",

    [ValidateSet("win-x64", "win-arm64", "win-x86")]
    [string] $Runtime = "win-x64",

    [string] $OutputDirectory,

    [switch] $TrustCertificate
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$projectPath = Join-Path $repositoryRoot "DordieWatch.App\DordieWatch.App.csproj"

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $repositoryRoot "publish\DordieWatch"
}

$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
$publishRoot = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot "publish"))
$publishPrefix = $publishRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar

if (-not $OutputDirectory.StartsWith($publishPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "The output directory must be inside '$publishRoot'."
}

function Get-DotNetCommand {
    $localDotNet = Join-Path $repositoryRoot ".dotnet\dotnet.exe"
    if (Test-Path -LiteralPath $localDotNet) {
        return $localDotNet
    }

    $command = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "The .NET SDK was not found. Install the SDK version from global.json and try again."
    }

    return $command.Source
}

function Get-CodeSigningCertificate {
    $subject = "CN=DordieWatch Local Development"
    $certificate = Get-ChildItem -Path Cert:\CurrentUser\My -CodeSigningCert |
        Where-Object {
            $_.Subject -eq $subject -and
            $_.HasPrivateKey -and
            $_.NotAfter -gt (Get-Date).AddDays(30)
        } |
        Sort-Object NotAfter -Descending |
        Select-Object -First 1

    if ($null -ne $certificate) {
        return $certificate
    }

    if (-not $TrustCertificate) {
        throw "No DordieWatch development certificate exists. Run this script once with -TrustCertificate."
    }

    Write-Host "Creating a local DordieWatch code-signing certificate..."
    return New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $subject `
        -FriendlyName "DordieWatch local development signing" `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -KeyAlgorithm RSA `
        -KeyLength 3072 `
        -HashAlgorithm SHA256 `
        -KeyExportPolicy NonExportable `
        -NotAfter (Get-Date).AddYears(3)
}

function Test-CertificateInStore {
    param(
        [Parameter(Mandatory)]
        [System.Security.Cryptography.X509Certificates.X509Certificate2] $Certificate,

        [Parameter(Mandatory)]
        [System.Security.Cryptography.X509Certificates.StoreName] $StoreName
    )

    $store = [System.Security.Cryptography.X509Certificates.X509Store]::new(
        $StoreName,
        [System.Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser)

    try {
        $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadOnly)
        return $store.Certificates.Find(
            [System.Security.Cryptography.X509Certificates.X509FindType]::FindByThumbprint,
            $Certificate.Thumbprint,
            $false).Count -gt 0
    }
    finally {
        $store.Dispose()
    }
}

function Add-CertificateToStore {
    param(
        [Parameter(Mandatory)]
        [System.Security.Cryptography.X509Certificates.X509Certificate2] $Certificate,

        [Parameter(Mandatory)]
        [System.Security.Cryptography.X509Certificates.StoreName] $StoreName
    )

    $store = [System.Security.Cryptography.X509Certificates.X509Store]::new(
        $StoreName,
        [System.Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser)

    try {
        $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
        $store.Add($Certificate)
    }
    finally {
        $store.Dispose()
    }
}

$certificate = Get-CodeSigningCertificate
$trustedAsRoot = Test-CertificateInStore -Certificate $certificate -StoreName Root
$trustedAsPublisher = Test-CertificateInStore -Certificate $certificate -StoreName TrustedPublisher

if (-not ($trustedAsRoot -and $trustedAsPublisher)) {
    if (-not $TrustCertificate) {
        throw "The DordieWatch certificate is not trusted. Run this script once with -TrustCertificate."
    }

    Write-Host "Trusting the certificate for the current Windows user..."
    if (-not $trustedAsRoot) {
        Add-CertificateToStore -Certificate $certificate -StoreName Root
    }
    if (-not $trustedAsPublisher) {
        Add-CertificateToStore -Certificate $certificate -StoreName TrustedPublisher
    }
}

if (Test-Path -LiteralPath $OutputDirectory) {
    $resolvedOutput = (Resolve-Path -LiteralPath $OutputDirectory).Path
    if (-not $resolvedOutput.StartsWith($publishPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean output outside '$publishRoot'."
    }

    Remove-Item -LiteralPath $resolvedOutput -Recurse -Force
}

$dotnet = Get-DotNetCommand
Write-Host "Publishing DordieWatch for $Runtime..."
& $dotnet publish $projectPath `
    --configuration $Configuration `
    --runtime $Runtime `
    --self-contained true `
    --output $OutputDirectory `
    -p:PublishSingleFile=true `
    -p:RunAnalyzers=false `
    -p:DebugSymbols=false `
    -p:DebugType=None

if ($LASTEXITCODE -ne 0) {
    throw "dotnet publish failed with exit code $LASTEXITCODE."
}

# VideoLAN.LibVLC.Windows contains native files for every Windows CPU. Only the
# selected runtime can be loaded by this build; removing the others keeps the
# artifact small and avoids needless signature checks.
$libVlcRoot = Join-Path $OutputDirectory "libvlc"
if (Test-Path -LiteralPath $libVlcRoot) {
    Get-ChildItem -LiteralPath $libVlcRoot -Directory |
        Where-Object { $_.Name -ne $Runtime } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
}

$signablePaths = @(
    Get-ChildItem -LiteralPath $OutputDirectory -Recurse -File |
        Where-Object { $_.Extension -in ".exe", ".dll" } |
        Select-Object -ExpandProperty FullName
)

$signedCount = 0
foreach ($existingSignature in (Get-AuthenticodeSignature -LiteralPath $signablePaths)) {
    if ($existingSignature.Status -eq [System.Management.Automation.SignatureStatus]::Valid) {
        continue
    }

    $signature = Set-AuthenticodeSignature `
        -LiteralPath $existingSignature.Path `
        -Certificate $certificate `
        -HashAlgorithm SHA256 `
        -IncludeChain All

    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw "Failed to sign '$($existingSignature.Path)': $($signature.StatusMessage)"
    }

    $signedCount++
}

$invalidFiles = Get-AuthenticodeSignature -LiteralPath $signablePaths |
    ForEach-Object {
        $signature = $_
        if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
            [PSCustomObject]@{
                Path = $signature.Path
                Status = $signature.Status
                Message = $signature.StatusMessage
            }
        }
    }

if ($invalidFiles) {
    $invalidFiles | Format-Table -AutoSize | Out-Host
    throw "One or more executable files do not have a valid signature."
}

$executable = Join-Path $OutputDirectory "DordieWatch.App.exe"
Write-Host "Signed $signedCount previously unsigned files."
Write-Host "Trusted development build: $executable"
