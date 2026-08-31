# 32-bit Windows PowerShell worker for Hancom Office 2022 COM automation.
# This script is intentionally a small allowlist: it never opens, saves, closes,
# exports, prints, or overwrites a user file.

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

$script:hwp = $null
$script:documentId = $null
$script:shadowText = ""
$script:shadowUndo = New-Object System.Collections.Generic.List[string]
$script:lastBeforeFingerprint = $null
$script:lastAfterFingerprint = $null
$script:lastReadError = $null

function Has-Property($Object, [string]$Name) {
    return $null -ne $Object -and $null -ne $Object.PSObject.Properties[$Name]
}

function New-Fingerprint([string]$Text) {
    $payload = [string]$script:documentId + [char]0 + [string]$Text
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
        $hash = $sha.ComputeHash($bytes)
        $hex = -join ($hash | ForEach-Object { $_.ToString("x2") })
        return $hex.Substring(0, 20)
    }
    finally {
        $sha.Dispose()
    }
}

function Get-HwpProcessRunning {
    return $null -ne (Get-Process -Name "Hwp" -ErrorAction SilentlyContinue | Select-Object -First 1)
}

function Require-Hwp {
    if ($null -eq $script:hwp -or [string]::IsNullOrWhiteSpace($script:documentId)) {
        throw "No automation-owned Hancom document is open. Start a new document first."
    }
}

function Read-NativeText {
    Require-Hwp
    $scanStarted = $false
    try {
        $script:lastReadError = $null
        # 0x0070 = document start, 0x0007 = document end.
        # 0x0007 alone means “current caret to document end”, which misses
        # text just inserted at the caret.
        $scanReady = [bool]$script:hwp.InitScan(0x07, 0x0077, 0, 0, 0, 0)
        if (-not $scanReady) {
            throw "Hancom refused to start a whole-document text scan."
        }
        $scanStarted = $true
        $builder = New-Object System.Text.StringBuilder
        $iterations = 0

        while ($iterations -lt 200000) {
            $piece = ""
            $state = [int]$script:hwp.GetText([ref]$piece)
            if ($state -ge 101) {
                throw "Hancom text scan failed with result code $state."
            }
            if ($piece.Length -gt 0) {
                [void]$builder.Append($piece)
            }
            if ($state -eq 0 -or $state -eq 1) {
                break
            }
            $iterations++
        }
        if ($iterations -ge 200000) {
            throw "Hancom text scan exceeded its safety limit."
        }
        [void]$script:hwp.ReleaseScan()
        $scanStarted = $false
        return @{
            text = $builder.ToString()
            context_verified = $true
        }
    }
    catch {
        $script:lastReadError = $_.Exception.Message
        if ($scanStarted) {
            try {
                [void]$script:hwp.ReleaseScan()
            }
            catch {
            }
        }
        return @{
            text = $script:shadowText
            context_verified = $false
        }
    }
}

function Get-Context {
    Require-Hwp
    $readBack = Read-NativeText
    $text = [string]$readBack.text
    if ($readBack.context_verified) {
        $script:shadowText = $text
    }
    return [ordered]@{
        document_id = $script:documentId
        text = $text
        fingerprint = New-Fingerprint $text
        context_verified = [bool]$readBack.context_verified
        unsaved = $true
    }
}

function Get-Status {
    $registered = $null -ne [Type]::GetTypeFromProgID("HWPFrame.HwpObject")
    return [ordered]@{
        backend = "powershell-com-x86"
        is_32bit_process = ([IntPtr]::Size -eq 4)
        hwp_registered = $registered
        hwp_process_running = Get-HwpProcessRunning
        is_ready = $registered -and ([IntPtr]::Size -eq 4)
        document_open = $null -ne $script:hwp
        unsaved = $null -ne $script:hwp
    }
}

