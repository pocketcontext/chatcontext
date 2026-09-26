# Safe updates

`deploy-chatcontext.py` accepts no command arguments and updates only `chat.pocketcontext.com` from `ghcr.io/pocketcontext/chatcontext:latest`. It serializes on its dedicated lock, requires exactly one matching existing container, gracefully stops it, rejects unclean/OOM exits, and invokes ONCE with automatic updates disabled. It refuses ambiguous recovery.

Optional bounded JSON stdin supplies only short-lived registry `username` and `token`; it cannot select a target. Login uses password-stdin and a private temporary Docker configuration removed on success or failure. Logs never print registry credentials or full container metadata.

`install.py` is a root-only future deployment step. It replaces only the exact existing ChatContext forced command in `/home/deploy/.ssh/authorized_keys`, preserves other keys, and installs a root-owned wrapper with narrowly scoped sudo. Provision a dedicated restricted key before installation. Do not run this during local application development.

The workflow remains disabled for deployment until `COLORS_PROFILE` is explicitly configured after authorized initial provisioning. See [deployment preparation](../docs/deployment.md). Test the orchestration locally with `python3 tests/deploy_workflow.py`; it uses mocks and never contacts infrastructure.
