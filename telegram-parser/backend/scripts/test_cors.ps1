try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/v1/proxies" -Method OPTIONS -Headers @{
        Origin = "http://[::1]:5177"
        "Access-Control-Request-Method" = "GET"
        "Access-Control-Request-Headers" = "authorization,x-project-id"
    }
    Write-Host "Status: $($r.StatusCode)"
    Write-Host "Allow-Origin: $($r.Headers['Access-Control-Allow-Origin'])"
    Write-Host "Allow-Methods: $($r.Headers['Access-Control-Allow-Methods'])"
    Write-Host "Allow-Headers: $($r.Headers['Access-Control-Allow-Headers'])"
} catch {
    $err = $_.Exception.Response
    if ($err) {
        Write-Host "Status: $($err.StatusCode)"
        $h = $err.Headers
        foreach ($k in @('Access-Control-Allow-Origin','Access-Control-Allow-Methods','Access-Control-Allow-Headers')) {
            if ($h.ContainsKey($k)) { Write-Host "${k}: $($h[$k])" }
        }
    } else {
        Write-Host "Error: $($_.Exception.Message)"
    }
}
