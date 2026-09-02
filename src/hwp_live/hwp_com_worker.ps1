# Windows PowerShell worker for Hancom Office COM automation.
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

if ($null -eq ("HwpLive.NativeWindows" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace HwpLive {
    public static class NativeWindows {
        private delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);

        [DllImport("user32.dll")]
        private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);

        [DllImport("user32.dll")]
        private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);

        [DllImport("user32.dll")]
        private static extern bool IsWindowVisible(IntPtr hwnd);

        public static long[] VisibleTopLevelForProcesses(int[] processIds) {
            var wanted = new HashSet<uint>();
            foreach (var processId in processIds) wanted.Add((uint)processId);
            var handles = new List<long>();
            EnumWindows(delegate(IntPtr hwnd, IntPtr unused) {
                uint processId;
                GetWindowThreadProcessId(hwnd, out processId);
                if (wanted.Contains(processId) && IsWindowVisible(hwnd)) {
                    handles.Add(hwnd.ToInt64());
                }
                return true;
            }, IntPtr.Zero);
            return handles.ToArray();
        }
    }
}
"@
}

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

function Get-HwpWindowHandles {
    $processIds = @(Get-Process -Name "Hwp" -ErrorAction SilentlyContinue | ForEach-Object { [int]$_.Id })
    if ($processIds.Count -eq 0) {
        return @()
    }
    return @([HwpLive.NativeWindows]::VisibleTopLevelForProcesses([int[]]$processIds))
}

function Test-StrictIsolation {
    return [string]::Equals(
        [Environment]::GetEnvironmentVariable("HWP_LIVE_SAFE_STRICT_ISOLATION"),
        "1",
        [StringComparison]::Ordinal
    )
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
        backend = "powershell-com"
        worker_bitness = ([IntPtr]::Size * 8)
        is_32bit_process = ([IntPtr]::Size -eq 4)
        hwp_registered = $registered
        hwp_process_running = Get-HwpProcessRunning
        strict_isolation = Test-StrictIsolation
        ownership_policy = "new-blank-unsaved-unique-window"
        is_ready = $registered
        document_open = $null -ne $script:hwp
        unsaved = $null -ne $script:hwp
    }
}

function Start-NewDocument {
    if ($null -ne $script:hwp) {
        throw "HWP Live already owns a document. It will not close it or start another one."
    }
    if ((Test-StrictIsolation) -and (Get-HwpProcessRunning)) {
        throw "Strict isolation is enabled and a Hancom process is already running. Close it or unset HWP_LIVE_SAFE_STRICT_ISOLATION before starting HWP Live."
    }
    if ($null -eq [Type]::GetTypeFromProgID("HWPFrame.HwpObject")) {
        throw "Hancom Office 2022 automation is not registered on this PC."
    }

    $existingHandles = @(Get-HwpWindowHandles)
    $script:hwp = New-Object -ComObject "HWPFrame.HwpObject"
    try {
        try {
            $document = $script:hwp.XHwpDocuments.Active_XHwpDocument
        }
        catch {
            [void]$script:hwp.HAction.Run("FileNew")
            $document = $script:hwp.XHwpDocuments.Active_XHwpDocument
        }

        if ([int]$script:hwp.XHwpDocuments.Count -ne 1) {
            throw "The new COM instance did not expose exactly one document."
        }
        if (-not [string]::IsNullOrWhiteSpace([string]$document.FullName)) {
            throw "The new COM instance exposed a file-backed document instead of a blank document."
        }
        if ([bool]$document.Modified) {
            throw "The new COM instance exposed a modified document instead of a pristine blank document."
        }

        $window = $script:hwp.XHwpWindows.Item(0)
        $window.Visible = $true
        $ownedHandle = $null
        for ($attempt = 0; $attempt -lt 20 -and $null -eq $ownedHandle; $attempt++) {
            foreach ($handle in @(Get-HwpWindowHandles)) {
                if ($existingHandles -notcontains $handle) {
                    $ownedHandle = $handle
                    break
                }
            }
            if ($null -eq $ownedHandle) {
                Start-Sleep -Milliseconds 100
            }
        }
        if ($null -eq $ownedHandle) {
            throw "The new COM instance could not be matched to a unique new Hancom window."
        }
    }
    catch {
        # Never close a document when ownership validation fails: releasing our
        # reference is safer than risking a user-owned window.
        $message = $_.Exception.Message
        $script:hwp = $null
        throw "Hancom ownership validation failed: $message"
    }

    $script:documentId = "hwp-live-" + [Guid]::NewGuid().ToString("N")
    $script:shadowText = ""
    $script:shadowUndo.Clear()
    $script:lastBeforeFingerprint = $null
    $script:lastAfterFingerprint = $null
    return (Get-Context)
}

