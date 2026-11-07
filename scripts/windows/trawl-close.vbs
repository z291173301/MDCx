' ============================================================
'  trawl-close.vbs
'  Launch trawl-close.bat elevated (administrator) with a
'  completely HIDDEN console window - no CMD window appears.
'  A UAC confirmation dialog will appear - click "Yes" to allow.
'  Place this script in the SAME folder as trawl-close.bat.
'  The "hidden" argument tells trawl-close.bat to skip the
'  final pause so the hidden window exits by itself.
' ============================================================

Option Explicit

Dim fso, shellApp, scriptDir, batPath, q

Set fso = CreateObject("Scripting.FileSystemObject")
Set shellApp = CreateObject("Shell.Application")

' Use this script's own location to find the batch file
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = fso.BuildPath(scriptDir, "trawl-close.bat")

If Not fso.FileExists(batPath) Then
    MsgBox "trawl-close.bat not found. Put this script in the same folder as trawl-close.bat.", _
           vbExclamation, "Error"
    WScript.Quit 1
End If

q = Chr(34)

' cmd /c ""C:\path\trawl-close.bat" hidden"  (double-quote trick keeps spaces in the path safe)
' "runas" verb = elevate via UAC prompt
' last parameter 0 = SW_HIDE -> the elevated console window never appears
shellApp.ShellExecute "cmd.exe", "/c " & q & q & batPath & q & " hidden" & q, scriptDir, "runas", 0

Set fso = Nothing
Set shellApp = Nothing
