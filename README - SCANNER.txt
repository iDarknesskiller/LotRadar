LOTRADAR R62 | Independent Edition
Source: SalesmanHub(20261110-230949).zip

Data: %LOCALAPPDATA%\MarketplaceScanner\data
Runtime: %LOCALAPPDATA%\MarketplaceScanner\runtime
Program: %LOCALAPPDATA%\Programs\MarketplaceScanner
Access: http://127.0.0.1:8765 (loopback only)

Launch Marketplace Scanner.cmd starts the app and repairs Python dependencies.
On first launch, it copies original SalesmanHub Marketplace data using SQLite
backup API if the old server is stopped. Never deletes or overwrites old data.

For Chrome, disable the OLD SalesmanHub extension and Load unpacked the
NEW chrome-extension directory from the installed MarketplaceScanner folder.
Pair with the key shown in the scanner console. Leave the port at 8765.

Export Inventory for SalesmanHub.cmd creates pending export only. There is NO
Hub import or remote sync server in this release. Do not put customer data on
unapproved servers. Posting to Facebook is still manual.