function Start-NewDocument {
    if ($null -ne $script:hwp) {
        throw "HWP Live already owns a document. It will not close it or start another one."
    }
    if (Get-HwpProcessRunning) {
        throw "A Hancom window is already running. HWP Live refuses to attach to an existing user document; close it first, then start a fresh HWP Live document."
    }
    if ($null -eq [Type]::GetTypeFromProgID("HWPFrame.HwpObject")) {
        throw "Hancom Office 2022 automation is not registered on this PC."
    }

    $script:hwp = New-Object -ComObject "HWPFrame.HwpObject"
    try {
        $window = $script:hwp.XHwpWindows.Item(0)
        $window.Visible = $true
    }
    catch {
        throw "Hancom launched but its first document window could not be shown: $($_.Exception.Message)"
    }

    try {
        $null = $script:hwp.XHwpDocuments.Active_XHwpDocument
    }
    catch {
        [void]$script:hwp.HAction.Run("FileNew")
    }

    $script:documentId = "hwp-live-" + [Guid]::NewGuid().ToString("N")
    $script:shadowText = ""
    $script:shadowUndo.Clear()
    $script:lastBeforeFingerprint = $null
    $script:lastAfterFingerprint = $null
    return (Get-Context)
}

function Apply-TextStyle($Style) {
    if ($null -eq $Style) {
        return
    }

    $charSet = $script:hwp.HParameterSet.HCharShape
    [void]$script:hwp.HAction.GetDefault("CharShape", $charSet.HSet)
    if ((Has-Property $Style "font_size_pt") -and $null -ne $Style.font_size_pt) {
        $charSet.Height = [int][Math]::Round(([double]$Style.font_size_pt) * 100)
    }
    if (Has-Property $Style "bold") {
        $charSet.Bold = [bool]$Style.bold
    }
    [void]$script:hwp.HAction.Execute("CharShape", $charSet.HSet)

    if ((Has-Property $Style "align") -and $null -ne $Style.align) {
        $alignmentMap = @{
            left = "Left"
            center = "Center"
            right = "Right"
            justify = "Justify"
        }
        $alignName = $alignmentMap[[string]$Style.align]
        if ($null -eq $alignName) {
            throw "Unsupported paragraph alignment: $($Style.align)"
        }
        $paraSet = $script:hwp.HParameterSet.HParaShape
        [void]$script:hwp.HAction.GetDefault("ParagraphShape", $paraSet.HSet)
        $paraSet.AlignType = $script:hwp.HAlign($alignName)
        [void]$script:hwp.HAction.Execute("ParagraphShape", $paraSet.HSet)
    }
}

function Invoke-HwpInsertText([string]$Text) {
    $insertSet = $script:hwp.HParameterSet.HInsertText
    [void]$script:hwp.HAction.GetDefault("InsertText", $insertSet.HSet)
    $insertSet.Text = $Text
    if (-not [bool]$script:hwp.HAction.Execute("InsertText", $insertSet.HSet)) {
        throw "Hancom rejected the text insertion."
    }
}

function Insert-Text([string]$Text, [bool]$NewParagraphAfter, $Style) {
    Apply-TextStyle $Style
    Invoke-HwpInsertText $Text
    if ($NewParagraphAfter) {
        [void]$script:hwp.HAction.Run("BreakPara")
    }

    if ($script:shadowText.Length -gt 0) {
        $script:shadowText += [Environment]::NewLine
    }
    $script:shadowText += $Text
    if ($NewParagraphAfter) {
        $script:shadowText += [Environment]::NewLine
    }
}

function Get-TableCellText($Cells, [int]$Row, [int]$Column) {
    if ($null -eq $Cells -or $Row -ge $Cells.Count) {
        return ""
    }
    $currentRow = @($Cells[$Row])
    if ($Column -ge $currentRow.Count -or $null -eq $currentRow[$Column]) {
        return ""
    }
    return [string]$currentRow[$Column]
}

