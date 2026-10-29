$log = "C:\Users\22692\AppData\Local\Temp\vfeat.log"
"== 启用前状态 ==" | Out-File -Encoding utf8 $log
Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform, Microsoft-Hyper-V-All, Microsoft-Windows-Subsystem-Linux |
    Select-Object FeatureName, State | Out-File -Append -Encoding utf8 $log

"== 启用 VirtualMachinePlatform ==" | Out-File -Append -Encoding utf8 $log
dism /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart 2>&1 | Out-File -Append -Encoding utf8 $log

"== 启用 Hyper-V ==" | Out-File -Append -Encoding utf8 $log
dism /online /enable-feature /featurename:Microsoft-Hyper-V-All /all /norestart 2>&1 | Out-File -Append -Encoding utf8 $log

"== 启用后状态 ==" | Out-File -Append -Encoding utf8 $log
Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform, Microsoft-Hyper-V-All, Microsoft-Windows-Subsystem-Linux |
    Select-Object FeatureName, State | Out-File -Append -Encoding utf8 $log

"== vmcompute 文件 ==" | Out-File -Append -Encoding utf8 $log
Test-Path "C:\Windows\System32\vmcompute.exe" | Out-File -Append -Encoding utf8 $log
