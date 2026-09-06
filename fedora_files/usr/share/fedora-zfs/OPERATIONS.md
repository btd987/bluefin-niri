# Optional ZFS Maintenance

Nothing is enrolled by image installation. This helper does not create or import
pools, mount datasets, edit fstab, upgrade pool features, migrate data, or set up
SSH credentials. ZFS must already be installed and usable with an imported pool.

Read-only inventory (usable without root; permissions may limit output):

```sh
python3 -I /usr/libexec/fedora-zfs status
```

Enroll one independent snapshot, scrub, or replication job:

```sh
sudo python3 -I /usr/libexec/fedora-zfs enroll data-snapshots
```

Choose a unique simple job name. The wizard performs read-only checks, displays
the proposal, and requires the exact confirmation `ENROLL` before writing policy
or activating a timer. Timers may execute immediately. Cancellation does not
write policy or alter storage. Choose each operation separately; none implicitly
enables another backup system or maintenance operation.

Snapshot enrollment requires explicit hourly/daily/weekly retention counts and
an execution schedule frequent enough for those tiers. Zero disables a tier;
monthly, yearly, and frequent tiers are disabled. Sanoid creates and prunes its
managed snapshots on the selected filesystem only, without recursion. Review
existing Sanoid policies outside this helper first: they are not discovered or
modified. Snapshots are crash-consistent, not guest-coordinated VM backups.

Scrubs operate only on the explicitly selected, already imported ONLINE pool.
An already running scrub/resilver may cause the scheduled command to fail;
the helper never stops it or restarts it forcibly.

Replication is deliberately limited to existing, manually seeded filesystem
destinations on a different pool. No initial seed, destination creation, child
dataset recursion, volume replication, resume, destination retention, rollback,
or force deletion is provided. The destination must be unmounted, read-only,
without children or an interrupted receive, and its latest snapshot must have
the same name and GUID on the source, with zero bytes written since that snapshot.
These checks run again before every transfer. Syncoid uses `--no-rollback`,
`--no-sync-snap`, `--no-stream`, and `--no-resume`; it sends the latest available
source snapshot, skips intermediates, and preserves destination readonly via
receive options. Source snapshots must be created separately. Keep a common
snapshot until successful replication; pruning it can require manual recovery.
Do not use other writers/receivers on the destination. Preflight is not atomic
with transfer; ZFS's non-forced receive remains the final divergence guard.

SSH accepts only simple `user@host` names, using the default SSH port. No IPv6
literals, SSH config aliases, custom options, key-path inputs, or automatic sudo
are supported. Provision root's authentication and verified host trust separately
on the installed machine. The remote account must already have the required
ZFS query/send-receive permissions and Syncoid runtime commands. Host-key checking
is strict, batch mode is required, SSH config is ignored, host-key updates are
disabled, and no keys, host trust, or privilege delegation are created here.

Same-pool replication is rejected, even through an SSH alias. Different pools on
the same machine may still share a failure domain. Maintain independent offline
or remote backups and test restores. Cross-job overlapping replication endpoints
are conservatively rejected even when hostnames differ.

Configuration lives in root-owned mode-0700 `/etc/fedora-zfs/jobs/NAME`, with
mode-0600 files. Reruns refuse overwrites, duplicate policies, and overlapping
replication enrollments. Partial failures are preserved for inspection, not
automatically deleted or retried. After correcting a service activation failure,
an administrator can explicitly enable the already generated timer.

Inspect or stop a job (substitute the enrolled name):

```sh
systemctl status fedora-zfs-data-snapshots.timer fedora-zfs@data-snapshots.service
journalctl -u fedora-zfs@data-snapshots.service
sudo systemctl disable --now fedora-zfs-data-snapshots.timer
```

Stopping a timer does not cancel a currently running operation or remove any
snapshots/configuration. Inspect running operations before manual configuration
changes. This is not a restore wizard or a general storage manager. Booted ZFS,
Secure Boot, real SSH replication, scrub, snapshot retention, and restore testing
remain required; mock and package-install proofs do not establish them.