function Apply-TextStyle($Style, [ref]$ActionCount) {
    if ($null -eq $Style) {
        return
    }

    $changesCharShape = (
        ((Has-Property $Style "font_size_pt") -and $null -ne $Style.font_size_pt) -or
        (Has-Property $Style "bold")
    )
    if ($changesCharShape) {
        $charSet = $script:hwp.HParameterSet.HCharShape
        [void]$script:hwp.HAction.GetDefault("CharShape", $charSet.HSet)
        if ((Has-Property $Style "font_size_pt") -and $null -ne $Style.font_size_pt) {
            $charSet.Height = [int][Math]::Round(([double]$Style.font_size_pt) * 100)
        }
        if (Has-Property $Style "bold") {
            $charSet.Bold = [bool]$Style.bold
        }
        if (-not [bool]$script:hwp.HAction.Execute("CharShape", $charSet.HSet)) {
            throw "Hancom rejected the character formatting."
        }
        $ActionCount.Value++
    }

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
        if (-not [bool]$script:hwp.HAction.Execute("ParagraphShape", $paraSet.HSet)) {
            throw "Hancom rejected the paragraph formatting."
        }
        $ActionCount.Value++
    }
}

function Invoke-HwpInsertText([string]$Text, [ref]$ActionCount) {
    $insertSet = $script:hwp.HParameterSet.HInsertText
    [void]$script:hwp.HAction.GetDefault("InsertText", $insertSet.HSet)
    $insertSet.Text = $Text
    if (-not [bool]$script:hwp.HAction.Execute("InsertText", $insertSet.HSet)) {
        throw "Hancom rejected the text insertion."
    }
    $ActionCount.Value++
}

function Invoke-HwpMutationRun([string]$Action, [ref]$ActionCount) {
    if (-not [bool]$script:hwp.HAction.Run($Action)) {
        throw "Hancom rejected the $Action action."
    }
    $ActionCount.Value++
}

