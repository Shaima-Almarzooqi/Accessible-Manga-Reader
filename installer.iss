; Installer for Accessible Manga Reader.
;
; A conventional per-machine install into Program Files, so it behaves
; the way people expect and one install serves every account on the
; computer. Windows asks for administrator permission to write there,
; which means the elevation prompt appears when installing and again
; when the app installs an update -- worth knowing, because it arrives
; partway through an update rather than at a moment you chose.
;
; Built from the folder version, so the installed copy is the one that
; starts quickly rather than unpacking itself on every launch.
;
; ArchName is passed in by the build workflow: ISCC ... /DArchName=x64

#ifndef ArchName
  #define ArchName "x64"
#endif
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppName=Accessible Manga Reader
AppVersion={#AppVersion}
AppPublisher=Shaima Almarzooqi
AppSupportURL=https://github.com/Shaima-Almarzooqi/Accessible-Manga-Reader
DefaultDirName={autopf}\Accessible Manga Reader
DefaultGroupName=Accessible Manga Reader
DisableProgramGroupPage=yes
; Program Files needs administrator rights.
PrivilegesRequired=admin
OutputDir=dist
OutputBaseFilename=AccessibleMangaReader-{#ArchName}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; The uninstaller and the update both need the app closed first.
CloseApplications=yes
RestartApplications=no
#if ArchName == "arm64"
ArchitecturesAllowed=arm64
#else
ArchitecturesAllowed=x64compatible
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist-folder\AccessibleMangaReader-{#ArchName}\*"; \
    DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Accessible Manga Reader"; \
    Filename: "{app}\AccessibleMangaReader-{#ArchName}.exe"
Name: "{group}\Uninstall Accessible Manga Reader"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Accessible Manga Reader"; \
    Filename: "{app}\AccessibleMangaReader-{#ArchName}.exe"; \
    Tasks: desktopicon

[Run]
; Offered rather than automatic, and unchecked when the installer was
; started silently by the app updating itself -- in that case the app
; restarts itself instead.
Filename: "{app}\AccessibleMangaReader-{#ArchName}.exe"; \
    Description: "Open Accessible Manga Reader"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The installed program only. Books, settings and downloaded voices
; live in the user's own data folder and are deliberately left alone,
; so uninstalling and reinstalling does not lose a processed library.
Type: filesandordirs; Name: "{app}"
