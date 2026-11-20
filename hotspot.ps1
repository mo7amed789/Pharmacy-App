# Pharmacy Enterprise v5.1 — PC local Wi-Fi hotspot (like SHAREit)
# ---------------------------------------------------------------------------
# Run from the app (hotspot.py) or manually:
#   powershell -NoProfile -ExecutionPolicy Bypass -File hotspot.ps1 -Action Start
#   powershell -NoProfile -ExecutionPolicy Bypass -File hotspot.ps1 -Action Status
#   powershell -NoProfile -ExecutionPolicy Bypass -File hotspot.ps1 -Action Stop
#   powershell -NoProfile -ExecutionPolicy Bypass -File hotspot.ps1 -Action Config
#   NOTE (v5.4): the app no longer configures a hotspot name/password.
#   Change the name/password only in Windows Settings > Network & internet > Mobile hotspot.
#   powershell -NoProfile -ExecutionPolicy Bypass -File hotspot.ps1 -Action Support
#
# HOW IT WORKS (modern Windows 10/11):
#   The legacy "netsh wlan set hostednetwork" is DEAD on most modern
#   Wi-Fi adapters ("Hosted network supported: No"). This script uses
#   the supported Windows Runtime API instead:
#     NetworkOperatorTetheringManager.CreateFromConnectionProfile(...)
#     StartTetheringAsync() / StopTetheringAsync()
#   It also calls DisableNoConnectionsTimeout() so the hotspot does
#   NOT auto-stop after ~5 minutes with no clients.
#
# OUTPUT: plain "KEY:value" lines on stdout, so hotspot.py can parse
#   them without JSON. Errors print "ERROR:<message>" and exit 1.
#   No internet is needed — the hotspot and the invoice server are local.
# ---------------------------------------------------------------------------
param(
    [string]$Action = "Status",
    [string]$Ssid = "",
    [string]$Passphrase = ""
)

$ErrorActionPreference = "Stop"

# Load the WinRT interop assembly (best effort; on PowerShell 7 the
# types may already be available, on 5.1 this is what makes AsTask work).
try { Add-Type -AssemblyName System.Runtime.WindowsRuntime } catch { }

function Out-Line($Key, $Value) {
    Write-Output ("{0}:{1}" -f $Key, $Value)
}

