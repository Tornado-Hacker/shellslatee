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

Page custom ShellslateeNotesPage ShellslateeNotesLeave

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
  ; The notes folder is user data; uninstalling never removes it.
!macroend
