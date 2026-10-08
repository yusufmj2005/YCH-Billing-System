; ============================================================================
;  BusinessPOS - Inno Setup 6 script
;  Build with build\build_installer.bat (passes /DMyAppVersion=x.y.z).
;
;  * Program files go to Program Files (or the per-user Programs folder when
;    the user chooses "install for me only").
;  * Business data lives in %LOCALAPPDATA%\BusinessPOS and is NEVER installed,
;    replaced or removed by this installer during install/upgrade.
;  * Upgrades: keep the same AppId. Old program files are replaced; the
;    database is upgraded in place by the application (after an automatic
;    pre-upgrade backup).
;  * Uninstall removes program files, shortcuts and registration. Business
;    data is kept unless the user explicitly asks (twice) to delete it.
; ============================================================================

#define MyAppName "BusinessPOS"
#ifndef MyAppVersion
  #define MyAppVersion "1.1.1"
#endif
; Publisher shown in "Apps & features". Override: ISCC /DMyAppPublisher="Your Company"
#ifndef MyAppPublisher
  #define MyAppPublisher "Mohammed Yusuf J"
#endif
#define MyAppExeName "BusinessPOS.exe"
#define MyAppMutex "BusinessPOS_SingleInstance_Mutex"

[Setup]
; NEVER change AppId: it links upgrades and the uninstaller to existing installs.
AppId={{8F2A6C1E-5B7D-4E8A-9C3F-2D1B0A7E6F45}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppCopyright=Copyright (c) 2026 {#MyAppPublisher}. All rights reserved.
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoDescription={#MyAppName} Setup
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
AllowNoIcons=yes
OutputDir=..\installer_output
OutputBaseFilename=BusinessPOS-Setup
SetupIconFile=..\assets\icons\app.ico
LicenseFile=..\LICENSE
#ifdef SIGN
; Signed release builds (build_installer.bat passes /DSIGN and the "bpos" sign tool).
SignTool=bpos
SignedUninstaller=yes
#endif
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
AppMutex={#MyAppMutex}
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[InstallDelete]
; Remove the previous version's bundled libraries before copying the new ones
; (program folder only - business data is stored elsewhere).
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\BusinessPOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD-PARTY-NOTICES.md"; DestDir: "{app}"; DestName: "THIRD-PARTY-NOTICES.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function IsUpgrade(): Boolean;
var
  Key: String;
begin
  Key := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{8F2A6C1E-5B7D-4E8A-9C3F-2D1B0A7E6F45}_is1';
  Result := RegKeyExists(HKLM, Key) or RegKeyExists(HKCU, Key);
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if IsUpgrade() and (not WizardSilent()) then
    MsgBox('An existing BusinessPOS installation was found and will be updated.' + #13#10#13#10 +
           'Your business data (sales, stock, customers, settings, users) is kept. ' +
           'BusinessPOS automatically creates a backup before upgrading its database ' +
           'the first time the new version starts.' + #13#10#13#10 +
           'For extra safety you may cancel now and use Backup & Restore in BusinessPOS ' +
           'to save a copy to a USB drive first.', mbInformation, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent()) then
  begin
    DataDir := ExpandConstant('{localappdata}\BusinessPOS');
    if DirExists(DataDir) then
    begin
      if MsgBox('BusinessPOS has been removed.' + #13#10#13#10 +
                'Your business data (database, backups, logs and exported files) is still ' +
                'stored in:' + #13#10 + DataDir + #13#10#13#10 +
                'Do you also want to PERMANENTLY DELETE this business data?' + #13#10 +
                'Choose No to keep it (recommended).',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      begin
        if MsgBox('This will permanently delete ALL sales, inventory, customer, supplier, ' +
                  'employee and financial records and all backups in this folder. ' +
                  'This cannot be undone.' + #13#10#13#10 + 'Delete the business data now?',
                  mbError, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        begin
          if not DelTree(DataDir, True, True, True) then
            MsgBox('Some files could not be deleted. You can remove the folder manually: ' +
                   DataDir, mbInformation, MB_OK);
        end;
      end;
    end;
  end;
end;
