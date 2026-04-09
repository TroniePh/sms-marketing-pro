; ══════════════════════════════════════════════════════════════
;  SMS Marketing Pro — Inno Setup Script (Bản Chuẩn 100%)
; ══════════════════════════════════════════════════════════════

#define MyAppName      "SMS Marketing Pro"
#define MyAppVersion   "1.0.0"
#define MyAppPublisher "Phạm Duy"
#define MyAppContact   "duyhondavn@gmail.com"
#define MyAppURL       "https://github.com/capcom6/android-sms-gateway"
#define MyAppExeName   "SMS_Marketing_Pro.exe"

[Setup]
AppId={{B7E3F1A2-9C04-4D8B-A1F6-7E2D5C8B3A01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppContact={#MyAppContact}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayName={#MyAppName}
; Lấy Icon cho trình gỡ cài đặt
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=output
OutputBaseFilename=Setup_SMS_Marketing
; ------------------------------------------
; Đã thêm dòng cấu hình Logo cho file Setup
SetupIconFile=logo.ico
; ------------------------------------------
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
DisableProgramGroupPage=yes
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
ShowLanguageDialog=auto

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Tạo biểu tượng trên Desktop"; GroupDescription: "Tùy chọn bổ sung:"

[Files]
; CỰC KỲ QUAN TRỌNG: Chỉ lấy toàn bộ dữ liệu BÊN TRONG thư mục đã build của PyInstaller
; Đảm bảo rằng trong thư mục "dist" của anh có chứa một thư mục tên là "SMS_Marketing_Pro" (hoặc tên app anh đặt)
Source: "dist\SMS_Marketing_Pro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.db,*.sqlite,*.sqlite3"

[Icons]
; Shortcut trong Start Menu (Sẽ tự động lấy Icon của file EXE)
Name: "{group}\{#MyAppName}";    Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Gỡ cài đặt {#MyAppName}"; Filename: "{uninstallexe}"

; Shortcut trên Desktop (Sẽ tự động lấy Icon của file EXE)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Chạy app ngay sau khi cài xong
Filename: "{app}\{#MyAppExeName}"; Description: "Khởi chạy {#MyAppName}"; Flags: nowait postinstall skipifsilent