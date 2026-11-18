; Shellslatee NSIS installer hooks.
;
; The first wizard page asks where the notes folder should live. The folder is
; always named "Shellslatee Notes"; the user picks the parent (default: the user
; profile, because Windows Defender Controlled Folder Access blocks unsigned
; apps writing to Documents). The choice is stored in notes_dir.txt so the app
; picks it up on first run.

!include "nsDialogs.nsh"

Var ShellslateeNotesPath
Var ShellslateeNotesField

; Uninstaller options. Each value stays 0 unless the user ticks the box on the
; uninstaller page, so silent uninstalls and update-mode uninstalls never touch
; user data.
Var SlAsrCheck
Var SlCfgCheck
Var SlEngineCheck
Var SlNotesCheck
Var SlDelAsr
Var SlDelCfg
Var SlDelEngine
Var SlDelNotes
Var SlNotesDir

Page custom ShellslateeNotesPage ShellslateeNotesLeave

; Declared here (before Tauri's confirm page) so the options window is shown
; before the final "uninstall" confirmation.
UninstPage custom un.ShellslateeOptionsPage un.ShellslateeOptionsLeave

Function un.ShellslateeOptionsPage
  ${If} ${Silent}
    Abort
  ${EndIf}

  StrCpy $SlNotesDir ""
  IfFileExists "$PROFILE\.config\shellslatee\notes_dir.txt" 0 sl_options_nonotes
    FileOpen $0 "$PROFILE\.config\shellslatee\notes_dir.txt" r
    FileRead $0 $SlNotesDir
    FileClose $0
  sl_options_nonotes:

  !insertmacro MUI_HEADER_TEXT "Remove Shellslatee" "Choose what should be removed from this PC."

  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}

  ${NSD_CreateLabel} 0 0 100% 28u "The program is always removed. Tick anything else you want deleted. Your notes are kept unless you tick the last box."
  Pop $0

  ${NSD_CreateCheckbox} 0 32u 100% 12u "Downloaded speech tools and models (ffmpeg, whisper, ~400 MB) and caches"
  Pop $SlAsrCheck
  ${NSD_SetState} $SlAsrCheck ${BST_CHECKED}

  ${NSD_CreateCheckbox} 0 48u 100% 12u "Settings and saved API keys"
  Pop $SlCfgCheck
  ${NSD_SetState} $SlCfgCheck ${BST_CHECKED}

  ${NSD_CreateCheckbox} 0 64u 100% 12u "Local engine Python packages (leaves Python itself installed)"
  Pop $SlEngineCheck
  ${NSD_SetState} $SlEngineCheck ${BST_CHECKED}

  ${NSD_CreateCheckbox} 0 84u 100% 12u "Also delete my notes folder"
  Pop $SlNotesCheck
  ${If} $SlNotesDir != ""
    ${NSD_CreateLabel} 14u 98u 100% 18u "$SlNotesDir"
    Pop $0
  ${Else}
    ${NSD_CreateLabel} 14u 98u 100% 18u "(no custom notes folder recorded)"
    Pop $0
  ${EndIf}

  nsDialogs::Show
FunctionEnd

Function un.ShellslateeOptionsLeave
  ${NSD_GetState} $SlAsrCheck $SlDelAsr
  ${NSD_GetState} $SlCfgCheck $SlDelCfg
  ${NSD_GetState} $SlEngineCheck $SlDelEngine
  ${NSD_GetState} $SlNotesCheck $SlDelNotes
FunctionEnd

Function ShellslateeNotesPage
  ${If} ${Silent}
    Abort
  ${EndIf}

  !insertmacro MUI_HEADER_TEXT "Notes folder" "Choose where Shellslatee keeps your lecture notes."

  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}

  ${NSD_CreateLabel} 0 0 100% 26u "Shellslatee saves Markdown notes in a folder named 'Shellslatee Notes'. Keep the suggested location or choose another parent folder."
  Pop $0

  ${NSD_CreateText} 0 30u -1 13u "$PROFILE\Shellslatee Notes"
  Pop $ShellslateeNotesField
  ${NSD_SetFocus} $ShellslateeNotesField
  SendMessage $ShellslateeNotesField ${EM_SETSEL} 0 -1

  ; Keep the folder from a previous install instead of resetting it.
  IfFileExists "$PROFILE\.config\shellslatee\notes_dir.txt" 0 shellslatee_nofile
    FileOpen $1 "$PROFILE\.config\shellslatee\notes_dir.txt" r
    FileRead $1 $2
    FileClose $1
    ${If} $2 != ""
      ${NSD_SetText} $ShellslateeNotesField $2
    ${EndIf}
  shellslatee_nofile:

  ${NSD_CreateButton} 0 48u 70u 14u "Browse folder..."
  Pop $0
  ${NSD_OnClick} $0 ShellslateeNotesBrowse

  ${NSD_CreateLabel} 0 68u 100% 24u "The folder is created during setup and is kept when you uninstall."
  Pop $0

  nsDialogs::Show
