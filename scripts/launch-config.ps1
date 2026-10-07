# 启停脚本只转换参数，默认值、文件语法和优先级由 Python 入口解析
function Get-LaunchConfiguration {
    param([hashtable]$Parameters, [string]$RepoPath)
    $arguments = @('--print-config')
    $pathOptions = @{DataDir='--data-dir'; FrontendDir='--frontend-dir'; PluginConfig='--plugin-config'; EnvFile='--env-file'}
    foreach ($name in $pathOptions.Keys) {
        if ($Parameters.ContainsKey($name) -and $Parameters[$name]) {
            $path = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Parameters[$name])
            $arguments += @($pathOptions[$name], $path)
        }
    }
    if ($Parameters.ContainsKey('Port')) { $arguments += @('--port', [string]$Parameters.Port) }
    if ($Parameters.ContainsKey('Profile')) { $arguments += @('--profile', [string]$Parameters.Profile) }
    if ($Parameters.NoBrowser -and $Parameters.Browser) { throw 'Choose either -Browser or -NoBrowser.' }
    if ($Parameters.EnvFile -and $Parameters.NoEnvFile) { throw 'Choose either -EnvFile or -NoEnvFile.' }
    if ($Parameters.NoBrowser) { $arguments += '--no-browser' }
    if ($Parameters.Browser) { $arguments += '--browser' }
    if ($Parameters.NoEnvFile) { $arguments += '--no-env-file' }
    $output = & uv run --project $RepoPath --no-sync python -m resume_maker.cli @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Launch configuration could not be resolved.' }
    return ($output | ConvertFrom-Json)
}

function Get-FrozenLaunchArguments {
    param($Configuration)
    $arguments = @('--no-env-file', '--port', [string]$Configuration.port, '--data-dir', $Configuration.data_dir)
    if ($Configuration.open_browser) { $arguments += '--browser' } else { $arguments += '--no-browser' }
    # 未覆盖前端时允许升级后的 wheel 使用自己的资源
    if ($Configuration.frontend_override) {
        $arguments += @('--frontend-dir', $Configuration.frontend_dir)
    }
    if ($Configuration.profile) { $arguments += @('--profile', $Configuration.profile) }
    if ($Configuration.plugin_config) { $arguments += @('--plugin-config', $Configuration.plugin_config) }
    return $arguments
}

function Invoke-FrozenLaunch {
    param($Configuration)
    $previous = @{}
    # 删除已解析的启动变量，让空的可选覆盖也保持固定，供应商输入继续保留
    $launchNames = @($Configuration.sources.PSObject.Properties.Name | ForEach-Object { 'RESUME_MAKER_' + $_.ToUpperInvariant() })
    $environment = [Environment]::GetEnvironmentVariables('Process')
    foreach ($name in $environment.Keys) {
        if ($launchNames -contains $name.ToUpperInvariant()) {
            $previous[$name] = $environment[$name]
            [Environment]::SetEnvironmentVariable($name, $null, 'Process')
        }
    }
    try {
        $arguments = @('run', '--no-sync', 'python', '-m', 'resume_maker.cli') + @(Get-FrozenLaunchArguments $Configuration)
        & uv @arguments | Out-Host
        return $LASTEXITCODE
    } finally {
        foreach ($name in $previous.Keys) {
            [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
        }
    }
}
