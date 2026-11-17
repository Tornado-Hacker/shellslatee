; Shellslatee NSIS installer hooks.
;
; The notes vault is created during setup instead of waiting for first run, so
; a fresh install already has a home for Markdown notes. The path is also
; written to the app's config folder so the onboarding screen can prefill it.

!macro NSIS_HOOK_POSTINSTALL
  CreateDirectory "$DOCUMENTS\Shellslatee Notes"
  CreateDirectory "$PROFILE\.config\shellslatee"
  FileOpen $0 "$PROFILE\.config\shellslatee\notes_dir.txt" w
  FileWrite $0 "$DOCUMENTS\Shellslatee Notes"
  FileClose $0
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; The notes folder is user data; uninstalling never removes it.
!macroend
