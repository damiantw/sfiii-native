param(
    [string]$Work = $PSScriptRoot,
    [switch]$SeparateSaves,
    [string]$SharedSaveDir = '',
    [string]$LauncherSettings = ''
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
try {
    $root = [IO.Path]::GetFullPath($Work)
    $running = Get-CimInstance Win32_Process -Filter "Name='saturn.exe'" | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)
    }
    if ($running) { throw 'Close Native SFIII before importing saves.' }
    $action = [System.Windows.Forms.MessageBox]::Show("Export saves for a Saturn / Saroo editor?`n`nYes: Export ordinary saves as BIN files`nNo: Import BIN / YSBAK saves`nCancel: Close", 'Save manager - Import / Export', 'YesNoCancel')
    if ($action -eq [System.Windows.Forms.DialogResult]::Cancel) { exit 0 }
    $exporting = $action -eq [System.Windows.Forms.DialogResult]::Yes
    $picker = New-Object System.Windows.Forms.OpenFileDialog
    $picker.Title = 'Import Saturn saves - Scenarios 1, 2 and 3'
    $picker.Filter = 'SFIII save exports (*.bin;*.ysbak)|*.bin;*.ysbak'
    $picker.Multiselect = $true
    if (-not $exporting -and $picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
    $choice = [System.Windows.Forms.MessageBox]::Show("Use cartridge memory?`n`nYes: Cartridge (512 KiB)`nNo: Internal (32 KiB)`nCancel: Close", 'Save storage', 'YesNoCancel')
    if ($choice -eq [System.Windows.Forms.DialogResult]::Cancel) { exit 0 }
    $device = if ($choice -eq [System.Windows.Forms.DialogResult]::Yes) { 'cartridge' } else { 'internal' }
    $config = Join-Path $root 'save-import-python.txt'
    $python = if (Test-Path -LiteralPath $config) { ([IO.File]::ReadAllText($config)).Trim() } else { (Get-Command python -ErrorAction SilentlyContinue).Source }
    if (-not $python) { throw 'Python 3 is required. Put its executable path in save-import-python.txt beside the launcher.' }
    # Shared mode (the default): import into the backup memory shared by all scenarios, under its lock,
    # after merging the per-scenario files once (so an import never shadows an unmerged save).
    $backup = Join-Path $root 'experimental-backup.bin'
    $sharedLock = $null
    # Folders prepared by older builds lack the helper and keep using their own file, as the game does.
    if (-not $SeparateSaves -and (Test-Path -LiteralPath (Join-Path $root 'shared-saves.py'))) {
        $sharedDir = if ($SharedSaveDir) { [IO.Path]::GetFullPath($SharedSaveDir) } else { Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'SFIII Native\Shared Backup Memory' }
        if (($sharedDir + '\').StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'The shared backup memory folder must be outside the game-data folder.' }
        New-Item -ItemType Directory -Force $sharedDir | Out-Null
        try { $sharedLock = [IO.File]::Open((Join-Path $sharedDir 'backup.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
        catch { throw "Another Shining Force III game or save import is using the shared backup memory ($sharedDir). Close it first." }
        $prepare = @('-X', 'utf8', '-B', (Join-Path $root 'shared-saves.py'), 'prepare', '--work', $root, '--shared', $sharedDir)
        if ($LauncherSettings) { $prepare += @('--settings', $LauncherSettings) }
        $null = & $python @prepare
        if ($LASTEXITCODE -ne 0) { throw 'The per-scenario saves could not be merged into the shared backup memory; nothing was imported or exported.' }
        $backup = Join-Path $sharedDir 'backup.bin'
    }
    if ($exporting) {
        $folder = New-Object System.Windows.Forms.FolderBrowserDialog
        $folder.Description = 'Choose an export location. A new timestamped folder will be created.'
        if ($folder.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
        $destination = Join-Path $folder.SelectedPath ('SFIII-save-export-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
        # Exports read the same backup memory the game uses: the shared one unless separate saves are selected.
        $result = & $python -X utf8 -B (Join-Path $root 'import-saturn-save.py') --backup $backup --device $device --export $destination 2>&1
        if ($LASTEXITCODE -ne 0) { throw ($result -join "`n") }
        [System.Windows.Forms.MessageBox]::Show("Exported ordinary saves to:`n$destination`n`nImport the BIN files using your Saroo save editor. Native save states are not Saturn saves. Your game saves were not changed.", 'Export complete') | Out-Null
        Start-Process explorer.exe -ArgumentList ('"' + $destination + '"')
        exit 0
    }
    function Invoke-Importer([switch]$Replace) {
        $ErrorActionPreference = 'Continue' # Capture native stderr for the dialog, including duplicate-name errors.
        $arguments = @('-X', 'utf8', '-B', (Join-Path $root 'import-saturn-save.py'), '--backup', $backup, '--device', $device)
        if ($Replace) { $arguments += '--replace' }
        $arguments += $picker.FileNames
        $lines = & $python @arguments 2>&1
        return @{ Code = $LASTEXITCODE; Text = ($lines -join "`n") }
    }
    $result = Invoke-Importer
    if ($result.Code -ne 0 -and $result.Text -match 'already exists') {
        $overwrite = [System.Windows.Forms.MessageBox]::Show("A selected save name already exists on $device memory.`n`nReplace matching saves? A backup of the current memory will be retained. Other saves will be preserved.", 'Replace existing saves', 'YesNo')
        if ($overwrite -ne [System.Windows.Forms.DialogResult]::Yes) { exit 0 }
        $result = Invoke-Importer -Replace
    }
    if ($result.Code -ne 0) { throw $result.Text }
    [System.Windows.Forms.MessageBox]::Show("Imported into $device memory. Existing saves were preserved and backed up.`n`nLaunch Native SFIII normally and choose Continue. Replay checkpoints keep their original save data.", 'Import complete') | Out-Null
} catch {
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Import failed') | Out-Null
    exit 1
} finally {
    if ($sharedLock) { $sharedLock.Dispose() }
}