function Insert-Table($Edit) {
    $rows = [int]$Edit.rows
    $cols = [int]$Edit.cols
    $tableSet = $script:hwp.HParameterSet.HTableCreation
    [void]$script:hwp.HAction.GetDefault("TableCreate", $tableSet.HSet)
    $tableSet.Rows = $rows
    $tableSet.Cols = $cols
    $tableSet.WidthType = 2
    $tableSet.HeightType = 1

    $availableWidth = 45000
    try {
        $sectionSet = $script:hwp.HParameterSet.HSecDef
        [void]$script:hwp.HAction.GetDefault("PageSetup", $sectionSet.HSet)
        $availableWidth = [int](
            $sectionSet.PageDef.PaperWidth -
            $sectionSet.PageDef.LeftMargin -
            $sectionSet.PageDef.RightMargin
        )
    }
    catch {
    }
    $tableSet.WidthValue = $availableWidth
    [void]$tableSet.CreateItemArray("ColWidth", $cols)
    $columnWidth = [int][Math]::Floor($availableWidth / $cols)
    for ($column = 0; $column -lt $cols; $column++) {
        $null = ($tableSet.ColWidth.Item($column) = $columnWidth)
    }
    $tableSet.TableProperties.TreatAsChar = 1
    $tableSet.TableProperties.Width = $availableWidth
    if (-not [bool]$script:hwp.HAction.Execute("TableCreate", $tableSet.HSet)) {
        throw "Hancom rejected the table creation."
    }

    for ($row = 0; $row -lt $rows; $row++) {
        for ($column = 0; $column -lt $cols; $column++) {
            $value = Get-TableCellText $Edit.cells $row $column
            if ($value.Length -gt 0) {
                Invoke-HwpInsertText $value
            }
            if ($row -ne ($rows - 1) -or $column -ne ($cols - 1)) {
                if (-not [bool]$script:hwp.HAction.Run("TableRightCell")) {
                    throw "Hancom could not move to the next table cell."
                }
            }
        }
    }

    $renderedRows = New-Object System.Collections.Generic.List[string]
    for ($row = 0; $row -lt $rows; $row++) {
        $renderedCells = New-Object System.Collections.Generic.List[string]
        for ($column = 0; $column -lt $cols; $column++) {
            $renderedCells.Add((Get-TableCellText $Edit.cells $row $column))
        }
        $renderedRows.Add(($renderedCells.ToArray() -join " | "))
    }
    if ($script:shadowText.Length -gt 0) {
        $script:shadowText += [Environment]::NewLine
    }
    $script:shadowText += ($renderedRows.ToArray() -join [Environment]::NewLine)
    $script:shadowText += [Environment]::NewLine
}

function Apply-Edits($Edits) {
    Require-Hwp
    $beforeContext = Get-Context
    $beforeShadow = $script:shadowText
    $warnings = New-Object System.Collections.Generic.List[string]
    $actionCount = 0
    try {
        foreach ($edit in @($Edits)) {
            if ([string]$edit.kind -eq "insert_text") {
                Insert-Text ([string]$edit.text) ([bool]$edit.new_paragraph_after) $edit.style
                $actionCount++
                continue
            }
            if ([string]$edit.kind -eq "insert_table") {
                Insert-Table $edit
                $actionCount++
                if ($null -ne $edit.table_style -and (
                    [bool]$edit.table_style.header_bold -or
                    $null -ne $edit.table_style.header_fill
                )) {
                    $warnings.Add(
                        "Table cells were inserted, but header bold/fill is not applied by the first native MVP. Verify or style that row manually."
                    )
                }
                continue
            }
            throw "Unsupported edit kind: $($edit.kind)"
        }

        $afterContext = Get-Context
        $script:shadowUndo.Add($beforeShadow)
        $script:lastBeforeFingerprint = $beforeContext.fingerprint
        $script:lastAfterFingerprint = $afterContext.fingerprint
        return [ordered]@{
            context = $afterContext
            native_undo_count = [Math]::Max(1, $actionCount)
            warnings = @($warnings.ToArray())
        }
    }
    catch {
        $originalError = $_.Exception.Message
        $rolledBack = $false
        try {
            $attempt = 0
            while ($attempt -lt 256) {
                $current = Get-Context
                if ($current.fingerprint -eq $beforeContext.fingerprint) {
                    $rolledBack = $true
                    break
                }
                $document = $script:hwp.XHwpDocuments.Active_XHwpDocument
                [void]$document.Undo(1)
                $attempt++
            }
        }
        catch {
            $rolledBack = $false
        }
        $script:shadowText = $beforeShadow
        if (-not $rolledBack) {
            throw "$originalError Automatic rollback could not verify the original document state."
        }
        throw $originalError
    }
}

