param(
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$Papers,
    [Parameter(Mandatory = $true)][string]$Workspace,
    [switch]$EnableRemote
)

$ErrorActionPreference = 'Stop'
if ($EnableRemote -and [string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
    $env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
}
$anMcpArguments = @('-m', 'aletheia_nexus.mcp_server', 'serve', '--allow-dir', $Papers, '--workspace', $Workspace)
if ($EnableRemote) { $anMcpArguments += '--enable-remote' }
& $Python @anMcpArguments
exit $LASTEXITCODE
