# 3 hours
foreach ($file in Get-ChildItem -Recurse *.htm, *.html) {
    Write-Output "Converting $($file.FullName) to UTF-8";
    (Get-Content $file) -replace 'charset=windows-1252', 'charset=utf-8' | Set-Content -Force -Encoding utf8 ("$($file.FullName.Replace('Breviary', 'Breviary.utf8'))");
}
