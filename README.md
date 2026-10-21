# DordieWatch

## Publish a Windows development build

Smart App Control can block ordinary unsigned .NET publish output, including
application DLLs loaded by `DordieWatch.App.exe`. Use the trusted development
publish script on a Windows development machine:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\Publish-TrustedDevBuild.ps1 -TrustCertificate
```

The first run creates a non-exportable code-signing certificate and trusts it
for the current Windows user. The script publishes a self-contained,
single-file Windows build, preserves valid third-party signatures, signs the
remaining executable files, and verifies every `.exe` and `.dll` in the output.
The application uses Windows' signed built-in SQLite library so an unsigned
native SQLite DLL is not required.

Later builds can omit `-TrustCertificate`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\Publish-TrustedDevBuild.ps1
```

The executable is written to `publish\DordieWatch\DordieWatch.App.exe`,
replacing the previous generated build.

This certificate is only for local development. Public releases must use a
trusted code-signing provider or Microsoft Store signing.
