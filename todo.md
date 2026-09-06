# Active Tasks

## Current Status

Fedora is unsigned testing with Secure Boot disabled, using `testing` and dated
testing tags only. Hardware acceptance is separate from build validation and is
not a production signing/reviewer gate on test publication.

- [x] Hardware packages are implemented in Fedora source and a local expanded
  image built successfully; package integrity, exact-kernel ZFS pairing and
  runtime development-package exclusion checks passed. These additions are not published.
- [x] Consolidate essential usage, generic hardware caveats and safety boundaries
  into README; remove personal inventories and historical validation documents.
- [x] Verify concise documentation and local links; standard source suite:
  223 tests, 202 passed, 21 opt-in skips, no failures. No tests reference removed docs.
- [ ] Remove historical personal documentation and anonymize maintainer commit
  metadata; verify the rewritten source tree and update the public main branch.
- [ ] Publish the hardware-expanded image through trusted `main` testing CI.
- [ ] Retest the published artifact with Secure Boot disabled: Wi-Fi, audio,
  cameras, readers, modems, graphics, suspend/resume, login and Noctalia lock.
  Package presence does not establish hardware recovery.
- [ ] Exercise current-artifact storage enrollment, independent recovery access,
  backup/restore including metadata and SELinux labels, and update/rollback.
- [ ] Cover independent-host SSH/network failures, storage/filesystem variants,
  wrong credentials, missing mounts, insufficient space, interruptions, reruns
  and long-duration retention using disposable storage.
- [ ] Verify rootless Compose, DevPod workspaces, Zed/Helix workflows, interactive
  Podman Desktop, virtualization and supported Fedora VFIO kernel arguments.
- [ ] Review inherited extlinux and `/var` tmpfiles lint warnings for ownership
  and boot impact; do not delete files blindly or claim warning-free validation.