function Insert-Text([string]$Text, [bool]$NewParagraphAfter, $Style, [ref]$ActionCount) {
    $restoreCharShape = $false
    $restoreParaShape = $false
    $savedCharShape = $null
    $savedParaShape = $null
    $savedCharHeight = $null
    $savedCharBold = $null
    $savedParaAlign = $null

    if ($null -ne $Style) {
        $restoreCharShape = (
            ((Has-Property $Style "font_size_pt") -and $null -ne $Style.font_size_pt) -or
            (Has-Property $Style "bold")
        )
        $restoreParaShape = (
            (Has-Property $Style "align") -and $null -ne $Style.align
        )
        if ($restoreCharShape) {
            $savedCharShape = $script:hwp.CharShape
            $savedCharHeight = [int]$savedCharShape.Height
            $savedCharBold = [bool]$savedCharShape.Bold
        }
        if ($restoreParaShape) {
            $savedParaShape = $script:hwp.ParaShape
            $savedParaAlign = [int]$savedParaShape.AlignType
        }
    }

    try {
        Apply-TextStyle $Style $ActionCount
        Invoke-HwpInsertText $Text $ActionCount
        if ($NewParagraphAfter) {
            Invoke-HwpMutationRun "BreakPara" $ActionCount
        }
    }
    finally {
        # Restore only the shapes changed by this edit. These assignments are native
        # undo entries too, so the worker records them with the insertion.
        if ($restoreCharShape -and $null -ne $savedCharShape) {
            $script:hwp.CharShape = $savedCharShape
            $ActionCount.Value++
            $restoredCharShape = $script:hwp.CharShape
            if (
                [int]$restoredCharShape.Height -ne $savedCharHeight -or
                [bool]$restoredCharShape.Bold -ne $savedCharBold
            ) {
                throw "Hancom did not restore the previous character formatting."
            }
        }
        if ($restoreParaShape -and $null -ne $savedParaShape) {
            $script:hwp.ParaShape = $savedParaShape
            $ActionCount.Value++
            $restoredParaShape = $script:hwp.ParaShape
            if ([int]$restoredParaShape.AlignType -ne $savedParaAlign) {
                throw "Hancom did not restore the previous paragraph alignment."
            }
        }
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

function Test-InTableCell {
    try {
        $fieldState = [int]$script:hwp.CurFieldState
        return ($fieldState -eq 1 -or $fieldState -eq 17)
    }
    catch {
        throw "Hancom could not report whether the caret is inside a table cell."
    }
}

function Exit-Table {
    if (-not (Test-InTableCell)) {
        throw "The caret is not inside the newly created table."
    }
    if (-not [bool]$script:hwp.HAction.Run("MoveListEnd")) {
        throw "Hancom could not move to the end of the last table cell."
    }
    if (-not [bool]$script:hwp.HAction.Run("MoveRight")) {
        throw "Hancom could not move out of the newly created table."
    }
    if (-not (Test-InTableCell)) {
        return
    }
    if ([bool]$script:hwp.HAction.Run("MoveParentList") -and -not (Test-InTableCell)) {
        return
    }
    throw "The caret remained inside the newly created table; no later edit was attempted."
}

function Insert-Table($Edit, [ref]$ActionCount) {
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
    $ActionCount.Value++

    for ($row = 0; $row -lt $rows; $row++) {
        for ($column = 0; $column -lt $cols; $column++) {
            $value = Get-TableCellText $Edit.cells $row $column
            if ($value.Length -gt 0) {
                Invoke-HwpInsertText $value $ActionCount
            }
            if ($row -ne ($rows - 1) -or $column -ne ($cols - 1)) {
                if (-not [bool]$script:hwp.HAction.Run("TableRightCell")) {
                    throw "Hancom could not move to the next table cell."
                }
            }
        }
    }

    Exit-Table
    if ([bool]$Edit.new_paragraph_after) {
        Invoke-HwpMutationRun "BreakPara" $ActionCount
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

function Invoke-OneNativeUndo {
    try {
        $document = $script:hwp.XHwpDocuments.Active_XHwpDocument
        [void]$document.Undo(1)
        return $true
    }
    catch {
        try {
            return [bool]$script:hwp.HAction.Run("Undo")
        }
        catch {
            return $false
        }
    }
}

function Apply-Edits($Edits) {
    Require-Hwp
    $beforeContext = Get-Context
    if (-not [bool]$beforeContext.context_verified) {
        throw "Hancom document read-back is unverified. No edit or automatic Undo was attempted."
    }
    $beforeShadow = $script:shadowText
    $warnings = New-Object System.Collections.Generic.List[string]
    $actionCount = 0
    try {
        foreach ($edit in @($Edits)) {
            if ([string]$edit.kind -eq "insert_text") {
                Insert-Text ([string]$edit.text) ([bool]$edit.new_paragraph_after) $edit.style ([ref]$actionCount)
                continue
            }
            if ([string]$edit.kind -eq "insert_table") {
                Insert-Table $edit ([ref]$actionCount)
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
        if (-not [bool]$afterContext.context_verified) {
            throw "Hancom applied the edit but its document read-back is unverified."
        }
        $script:shadowUndo.Add($beforeShadow)
        $script:lastBeforeFingerprint = $beforeContext.fingerprint
        $script:lastAfterFingerprint = $afterContext.fingerprint
        return [ordered]@{
            context = $afterContext
            native_undo_count = $actionCount
            warnings = @($warnings.ToArray())
        }
    }
    catch {
        $originalError = $_.Exception.Message
        if ($actionCount -le 0) {
            throw $originalError
        }
        $rolledBack = $false
        $rollbackReason = "the recorded native Undo limit was reached"
        try {
            $attempt = 0
            while ($attempt -lt $actionCount) {
                $current = Get-Context
                if (-not [bool]$current.context_verified) {
                    $rollbackReason = "document read-back became unverified before the next Undo"
                    break
                }
                if (-not (Invoke-OneNativeUndo)) {
                    $rollbackReason = "Hancom refused a recorded Undo step"
                    break
                }
                $attempt++
            }
            $restored = Get-Context
            if ([bool]$restored.context_verified -and $restored.fingerprint -eq $beforeContext.fingerprint) {
                $rolledBack = $true
            }
            elseif (-not [bool]$restored.context_verified) {
                $rollbackReason = "document read-back was unverified after rollback"
            }
        }
        catch {
            $rolledBack = $false
            $rollbackReason = $_.Exception.Message
        }
        if ($rolledBack) {
            $script:shadowText = $beforeShadow
            throw $originalError
        }
        throw "$originalError Automatic rollback stopped after at most $actionCount recorded native Undo steps: $rollbackReason. Verify the visible document manually."
    }
}

function Undo-LastEdit([int]$NativeUndoCount) {
    Require-Hwp
    if ([string]::IsNullOrWhiteSpace($script:lastBeforeFingerprint)) {
        throw "The worker has no safe HWP Live change to undo."
    }
    if ($NativeUndoCount -lt 1 -or $NativeUndoCount -gt 512) {
        throw "The recorded native Undo count is outside the safe range. No Undo was attempted."
    }
    $current = Get-Context
    if (-not [bool]$current.context_verified) {
        throw "Hancom document read-back is unverified. No Undo was attempted."
    }
    if ($current.fingerprint -ne $script:lastAfterFingerprint) {
        throw "The document changed after the HWP Live edit. Refusing to undo."
    }

    $attempt = 0
    while ($attempt -lt $NativeUndoCount) {
        $beforeUndo = Get-Context
        if (-not [bool]$beforeUndo.context_verified) {
            throw "Hancom document read-back became unverified. HWP Live stopped before the next Undo step."
        }
        if (-not (Invoke-OneNativeUndo)) {
            throw "Hancom refused recorded Undo step $($attempt + 1) of $NativeUndoCount."
        }
        $attempt++
    }
    $afterUndo = Get-Context
    if (-not [bool]$afterUndo.context_verified) {
        throw "Hancom completed the recorded Undo steps, but document read-back is unverified. Verify the visible document manually."
    }
    if ($afterUndo.fingerprint -ne $script:lastBeforeFingerprint) {
        throw "Hancom did not restore the exact pre-edit text state after $NativeUndoCount recorded native Undo steps. HWP Live stopped at that limit."
    }
    if ($script:shadowUndo.Count -gt 0) {
        $script:shadowText = $script:shadowUndo[$script:shadowUndo.Count - 1]
        $script:shadowUndo.RemoveAt($script:shadowUndo.Count - 1)
    }
    $script:lastBeforeFingerprint = $null
    $script:lastAfterFingerprint = $null
    return $afterUndo
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
