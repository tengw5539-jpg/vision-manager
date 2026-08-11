' VisionPower 视觉模型管理器 - 静默启动（无黑窗口）
Set ws = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
ws.Run """" & scriptDir & "\start.bat""", 0, False
