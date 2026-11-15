import os
from pathlib import Path
import shutil
import subprocess
import tempfile


_POWERSHELL_SCRIPT = r"""param(
    [Parameter(Mandatory = $true)]
    [string]$TargetPath,
    [Parameter(Mandatory = $true)]
    [string]$ShortcutPath,
    [Parameter(Mandatory = $true)]
    [string]$RelativeLinkPath,
    [Parameter(Mandatory = $true)]
    [string]$WorkingDirectory
)

$ErrorActionPreference = "Stop"
$source = @'
using System;
using System.Runtime.InteropServices;

[ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IShellLinkW {
    void GetPath(IntPtr path, int cch, IntPtr findData, uint flags);
    void GetIDList(out IntPtr idList);
    void SetIDList(IntPtr idList);
    void GetDescription(IntPtr name, int cch);
    void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string name);
    void GetWorkingDirectory(IntPtr dir, int cch);
    void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string dir);
    void GetArguments(IntPtr args, int cch);
    void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string args);
    void GetHotkey(out short hotkey);
    void SetHotkey(short hotkey);
    void GetShowCmd(out int showCmd);
    void SetShowCmd(int showCmd);
    void GetIconLocation(IntPtr iconPath, int cch, out int iconIndex);
    void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string iconPath, int iconIndex);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string path, uint reserved);
    void Resolve(IntPtr hwnd, uint flags);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string path);
}

[ComImport, Guid("0000010B-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IPersistFile {
    void GetClassID(out Guid classId);
    [PreserveSig] int IsDirty();
    void Load([MarshalAs(UnmanagedType.LPWStr)] string fileName, uint mode);
    void Save([MarshalAs(UnmanagedType.LPWStr)] string fileName, [MarshalAs(UnmanagedType.Bool)] bool remember);
    void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string fileName);
    void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string fileName);
}

public static class ShellLinkTools {
    private static readonly Guid ClsidShellLink = new Guid("00021401-0000-0000-C000-000000000046");

    public static void CreateShortcut(string target, string shortcutPath, string relativeLinkPath, string workingDirectory) {
        Type shellLinkType = Type.GetTypeFromCLSID(ClsidShellLink);
        IShellLinkW link = (IShellLinkW)Activator.CreateInstance(shellLinkType);
        link.SetPath(target);
        link.SetWorkingDirectory(workingDirectory);
        link.SetRelativePath(relativeLinkPath, 0);
        ((IPersistFile)link).Save(shortcutPath, true);
    }
}
'@

Add-Type -TypeDefinition $source
[ShellLinkTools]::CreateShortcut($TargetPath, $ShortcutPath, $RelativeLinkPath, $WorkingDirectory)
"""


def create_shortcut(
    target: Path,
    shortcut: Path,
    working_directory: Path,
    relative_link_path: Path | None = None,
) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        raise FileNotFoundError("Windows PowerShell was not found; shortcut creation is required.")

    target = target.resolve()
    shortcut = shortcut.resolve()
    relative_link_path = (relative_link_path or shortcut).resolve()
    working_directory = working_directory.resolve()
    relative_working_directory = os.path.relpath(working_directory, shortcut.parent)

    with tempfile.TemporaryDirectory(prefix="vn_shortcut_") as temporary:
        script_path = Path(temporary) / "create_shortcut.ps1"
        script_path.write_text(_POWERSHELL_SCRIPT, encoding="utf-8-sig", newline="\r\n")
        subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-TargetPath",
                str(target),
                "-ShortcutPath",
                str(shortcut),
                "-RelativeLinkPath",
                str(relative_link_path),
                "-WorkingDirectory",
                relative_working_directory,
            ],
            check=True,
        )
