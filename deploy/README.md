# Deployment lifecycle

The old ChatContext deployment is retired. `install.py` and the app-local deployment
wrapper fail closed and perform no installation or deployment. Do not reinstall
these commands or recreate the old host credentials.

The maintained [common CI and deployment contract](../docs/ci-and-deployment.md)
is authoritative. Deployment remains explicitly disabled in this repository.
A separately authorized fresh deployment uses the `once-pocketcontext-v2` shared
dispatcher with an app-specific forced-command SSH key. The commandless connection
sends no registry credentials. The dispatcher resolves an immutable image, stops
the existing writer cleanly under its locks, preserves its volume, and verifies
the replacement. It does not automatically roll back.

See [runtime configuration and recovery](../docs/deployment.md) for required
primary-object storage, separate Litestream credentials and explicit fresh-volume
initialization. `docker/backup.py` is an offline legacy archive utility, excluded
from the current image; it is not part of the deployment or recovery entrypoint.

## Published container images

The image workflow publishes native AMD64 and ARM64 images by digest to GHCR,
then combines them into a multiarchitecture manifest with commit tags and `latest`.
Pulling an image is not deployment and does not enable the retired workflow job.
This workflow does not publish GitHub Release image archives.

Run `python3 tests/deploy_workflow.py` for isolated deployment-contract checks.
