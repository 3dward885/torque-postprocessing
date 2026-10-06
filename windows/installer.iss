#ifndef BundleDir
  #error BundleDir must point to the built application directory.
#endif
#ifndef OutputPath
  #error OutputPath must specify a new release directory.
#endif
#ifndef MaxAppPath
  #error MaxAppPath must be derived from the bundled library paths.
#endif
#ifndef BuildNumber
  #define BuildNumber 1
#endif

[Setup]
AppId={{7192D918-D36B-4D0E-9F83-F90C3C68A6F1}
AppName=Torque Data Postprocessing
AppVersion=1.5
AppPublisher=Torque Data Postprocessing
DefaultDirName={localappdata}\Programs\Torque Data Postprocessing
DefaultGroupName=Torque Data Postprocessing
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputPath}
OutputBaseFilename=Torque_Data_Postprocessing_1.5_Setup_x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AllowNoIcons=yes
DisableProgramGroupPage=no
UninstallDisplayIcon={app}\Torque Data Postprocessing.exe
CloseApplications=no
RestartApplications=no
SetupLogging=yes
VersionInfoVersion=1.5.0.{#BuildNumber}
VersionInfoDescription=Torque Data Postprocessing Setup

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Torque Data Postprocessing"; Filename: "{app}\Torque Data Postprocessing.exe"; WorkingDir: "{userdocs}"
Name: "{group}\Uninstall Torque Data Postprocessing"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Torque Data Postprocessing"; Filename: "{app}\Torque Data Postprocessing.exe"; WorkingDir: "{userdocs}"; Tasks: desktopicon

[Run]
Filename: "{app}\Torque Data Postprocessing.exe"; Description: "Open Torque Data Postprocessing"; Flags: nowait postinstall skipifsilent

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Entry: TFindRec;
  Contents: AnsiString;
  Occupied: Boolean;
begin
  Result := '';
  if Length(ExpandConstant('{app}')) > {#MaxAppPath} then begin
    Result := 'This installation path is too long for the bundled Windows libraries. Choose a shorter folder, such as the default installation location.';
    exit;
  end;
  Occupied := False;
  if FindFirst(ExpandConstant('{app}\*'), Entry) then begin
    try
      repeat
        if (Entry.Name <> '.') and (Entry.Name <> '..') then
          Occupied := True;
      until not FindNext(Entry);
    finally
      FindClose(Entry);
    end;
  end;
  if Occupied then begin
    if not LoadStringFromFile(ExpandConstant('{app}\install_identity.txt'), Contents) or
       (Trim(String(Contents)) <> '7192D918-D36B-4D0E-9F83-F90C3C68A6F1') then
      Result := 'Choose an empty folder or an existing Torque Data Postprocessing installation. No files were changed.';
  end;
end;