function Undo-LastEdit([int]$NativeUndoCount) {
    Require-Hwp
    if ([string]::IsNullOrWhiteSpace($script:lastBeforeFingerprint)) {
        throw "The worker has no safe HWP Live change to undo."
    }
    $current = Get-Context
    if ($current.fingerprint -ne $script:lastAfterFingerprint) {
        throw "The document changed after the HWP Live edit. Refusing to undo."
    }

    $attempt = 0
    while ($attempt -lt 256) {
        $didUndo = $false
        try {
            $document = $script:hwp.XHwpDocuments.Active_XHwpDocument
            [void]$document.Undo(1)
            $didUndo = $true
        }
        catch {
            try {
                $didUndo = [bool]$script:hwp.HAction.Run("Undo")
            }
            catch {
                $didUndo = $false
            }
        }
        if (-not $didUndo) {
            break
        }
        $attempt++
        $afterUndo = Get-Context
        if ($afterUndo.fingerprint -eq $script:lastBeforeFingerprint) {
            if ($script:shadowUndo.Count -gt 0) {
                $script:shadowText = $script:shadowUndo[$script:shadowUndo.Count - 1]
                $script:shadowUndo.RemoveAt($script:shadowUndo.Count - 1)
            }
            $script:lastBeforeFingerprint = $null
            $script:lastAfterFingerprint = $null
            return $afterUndo
        }
    }
    throw "Hancom could not restore the exact pre-edit text state, so HWP Live stopped instead of undoing further."
}

function Write-WorkerResponse([string]$Id, [bool]$Ok, $Result, [string]$ErrorMessage) {
    $payload = [ordered]@{
        id = $Id
        ok = $Ok
    }
    if ($Ok) {
        $payload.result = $Result
    }
    else {
        $payload.error = [ordered]@{ message = $ErrorMessage }
    }
    [Console]::Out.WriteLine(($payload | ConvertTo-Json -Compress -Depth 20))
}

while ($null -ne ($line = [Console]::In.ReadLine())) {
    if ([string]::IsNullOrWhiteSpace($line)) {
        continue
    }

    $request = $null
    $shouldStop = $false
    try {
        $request = $line | ConvertFrom-Json
        $operation = [string]$request.operation
        $result = switch ($operation) {
            "status" {
                Get-Status
                break
            }
            "start_new_document" {
                Start-NewDocument
                break
            }
            "read_context" {
                Get-Context
                break
            }
            "apply_edits" {
                Apply-Edits $request.params.edits
                break
            }
            "undo" {
                Undo-LastEdit ([int]$request.params.native_undo_count)
                break
            }
            "shutdown" {
                $shouldStop = $true
                [ordered]@{ stopped = $true }
                break
            }
            default {
                throw "Unsupported worker operation: $operation"
            }
        }
        Write-WorkerResponse ([string]$request.id) $true $result $null
    }
    catch {
        $requestId = if ($null -ne $request -and (Has-Property $request "id")) {
            [string]$request.id
        }
        else {
            ""
        }
        Write-WorkerResponse $requestId $false $null $_.Exception.Message
    }
    if ($shouldStop) {
        break
    }
}
