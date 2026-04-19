#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Gold Paper Trading + Kronos — WSL2 full setup
# Run once to set up the entire environment from scratch
# ─────────────────────────────────────────────────────────────────────────────
set -e

echo "═══════════════════════════════════════════"
echo " Gold Paper Trading — WSL2 Setup"
echo "═══════════════════════════════════════════"

# 1. System deps
echo "[1/8] System packages..."
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
    python3.11 python3.11-venv python3-pip \
    git curl wget build-essential screen htop \
    libsqlite3-dev libgl1-mesa-glx libglib2.0-0

# 2. Create venv
echo "[2/8] Python venv..."
python3.11 -m venv ~/GD_V1/venv
source ~/GD_V1/venv/bin/activate

# 3. PyTorch CUDA 12.1
echo "[3/8] PyTorch + CUDA..."
pip install --upgrade pip
pip install torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu121

# 4. Project deps
echo "[4/8] Project Python deps..."
cd ~/GD_V1/gold-paper-trading
pip install -r requirements.txt

# 5. Install new deps (from updated requirements)
echo "[5/8] Kronos + ML deps..."
pip install \
    "torch>=2.1.0" \
    "transformers>=4.40.0" \
    "huggingface_hub>=0.23.0" \
    "accelerate>=0.30.0" \
    "backtrader>=1.9.78" \
    "python-dotenv>=1.0.0" \
    "rich>=13.7.0" \
    "schedule>=1.2.0" \
    "plotext>=5.2.8" \
    "pytest>=8.0.0"

# 6. HF cache + MPL backend
echo "[6/8] Environment variables..."
HF_HOME=~/GD_V1/gold-paper-trading/models
TRANSFORMERS_CACHE=~/GD_V1/gold-paper-trading/models
MPLBACKEND=Agg

cat >> ~/.bashrc << 'EOF'
export HF_HOME=~/GD_V1/gold-paper-trading/models
export TRANSFORMERS_CACHE=~/GD_V1/gold-paper-trading/models
export MPLBACKEND=Agg
EOF

export HF_HOME=$HF_HOME
export TRANSFORMERS_CACHE=$TRANSFORMERS_CACHE
export MPLBACKEND=$MPLBACKEND

# 7. Create dirs
echo "[7/8] Creating directories..."
mkdir -p ~/GD_V1/gold-paper-trading/logs/plots
mkdir -p ~/GD_V1/gold-paper-trading/data/historical
mkdir -p ~/GD_V1/gold-paper-trading/data/live
mkdir -p ~/GD_V1/gold-paper-trading/models

# 8. Verify CUDA
echo "[8/8] Verifying CUDA..."
python3 -c "
import torch
print('  Python:', __import__('sys').version.split()[0])
print('  CUDA available:', torch.cuda.is_available())
if torch.cuda.is_available():
    print('  GPU:', torch.cuda.get_device_name(0))
    print('  VRAM:', round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1), 'GB')
    x = torch.zeros(1).cuda().half()
    print('  float16 works:', True)
else:
    print('  WARNING: CUDA not available — will use CPU')
"

echo ""
echo "═══════════════════════════════════════════"
echo "✅ Setup complete!"
echo "═══════════════════════════════════════════"
echo ""
echo "Next steps:"
echo "  1. source ~/GD_V1/venv/bin/activate"
echo "  2. python test_setup.py         # verify everything"
echo "  3. bash start.sh                # launch all services"
echo ""
