#!/bin/bash
# WSL2 + ROCm 训练环境安装（在 Ubuntu-24.04 内以 root 运行）
# 日志: /tmp/rocm_setup.log
set -x
export DEBIAN_FRONTEND=noninteractive

echo "===== [1/5] apt 基础依赖 ====="
apt update -y
apt install -y wget curl git python3 python3-venv python3-pip

echo "===== [2/5] 安装 amdgpu-install ====="
cd /tmp
LIST=$(curl -s https://repo.radeon.com/amdgpu-install/latest/ubuntu/noble/ | grep -oE 'amdgpu-install_[0-9.]+-[0-9]+_all\.deb' | sort -V | tail -1)
echo "包名: $LIST"
if [ -z "$LIST" ]; then
  LIST="amdgpu-install_6.4.60402-1_all.deb"
  echo "解析失败，使用默认: $LIST"
fi
wget -q "https://repo.radeon.com/amdgpu-install/latest/ubuntu/noble/$LIST" -O amdgpu-install.deb
apt install -y ./amdgpu-install.deb
apt update -y

echo "===== [3/5] 安装 ROCm (WSL, 无 DKMS) ====="
amdgpu-install -y --usecase=wsl,rocm --no-dkms

echo "===== [4/5] 创建 Python 环境 ====="
python3 -m venv /root/train-venv
/root/train-venv/bin/pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

echo "===== [5/5] 安装 ROCm 版 PyTorch ====="
OK=0
for V in rocm6.4 rocm6.3 rocm6.2 rocm6.1; do
  echo "尝试 PyTorch wheel: $V"
  if /root/train-venv/bin/pip install torch torchvision --index-url "https://download.pytorch.org/whl/$V"; then
    OK=1; echo "PyTorch 安装成功: $V"; break
  fi
done
[ $OK -eq 1 ] || echo "!!! 所有 PyTorch wheel 源都失败"

echo "===== 验证 ====="
rocminfo | grep -E "Marketing Name|Name:" | head -5
/root/train-venv/bin/python -c "import torch; print('torch', torch.__version__); print('GPU可用', torch.cuda.is_available()); print('设备', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '无')"
echo "===== 完成 ====="
