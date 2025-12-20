## Provision the Raspberry Pi

### Option A: local inventory (recommended)
Copy the example:
- `infra/ansible/inventories/example.yml` → `infra/ansible/inventories/local.yml`

Edit `local.yml` with your Pi host/user, then run:
```bash
cd infra/ansible
ansible-playbook -i inventories/local.yml playbooks/site.yml