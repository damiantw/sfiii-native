param([string]$Work = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
try {
    $root = [IO.Path]::GetFullPath($Work)
    $running = Get-CimInstance Win32_Process -Filter "Name='saturn.exe'" | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)
    }
    if ($running) { throw 'Close Native SFIII before importing saves.' }
    $picker = New-Object System.Windows.Forms.OpenFileDialog
    $picker.Title = 'Import real Saturn saves - SFORCE31_XX.BIN'
    $picker.Filter = 'Raw SFIII Scenario 1 saves (*.bin)|*.bin'
    $picker.Multiselect = $true
    if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
    $choice = [System.Windows.Forms.MessageBox]::Show("Import into cartridge memory?`n`nYes: Cartridge (512 KiB)`nNo: Internal (32 KiB)`nCancel: Leave saves unchanged", 'Save destination', 'YesNoCancel')
    if ($choice -eq [System.Windows.Forms.DialogResult]::Cancel) { exit 0 }
    $device = if ($choice -eq [System.Windows.Forms.DialogResult]::Yes) { 'cartridge' } else { 'internal' }
    $config = Join-Path $root 'save-import-python.txt'
    $python = if (Test-Path -LiteralPath $config) { ([IO.File]::ReadAllText($config)).Trim() } else { (Get-Command python -ErrorAction SilentlyContinue).Source }
    if (-not $python) { throw 'Python 3 is required. Put its executable path in save-import-python.txt beside the launcher.' }
    function Invoke-Importer([switch]$Replace) {
        $ErrorActionPreference = 'Continue' # Capture native stderr for the dialog, including duplicate-name errors.
        $arguments = @((Join-Path $root 'import-saturn-save.py'), '--backup', (Join-Path $root 'experimental-backup.bin'), '--device', $device)
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
}
