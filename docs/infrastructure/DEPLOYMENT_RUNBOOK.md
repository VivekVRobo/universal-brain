# Bare-Metal & Cloud Deployment Runbook

**Status:** Draft for operator review  
**Version:** Draft 0.1  
**Authority:** Derived from System Architecture, ADR-0007, and FREE_CLOUD_ORCHESTRATION.md

---

## 1. Overview & Provisioning Target

This runbook provides step-by-step, reproducible instructions to deploy the **Universal Brain Sovereign Kernel** onto a clean **Ubuntu 22.04 LTS** server (specifically optimized for the Oracle Cloud Always Free Ampere A1 ARM instance: 4 OCPU, 24GB RAM, 200GB disk).

```mermaid
flowchart LR
    CleanOS["1. Clean Ubuntu 22.04 LTS"] --> BasePkg["2. Install Docker, Tailscale, rclone"]
    BasePkg --> MeshVPN["3. Join Tailscale Mesh (Zero Inbound Ports)"]
    MeshVPN --> RepoClone["4. Clone Repo & Load GPG Secrets"]
    RepoClone --> DBInit["5. Boot PostgreSQL (pgvector) & Run Migrations"]
    DBInit --> Daemons["6. Enable Systemd Services (Kernel & Replicator)"]
    Daemons --> SmokeTest["7. Run Automated Smoke Test & Verification"]
```

---

## 2. Prerequisites & Credentials Checklist

Before booting the system, ensure the following credentials and accounts are prepared:
- [ ] **Oracle Cloud Account:** 1x Ampere A1 Compute Instance running Ubuntu 22.04 LTS.
- [ ] **Tailscale Auth Key:** Ephemeral or reusable key to join private mesh network.
- [ ] **GitHub SSH Deploy Key:** Read/write access to the private repository for encrypted backups.
- [ ] **Telegram Bot Credentials:** Bot Token (`TELEGRAM_BOT_TOKEN`) and Chat ID (`TELEGRAM_ADMIN_CHAT_ID`).
- [ ] **Google Drive Service Account or rclone config:** For mounting `/mnt/brain_knowledge` and syncing chunked journals.
- [ ] **Operator GPG Key:** Public key for database snapshot encryption; private key for restoration.

---

## 3. Step-by-Step Installation Guide

### Step 1: Base System Hardening & Package Installation

Log in to the server via SSH and install the required container and networking packages:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git ufw age gnupg2 jq htop build-essential rclone

# Install Docker and Docker Compose v2
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
sudo systemctl enable --now docker
```

### Step 2: Zero-Trust Network Lockdown (Tailscale & Firewall)

To satisfy `THR-011` and eliminate public internet exposure:

```bash
# Install Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --authkey=tskey-auth-XXXXXXXXXXXX --ssh

# Lock down UFW firewall: Deny all incoming traffic except Tailscale mesh
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow in on tailscale0
sudo ufw --force enable
```
*Verification:* The server now has zero public open ports. All operator access and Colab worker connections route over the authenticated Tailscale mesh.

---

### Step 3: Directory Layout & Secret Injection

Set up the production directory structure under `/opt/universal_brain`:

```bash
sudo mkdir -p /opt/universal_brain/{config,data/postgres,logs,secrets,artifacts/evidence}
sudo chown -R $USER:$USER /opt/universal_brain
cd /opt/universal_brain

# Clone the repository
git clone git@github.com:your-repo/universal-brain.git repo
cd repo
```

Create the environment file `/opt/universal_brain/config/.env` with locked permissions:

```bash
cat << 'EOF' > /opt/universal_brain/config/.env
APP_ENV=production
SYSTEM_ID=ub-oracle-core-01
DATABASE_URL=postgresql://brain_admin:CHANGE_ME_PASSWORD@localhost:5432/universal_brain
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_ADMIN_CHAT_ID=987654321
TELEGRAM_COLD_CHANNEL_ID=-1001234567890
GDRIVE_JOURNAL_DIR=/mnt/brain_knowledge/journal
OPERATOR_GPG_FINGERPRINT=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
EOF

chmod 600 /opt/universal_brain/config/.env
```

---

### Step 4: Launch Database & Run Schema Migrations

Universal Brain uses PostgreSQL 16 with `pgvector`:

```bash
# Start PostgreSQL container via Docker Compose
docker compose -f docker-compose.prod.yml up -d postgres

# Wait for PostgreSQL to become healthy
sleep 5

# Enable pgvector extension and run database migrations
docker compose -f docker-compose.prod.yml exec -T postgres psql -U brain_admin -d universal_brain -c "CREATE EXTENSION IF NOT EXISTS vector;"
docker compose -f docker-compose.prod.yml run --rm app alembic upgrade head
```

---

### Step 5: Mount Persistent Knowledge Base (rclone)

Mount the off-site Google Drive folder to `/mnt/brain_knowledge`:

```bash
sudo mkdir -p /mnt/brain_knowledge
sudo rclone mount gdrive:brain_knowledge /mnt/brain_knowledge \
    --daemon \
    --vfs-cache-mode writes \
    --dir-cache-time 72h \
    --allow-other
```

---

### Step 6: Install Systemd Production Daemons

Universal Brain runs as two permanent systemd daemons on the host:

#### 1. Executive Kernel Service (`/etc/systemd/system/universal-brain-kernel.service`)
```ini
[Unit]
Description=Universal Brain Executive Kernel & API Service
After=network.target docker.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/universal_brain/repo
EnvironmentFile=/opt/universal_brain/config/.env
ExecStart=/usr/bin/docker compose -f docker-compose.prod.yml up app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### 2. Memory Replicator Service (`/etc/systemd/system/universal-brain-replicator.service`)
```ini
[Unit]
Description=Universal Brain Memory Replicator Daemon (Sync & Snapshots)
After=network.target universal-brain-kernel.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/universal_brain/repo
EnvironmentFile=/opt/universal_brain/config/.env
ExecStart=/usr/bin/python3 -m universal_brain.memory.replicator
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
```

Enable and start both services:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now universal-brain-kernel
sudo systemctl enable --now universal-brain-replicator
```

---

## 4. Post-Deployment Smoke Test & Verification

To verify that all subsystems, databases, and alerting sinks are functioning:

```bash
python3 -m universal_brain.scripts.smoke_test
```

### Smoke Test Verification Matrix
1. **Database Health:** Verifies PostgreSQL read/write transactions and `pgvector` cosine similarity calculation.
2. **Outbox & Replicator:** Emits a test `CONSTITUTION_CHECK` event; verifies that a chunk file appears in `/mnt/brain_knowledge/journal/` within 60 seconds.
3. **Out-of-Band Telegram Alert:** Pushes a test deployment confirmation to the operator's mobile device.
4. **Tool Gateway Sandbox:** Tests a dry-run A1 file edit on a temporary git branch with preflight `patch -R --dry-run` verification.
5. **Hash Chain Checksum:** Asserts that `ALN-016` event hash chain verifies with zero broken links.

When all 5 checks return `[PASS]`, the node is declared **SOVEREIGN OPERATIONAL READY**.
