#!/bin/bash
# WSL2 (Ubuntu 24.04) + AMD RX 7900 XT 的 ROCm 训练环境一键配置
# 用法: bash setup_rocm.sh
set -e

echo "===== [1/5] 系统更新与基础依赖 ====="
sudo apt update
sudo apt install -y wget curl git python3 python3-venv python3-pip

echo "===== [2/5] 安装 ROCm (WSL 版, 无需内核驱动) ====="
# 解析 amdgpu-install 最新 deb 包名
DEB_URL=$(curl -s https://repo.radeon.com/amdgpu-install/latest/ubuntu/noble/ | grep -oP 'amdgpu-install_[0-9.]+-[0-9]+_all\.deb' | sort -V | tail -1)
echo "下载: $DEB_URL"
wget -q "https://repo.radeon.com/amdgpu-install/latest/ubuntu/noble/$DEB_URL" -O /tmp/amdgpu-install.deb
sudo apt install -y /tmp/amdgpu-install.deb
sudo apt update
sudo amdgpu-install -y --usecase=wsl,rocm --no-dkms

echo "===== [3/5] 创建 Python 虚拟环境 ~/train-venv ====="
python3 -m venv ~/train-venv
source ~/train-venv/bin/activate
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple || true

echo "===== [4/5] 安装 ROCm 版 PyTorch ====="
pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm6.2

echo "===== [5/5] 验证 GPU 识别 ====="
rocminfo | grep -E "Name|Marketing" | head -5 || true
python -c "import torch; print('torch:', torch.__version__); print('GPU 可用:', torch.cuda.is_available()); print('设备:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '无')"

echo ""
echo "===== 全部完成 ====="
echo "激活环境: source ~/train-venv/bin/activate"
