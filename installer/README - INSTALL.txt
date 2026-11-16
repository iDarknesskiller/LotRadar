LOTRADAR - WINDOWS INSTALLER PACKAGE

Package version, source commit and build type are recorded in Install-Manifest.json
(package_version, source_commit, build_type). A build_type other than "production"
is a development package and must not be handed out as a release.

INSTALL / UPGRADE
1. On Windows, extract this ZIP to a folder (do not run inside the ZIP preview).
2. Close LotRadar completely if it is running (the installer refuses to run while
   port 8765 is active).
3. Double-click Installer.cmd. No administrator rights are needed.
4. Open LotRadar from the new desktop / Start menu shortcut. The first launch
   downloads Python 3.10+, the needed Python packages and Playwright Chromium if they
   are missing, so internet access is required once.
5. Chrome Reader (optional): Chrome > chrome://extensions > Developer mode >
   Load unpacked > choose:
     %LOCALAPPDATA%\Programs\MarketplaceScanner\chrome-extension
   Disable any older LotRadar/SalesmanHub scanner extension before pairing.

WHAT THE INSTALLER DOES
- Verifies every program file against the SHA-256 hashes in Install-Manifest.json
  BEFORE changing anything on your computer.
- Installs the program to %LOCALAPPDATA%\Programs\MarketplaceScanner.
- Moves any previous program folder to
  %LOCALAPPDATA%\MarketplaceScanner\ProgramBackups (never deleted automatically).
  If the install fails after the swap, the previous program is restored.
- NEVER reads, copies or overwrites your data at
  %LOCALAPPDATA%\MarketplaceScanner\data or the runtime folder next to it.

This package contains PROGRAM FILES only: no database, drafts, photo cache, API keys,
settings or browser login. To bring existing inventory to another computer, copy the
data folder yourself while LotRadar is closed, and never over an existing database
without a backup.

BRANDING IMAGES
Photo export needs business_card.png and dedication.jpg in the program's branding
folder. Production packages include them. A development package built without them
installs and starts, but photo export reports "branding_assets_missing" until the two
images are placed in %LOCALAPPDATA%\Programs\MarketplaceScanner\branding.
(Reinstalling an update replaces the program folder, so put the images in the
installer package instead of by hand.)

SECURITY
The local server listens on 127.0.0.1:8765 only. Publishing on Facebook is still manual.
Do not upload this package or your data folder to public websites.
