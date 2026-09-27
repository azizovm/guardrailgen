param([switch]$Offline)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$linuxRoot = (& wsl.exe -d Ubuntu-22.04 -- wslpath -a $projectRoot).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve project folder in WSL.' }
$terminal = Get-Command wt.exe -ErrorAction Stop
$terminalArgs = @('-w', 'new')
$roles = @('world','service','controller','filter','prompt')
$titles = @('1 Gazebo','2 Groq service','3 LLM controller','4 Safety filter','5 Prompt')
for ($i = 0; $i -lt $roles.Count; $i++) {
    if ($i -gt 0) { $terminalArgs += ';' }
    $terminalArgs += @('new-tab','--title',$titles[$i],'wsl.exe','-d','Ubuntu-22.04','--','env')
    if ($Offline) { $terminalArgs += 'GUARDRAILGEN_OFFLINE=1' }
    $terminalArgs += @('bash',"$linuxRoot/scripts/stack_terminal.sh",$roles[$i])
}
# Visible interactive terminals were explicitly requested by the user.
$quotedArgs = ($terminalArgs | ForEach-Object {
    if ($_ -match '"') { throw 'Unexpected quote in terminal argument.' }
    '"' + $_ + '"'
}) -join ' '
Start-Process -FilePath $terminal.Source -ArgumentList $quotedArgs -WindowStyle Normal
