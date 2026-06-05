#!/bin/bash
# ahub-node install script — deploy on target compute machines
set -euo pipefail

echo ""
echo "  ┌─────────────────────────────────────┐"
echo "  │  ahub-node — AgentHub Remote Node   │"
echo "  └─────────────────────────────────────┘"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${AHUB_NODE_DIR:-/opt/ahub-node}"

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "  ✗ Python3 not found. Install it first."
  exit 1
fi
echo "  ✓ Python $(python3 --version | awk '{print $2}')"

# Check Docker
if command -v docker &>/dev/null; then
  echo "  ✓ Docker $(docker --version | grep -oP '\d+\.\d+\.\d+')"
else
  echo "  ⚠ Docker not found (container tools will not work)"
fi

# Install to target directory
if [[ "$SCRIPT_DIR" != "$INSTALL_DIR" ]]; then
  echo ""
  echo "  Installing to $INSTALL_DIR ..."
  mkdir -p "$INSTALL_DIR"
  cp "$SCRIPT_DIR"/{server.py,security.py,config.yaml,requirements.txt} "$INSTALL_DIR/"
fi

# Install Python dependencies
echo "  Installing dependencies..."
pip3 install -q -r "$INSTALL_DIR/requirements.txt"
echo "  ✓ Dependencies installed"

# Generate token if using default
if grep -q "ahub-change-me" "$INSTALL_DIR/config.yaml"; then
  NEW_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(20))")
  sed -i "s|ahub-change-me|$NEW_TOKEN|g" "$INSTALL_DIR/config.yaml"
  echo ""
  echo "  ┌─── Generated Token ───────────────────────┐"
  echo "  │  $NEW_TOKEN  │"
  echo "  └───────────────────────────────────────────┘"
  echo "  Save this token! You'll need it in AgentHub's MCP config."
fi

# Create systemd service (optional)
echo ""
read -rp "  Create systemd service? [Y/n]: " ans
if [[ "${ans:-y}" =~ ^[Yy] ]]; then
  cat > /etc/systemd/system/ahub-node.service << EOF
[Unit]
Description=AgentHub Remote Node (MCP Server)
After=network.target docker.service

[Service]
Type=simple
ExecStart=$(command -v python3) $INSTALL_DIR/server.py
WorkingDirectory=$INSTALL_DIR
Restart=always
RestartSec=5
Environment=AHUB_NODE_CONFIG=$INSTALL_DIR/config.yaml

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now ahub-node
  echo "  ✓ Service created and started"
  echo "  Status: systemctl status ahub-node"
else
  echo ""
  echo "  Manual start:"
  echo "    cd $INSTALL_DIR && python3 server.py"
fi

PORT=$(python3 -c "import yaml; print(yaml.safe_load(open('$INSTALL_DIR/config.yaml'))['server']['port'])")
echo ""
echo "  ┌─────────────────────────────────────────────┐"
echo "  │  Done! Server on port $PORT                   │"
echo "  │                                             │"
echo "  │  AgentHub config (settings.json):           │"
echo "  │  \"mcpServers\": {                            │"
echo "  │    \"node-NAME\": {                           │"
echo "  │      \"type\": \"sse\",                         │"
echo "  │      \"url\": \"http://THIS_IP:$PORT/sse\"      │"
echo "  │    }                                        │"
echo "  │  }                                          │"
echo "  └─────────────────────────────────────────────┘"
echo ""