# Await a WinRT async operation the correct way in PowerShell 5.1.
#
# WHY NOT THE OLD WAY: in PowerShell 5.1 a WinRT IAsyncOperation<T>
# comes back as a System.__ComObject, and its result method is NOT
# exposed through COM interop — calling it directly fails with
# "Method invocation failed because [System.__ComObject] does not
# contain a method named GetResults", even when the operation itself
# already finished successfully. The supported workaround (the
# well-known Ben N. pattern) is to convert the WinRT operation to a
# .NET Task with System.Runtime.WindowsRuntime.AsyncOperationExtensions
# AsTask (for IAsyncOperation<T>) or AsyncActionExtensions AsTask
# (for IAsyncAction, e.g. StopTetheringAsync), Wait on that Task with
# a timeout, and read its Result. This script therefore NEVER calls
# the result method directly on a __ComObject.
#
# $ResultType: the .NET type of the operation result, e.g.
#   [Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult]
# Pass $null for IAsyncAction calls (no result, e.g. Stop).
# Returns the result object, or $null for actions / when the fallback
# below had to be used (callers must then verify via
# TetheringOperationalState instead of trusting the result object).
function Await-Op($Op, $ResultType = $null, [int]$TimeoutSec = 30) {
    if ($null -ne $Op) {
        # --- Primary path: AsTask via reflection ---
        try {
            if ($null -ne $ResultType) {
                # IAsyncOperation<T>: find AsTask<T> with exactly 1 parameter
                # (there is also an AsTask<T,TProgress> overload — skip it by
                # requiring exactly 1 generic argument).
                $extType = [System.Runtime.WindowsRuntime.AsyncOperationExtensions]
                $method = $extType.GetMethods() | Where-Object {
                    $_.Name -eq "AsTask" -and $_.IsGenericMethodDefinition -and
                    $_.GetGenericArguments().Count -eq 1 -and
                    $_.GetParameters().Count -eq 1
                } | Select-Object -First 1
                if ($method) {
                    $generic = $method.MakeGenericMethod($ResultType)
                    $task = $generic.Invoke($null, @($Op))
                    if (-not $task.Wait([TimeSpan]::FromSeconds($TimeoutSec))) {
                        throw "Timed out waiting for the Windows tethering API."
                    }
                    if ($task.IsFaulted) {
                        $inner = $null
                        try { $inner = $task.Exception.InnerException } catch { }
                        if ($inner) { throw $inner } else { throw $task.Exception }
                    }
                    if ($task.IsCanceled) {
                        throw "Windows API operation was cancelled."
                    }
                    return $task.Result
                }
            } else {
                # IAsyncAction: non-generic AsTask with exactly 1 parameter.
                $extType = [System.Runtime.WindowsRuntime.AsyncActionExtensions]
                $method = $extType.GetMethods() | Where-Object {
                    $_.Name -eq "AsTask" -and -not $_.IsGenericMethodDefinition -and
                    $_.GetParameters().Count -eq 1
                } | Select-Object -First 1
                if ($method) {
                    $task = $method.Invoke($null, @($Op))
                    if (-not $task.Wait([TimeSpan]::FromSeconds($TimeoutSec))) {
                        throw "Timed out waiting for the Windows tethering API."
                    }
                    if ($task.IsFaulted) {
                        $inner = $null
                        try { $inner = $task.Exception.InnerException } catch { }
                        if ($inner) { throw $inner } else { throw $task.Exception }
                    }
                    if ($task.IsCanceled) {
                        throw "Windows API operation was cancelled."
                    }
                    return $null
                }
            }
        } catch {
            # The object may be the OTHER kind than the caller assumed
            # (e.g. ConfigureAccessPointAsync returning IAsyncAction on
            # some Windows builds). Try the action conversion once.
            if ($null -ne $ResultType) {
                try {
                    $extType2 = [System.Runtime.WindowsRuntime.AsyncActionExtensions]
                    $m2 = $extType2.GetMethods() | Where-Object {
                        $_.Name -eq "AsTask" -and -not $_.IsGenericMethodDefinition -and
                        $_.GetParameters().Count -eq 1
                    } | Select-Object -First 1
                    if ($m2) {
                        $t2 = $m2.Invoke($null, @($Op))
                        if (-not $t2.Wait([TimeSpan]::FromSeconds($TimeoutSec))) {
                            throw "Timed out waiting for the Windows tethering API."
                        }
                        if ($t2.IsFaulted) {
                            $inner2 = $null
                            try { $inner2 = $t2.Exception.InnerException } catch { }
                            if ($inner2) { throw $inner2 } else { throw $t2.Exception }
                        }
                        if ($t2.IsCanceled) {
                            throw "Windows API operation was cancelled."
                        }
                        return $null
                    }
                } catch {
                    # Fall through to the polling fallback below.
                }
            }
            # Otherwise fall through to polling; a genuinely faulted
            # operation will surface there as Status = Error.
        }
        # --- Fallback: poll Status only, never the result method ---
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        while ($Op.Status -eq "Started") {
            if ($sw.Elapsed.TotalSeconds -gt $TimeoutSec) {
                throw "Timed out waiting for the Windows tethering API."
            }
            Start-Sleep -Milliseconds 200
        }
        if ($Op.Status -eq "Error") {
            throw ("Windows API error: " + $Op.ErrorCode)
        }
        if ($Op.Status -eq "Canceled") {
            throw "Windows API operation was cancelled."
        }
        # Completed, but the result cannot be read through COM interop,
        # so return $null and let the caller verify via
        # TetheringOperationalState / a config read instead.
        return $null
    }
    return $null
}

function Get-TetheringManager {
    # Load the WinRT types (no-op on PowerShell 7 where they are built in).
    try {
        [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType=WindowsRuntime] | Out-Null
        [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType=WindowsRuntime] | Out-Null
        [Windows.Networking.NetworkOperators.NetworkOperatorTetheringAccessPointConfiguration, Windows.Networking.NetworkOperators, ContentType=WindowsRuntime] | Out-Null
    } catch {
        # Types may already be loaded; continue and let the next call fail loudly if not.
    }
    $profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
    if (-not $profile) {
        # No "internet" profile (e.g. no internet right now) — fall back
        # to any Wi-Fi connection profile; tethering itself needs no internet.
        $profiles = [Windows.Networking.Connectivity.NetworkInformation]::GetConnectionProfiles() |
            Where-Object { $_.IsWlanConnectionProfile }
        if ($profiles) { $profile = $profiles | Select-Object -First 1 }
    }
    if (-not $profile) {
        throw "No Wi-Fi connection profile found. Turn Wi-Fi on first (Settings > Network & Internet > Wi-Fi), then try again."
    }
    return [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
}

function Get-CurrentConfig($Mgr) {
    try {
        $cfg = Await-Op $Mgr.GetCurrentAccessPointConfiguration() ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringAccessPointConfiguration])
        if (-not $cfg) {
            return @{ Ssid = ""; Password = "" }
        }
        return @{ Ssid = $cfg.Ssid; Password = $cfg.Passphrase }
    } catch {
        # Windows does not always expose the current SSID/password to scripts.
        return @{ Ssid = ""; Password = "" }
    }
}