FunctionEnd

Function ShellslateeNotesBrowse
  ${NSD_GetText} $ShellslateeNotesField $0
  nsDialogs::SelectFolderDialog "Choose where the 'Shellslatee Notes' folder should live" "$0"
  Pop $1
  ${If} $1 != ""
  ${AndIf} $1 != "error"
    StrCpy $2 $1 "" -16
    ${If} $2 == "Shellslatee Notes"
      ${NSD_SetText} $ShellslateeNotesField "$1"
    ${Else}
      ${NSD_SetText} $ShellslateeNotesField "$1\Shellslatee Notes"
    ${EndIf}
  ${EndIf}
FunctionEnd

Function ShellslateeNotesLeave
  ${NSD_GetText} $ShellslateeNotesField $ShellslateeNotesPath
  ${If} $ShellslateeNotesPath == ""
    StrCpy $ShellslateeNotesPath "$PROFILE\Shellslatee Notes"
  ${EndIf}
FunctionEnd

!macro NSIS_HOOK_POSTINSTALL
  StrCpy $R0 $ShellslateeNotesPath
  ${If} $R0 == ""
    StrCpy $R0 "$PROFILE\Shellslatee Notes"
  ${EndIf}

  ; Create the folder and prove it accepts a write; a locked-down location
  ; silently falls back to the profile rather than leaving setup broken.
  ClearErrors
  CreateDirectory "$R0"
  FileOpen $8 "$R0\.shellslatee-write-test" w
  ${If} ${Errors}
    StrCpy $R0 "$PROFILE\Shellslatee Notes"
    CreateDirectory "$R0"
    ClearErrors
    FileOpen $8 "$R0\.shellslatee-write-test" w
  ${EndIf}
  ${IfNot} ${Errors}
    FileWrite $8 "ok"
    FileClose $8
    Delete "$R0\.shellslatee-write-test"
  ${EndIf}

  CreateDirectory "$PROFILE\.config\shellslatee"
  FileOpen $9 "$PROFILE\.config\shellslatee\notes_dir.txt" w
  FileWrite $9 "$R0"
  FileClose $9
  FileOpen $9 "$PROFILE\.config\shellslatee\install.log" a
  FileWrite $9 "notes_dir=$R0$\r$\n"
  FileClose $9
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; Stop the app and the spawned engine before deleting their files.
  nsExec::Exec 'taskkill /F /IM shellslatee-studio.exe'
  Pop $0
  nsExec::Exec 'taskkill /F /IM shellslatee.exe'
  Pop $0

  ; Downloaded speech tools, models and caches.
  ${If} $SlDelAsr == ${BST_CHECKED}
    RMDir /r "$LOCALAPPDATA\Shellslatee"
    RMDir /r "$PROFILE\.cache\huggingface"
    RMDir /r "$LOCALAPPDATA\pip\cache"
  ${EndIf}

  ; Settings, sealed keys and the plaintext provider key file.
  ${If} $SlDelCfg == ${BST_CHECKED}
    Delete "$PROFILE\.config\shellslatee\desktop.json"
    Delete "$PROFILE\.config\shellslatee\desktop_keys.json"
    Delete "$PROFILE\.config\shellslatee\desktop_keys.dat"
    Delete "$PROFILE\.config\shellslatee\aikey_key"
    Delete "$PROFILE\.config\shellslatee\install.log"
    Delete "$PROFILE\.config\shellslatee\notes_dir.txt"
    RMDir "$PROFILE\.config\shellslatee"
  ${EndIf}

  ; Local pip --user engine and the faster-whisper speech stack. Python itself
  ; is left installed because it may be shared with other software.
  ${If} $SlDelEngine == ${BST_CHECKED}
    nsExec::Exec 'cmd /c python -m pip uninstall -y shellslatee-engine faster-whisper ctranslate2'
    Pop $0
    nsExec::Exec 'cmd /c py -3 -m pip uninstall -y shellslatee-engine faster-whisper ctranslate2'
    Pop $0
  ${EndIf}

  ; Notes are user data. Delete only when explicitly ticked and the recorded
  ; path is a real folder path, never a drive root or a profile shell folder.
  ${If} $SlDelNotes == ${BST_CHECKED}
  ${AndIf} $SlNotesDir != ""
    StrCpy $0 $SlNotesDir "" 12
    ${If} $0 != ""
    ${AndIf} $SlNotesDir != "$PROFILE"
    ${AndIf} $SlNotesDir != "$PROFILE\"
    ${AndIf} $SlNotesDir != "$PROFILE\Desktop"
    ${AndIf} $SlNotesDir != "$PROFILE\Documents"
    ${AndIf} $SlNotesDir != "$PROFILE\Downloads"
    ${AndIf} $SlNotesDir != "$DESKTOP"
    ${AndIf} $SlNotesDir != "$DOCUMENTS"
      RMDir /r "$SlNotesDir"
    ${EndIf}
  ${EndIf}
!macroend
