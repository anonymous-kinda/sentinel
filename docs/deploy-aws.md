# Deploying the cloud hub on AWS

One Graviton instance (t4g.small, about $17.50/month including the public IPv4 address) in its own VPC. Terraform builds the infrastructure; Ansible installs the same bundle an edge node or a disconnected enclave receives, and puts Caddy (automatic TLS) in front.

```
internet --443--> Caddy (Let's Encrypt) --127.0.0.1:8000--> sentinel (systemd, hardened)
admin    --22 from admin_cidr only--> sshd        break-glass: SSM Session Manager
edges    --7422 mTLS, allow-listed--> nats-server leafnode   (closed until M2)
```

## Prerequisites

- An AWS account, with credentials in the environment (`aws configure` or `AWS_PROFILE`).
- Terraform 1.6+ (or run `make tools`; a pinned binary is not bundled for the operator side).
- `uvx` (ships with uv) for Ansible: `uvx --from ansible-core ansible-playbook ...`.

## 1. Infrastructure

```bash
cd deploy/aws/terraform
cp terraform.tfvars.example terraform.tfvars      # set admin_cidr, ssh_public_key, budget_email
terraform init
terraform plan -out plan.tfplan                   # review: 1 VPC, 1 instance, 1 EIP, 1 budget, IAM
terraform apply plan.tfplan
terraform output -raw ansible_inventory > ../../ansible/inventory.ini
```

`admin_cidr` must be a specific network; the variable rejects `0.0.0.0/0`. The instance role grants Session Manager only. IMDSv2 is required and the root volume is encrypted.

## 2. Node

```bash
make bundle ARCH=aarch64          # dist/sentinel-<ver>-aarch64.tar.gz and .sha256
cd deploy/ansible
uvx --from ansible-core ansible-playbook site.yml
```

The playbook checks the tarball digest, unpacks it, and runs `install.sh`, which checks every file against `SHA256SUMS` and installs dependencies offline with hashes required. It then writes the node settings: read-only, exercise data plus the NASA reference set. Last, it configures Caddy for `https://<ip-with-dashes>.sslip.io`, a TLS-capable name that needs no DNS setup.

## 3. Check

```bash
curl -sf https://$(terraform -chdir=../aws/terraform output -raw hostname)/api/health
```

## Cost and teardown

The budget alarm emails at 80% (forecast) and 100% (actual) of `monthly_budget_usd` (default $20). To remove everything:

```bash
terraform -chdir=deploy/aws/terraform destroy
```

## What the public node does not do

- **Accept uploads.** `SENTINEL_READ_ONLY=1` disables the ingest endpoint.
- **Run the AI assistant.** That would add abuse and cost risk; it is shown locally and in the demo video.
- **Serve Space-Track data.** Its terms restrict redistribution. The public node serves exercise data and NASA's published reference set only.
