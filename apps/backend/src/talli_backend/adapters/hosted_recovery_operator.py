"""Explicit operator entry point. Never imported by runtime composition."""
import argparse
import json
from pathlib import Path
import re

from talli_backend.adapters.hosted_backup_recovery import HostedBackupRecovery
from talli_backend.adapters.hosted_recovery_capture import ManagedCapture, digest, json_bytes, private_read, require
from talli_backend.adapters.hosted_recovery_target import HostedDesignation, SupabaseRecoveryTarget
from talli_backend.adapters.managed_disposition_binding import ManagedDispositionBinding


def execute(*, command, config, expected_config_sha256, expected_plan_sha256=None):
    raw = private_read(config, 32768)
    require(digest(raw) == expected_config_sha256, 'hosted_operator_config_changed')
    values = json_bytes(raw)
    required = {'version', 'designation', 'credentials', 'ca', 'caSha256', 'work', 'pgRestore', 'capture'}
    require((set(values) == required and values['version'] == 1) or
        (set(values) == required | {'disposition'} and values['version'] == 2),
        'hosted_operator_config_invalid')
    designation = HostedDesignation(**values['designation'])
    target = SupabaseRecoveryTarget(designation=designation, credentials=values['credentials'],
        ca=values['ca'], ca_sha256=values['caSha256'])
    work = Path(values['work'])
    require(work.is_absolute(), 'hosted_work_directory_invalid')
    if command in ('inspect', 'contain'):
        disposition = None
        if command == 'inspect' and 'disposition' in values:
            try:
                disposition = ManagedDispositionBinding(customer_root=values['capture']['directory'],
                    **values['disposition'])
            except Exception:
                # Inspection still verifies the target marker/quarantine and
                # reports a closed replay prerequisite; containment never needs
                # capture, journal or held-byte availability.
                pass
        operator = HostedBackupRecovery.from_state(target=target, work=work,
            expected_plan_sha256=expected_plan_sha256, disposition=disposition)
        return operator.inspect() if command == 'inspect' else operator.contain(
            expected_plan_sha256=expected_plan_sha256)
    disposition = ManagedDispositionBinding(customer_root=values['capture']['directory'],
        **values['disposition']) if 'disposition' in values else None
    capture = ManagedCapture.open(**values['capture'], disposition=disposition)
    operator = HostedBackupRecovery(capture=capture, target=target, work=work,
        pg_restore=values['pgRestore'])
    if command == 'plan': return operator.plan()
    require(command == 'restore', 'hosted_operator_command_invalid')
    return operator.restore(expected_plan_sha256=expected_plan_sha256)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Restore one designated managed capture under quarantine; '
        'no project lifecycle, publication, scheduler or billing operations.')
    parser.add_argument('command', choices=('plan', 'restore', 'inspect', 'contain'))
    parser.add_argument('--config', required=True, help='absolute owner-private JSON configuration path')
    parser.add_argument('--expected-config-sha256', required=True,
        help='independently held digest of the reviewed configuration bytes')
    parser.add_argument('--expected-plan-sha256', help='reviewed plan digest; required for restore/inspect/contain')
    args = parser.parse_args(argv)
    if args.command in ('restore', 'inspect', 'contain') and not args.expected_plan_sha256:
        parser.error('--expected-plan-sha256 is required for this command')
    try:
        result = execute(command=args.command, config=args.config,
            expected_config_sha256=args.expected_config_sha256,
            expected_plan_sha256=args.expected_plan_sha256)
        if args.command != 'plan':
            # Private object names and original actor identifiers stay in private
            # custody; terminal output is a bounded non-secret status projection.
            result = {key: value for key, value in result.items() if key in
                ('phase', 'planSha256', 'publicationAuthorized', 'verification', 'databaseMarkerPresent',
                 'providerProjectPauseOrDeletionPerformed', 'ownerCaptureAndCredentialFilesRemoved',
                 'dispositionReplayCurrent')}
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) and re.fullmatch(
            'hosted_[a-z_]+', str(error)) else 'hosted_operator_failed_inspect_private_state'
        print(json.dumps({'status': 'stopped', 'code': code, 'publicationAuthorized': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