try {
    switch ($Action.ToLower()) {
        "support" {
            $legacy = "unknown"
            try {
                $drivers = netsh wlan show drivers 2>$null | Out-String
                if ($drivers -match "Hosted network supported\s*:\s*(\w+)") { $legacy = $Matches[1] }
            } catch { }
            Out-Line "WINDOWS" ([System.Environment]::OSVersion.Version.ToString())
            Out-Line "LEGACY_HOSTED" $legacy
            Out-Line "NOTE" "Modern hotspot uses the WinRT tethering API, not legacy hostednetwork. LEGACY_HOSTED=No does not mean the hotspot cannot work."
        }
        "status" {
            $mgr = Get-TetheringManager
            Out-Line "STATUS" ([string]$mgr.TetheringOperationalState)
            $cfg = Get-CurrentConfig $mgr
            Out-Line "SSID" $cfg.Ssid
            Out-Line "PASSWORD" $cfg.Password
            # The WinRT tethering API does not expose a client count.
            Out-Line "CLIENTS" "unknown"
        }
        "config" {
            $mgr = Get-TetheringManager
            $cfg = Get-CurrentConfig $mgr
            Out-Line "SSID" $cfg.Ssid
            Out-Line "PASSWORD" $cfg.Password
        }
        "start" {
            $mgr = Get-TetheringManager
            try { $mgr.DisableNoConnectionsTimeout() } catch { }
            $result = Await-Op $mgr.StartTetheringAsync() ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult]) 60
            if ($null -ne $result -and $result.Status -ne "Success") {
                throw ("Tethering failed: " + $result.Status + " " + $result.AdditionalErrorMessage)
            }
            # Do NOT trust the async result object alone: verify the
            # hotspot is actually On (OperationalState = 1), waiting
            # briefly for the transition to finish.
            $on = $false
            for ($i = 0; $i -lt 25; $i++) {
                if ([int]$mgr.TetheringOperationalState -eq 1) { $on = $true; break }
                Start-Sleep -Milliseconds 200
            }
            if (-not $on) {
                $extra = ""
                if ($null -ne $result) { $extra = (" (result: " + $result.Status + " " + $result.AdditionalErrorMessage + ")") }
                throw ("Tethering did not turn on (state: " + $mgr.TetheringOperationalState + ")" + $extra + ". Check the Mobile Hotspot settings in Windows and try running the app as administrator.")
            }
            Out-Line "STATUS" "On"
            $cfg = Get-CurrentConfig $mgr
            Out-Line "SSID" $cfg.Ssid
            Out-Line "PASSWORD" $cfg.Password
        }
        "stop" {
            $mgr = Get-TetheringManager
            $null = Await-Op $mgr.StopTetheringAsync() $null 60
            Out-Line "STATUS" "Off"
        }
        "configure" {
            if (-not $Ssid) { throw "SSID is required. Example: -Ssid <Windows hotspot name>" }
            if ($Passphrase.Length -lt 8) { throw "Wi-Fi password must be at least 8 characters." }
            $mgr = Get-TetheringManager
            $cfg = New-Object Windows.Networking.NetworkOperators.NetworkOperatorTetheringAccessPointConfiguration
            $cfg.Ssid = $Ssid
            $cfg.Passphrase = $Passphrase
            # ConfigureAccessPointAsync returns an operation result on
            # most builds, but an action on some — Await-Op tries the
            # operation conversion first and falls back to the action one.
            $result = Await-Op $mgr.ConfigureAccessPointAsync($cfg) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult]) 60
            if ($null -ne $result -and $result.Status -ne "Success") {
                throw ("Configuring the hotspot failed: " + $result.Status + " " + $result.AdditionalErrorMessage)
            }
            Out-Line "STATUS" "Configured"
            Out-Line "SSID" $Ssid
        }
        default {
            throw ("Unknown action: " + $Action + ". Use Start, Stop, Status, Config, Configure or Support.")
        }
    }
    exit 0
} catch {
    Out-Line "ERROR" $_.Exception.Message
    exit 1
}
