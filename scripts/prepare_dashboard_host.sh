#!/bin/bash
# Prepare a public placeholder on an existing Caddy host. Do not upload dashboard data.
# Run as root after copying the reviewed template to the server:
#   bash prepare_dashboard_host.sh /root/events-coverage-setup/askmedia.Caddyfile
# This script does not install packages, change SSH/firewalls/DNS, or restart M4.
set +x
set -euo pipefail
umask 077

template_path="${1:-/root/events-coverage-setup/askmedia.Caddyfile}"
main_path=/etc/caddy/Caddyfile
site_path=/etc/caddy/sites/askmedia.news.caddy
import_line="import $site_path"
backup_dir=''
site_existed=0
files_changed=0
reload_attempted=0
completed=0
main_temp="/etc/caddy/.Caddyfile.events-coverage.$$"
site_temp="/etc/caddy/sites/.askmedia.news.events-coverage.$$"

fail() {
    printf '%s\n' "$*" >&2
    exit 1
}

m4_status() {
    curl --silent --show-error --noproxy '*' --connect-timeout 3 --max-time 10 \
        --output /dev/null --write-out '%{http_code}' http://127.0.0.1:8080/
}

restore_configs() {
    # Restore the original bytes and file attributes through same-directory renames.
    cp --preserve=all -- "$backup_dir/Caddyfile.before" "$main_temp" &&
        mv --force --no-target-directory -- "$main_temp" "$main_path" || return 1
    if (( site_existed )); then
        cp --preserve=all -- "$backup_dir/askmedia.news.before" "$site_temp" &&
            mv --force --no-target-directory -- "$site_temp" "$site_path" || return 1
    else
        rm --force -- "$site_path" || return 1
    fi
}

finish() {
    local result=$?
    trap - EXIT INT TERM
    if (( ! completed && files_changed )); then
        printf 'Preparation failed; restoring the previous Caddy files.\n' >&2
        if restore_configs; then
            if (( reload_attempted )); then
                if caddy validate --config "$main_path" --adapter caddyfile \
                    > "$backup_dir/rollback-validation.log" 2>&1 &&
                    systemctl reload caddy.service > "$backup_dir/rollback-reload.log" 2>&1; then
                    printf 'Previous Caddy configuration restored and reloaded.\n' >&2
                else
                    printf 'Rollback needs attention. Inspect %s over SSH.\n' "$backup_dir" >&2
                fi
            else
                printf 'Previous files restored; the running Caddy configuration was not reloaded.\n' >&2
            fi
        else
            printf 'File restoration needs attention. Original files: %s\n' "$backup_dir" >&2
        fi
        (( result != 0 )) || result=1
    fi
    rm --force -- "$main_temp" "$site_temp"
    exit "$result"
}

[[ $EUID -eq 0 ]] || fail 'Run this preparation script as root on the chosen existing server.'
[[ -r "$template_path" && -s "$template_path" ]] || fail 'The site template is missing or unreadable.'
[[ -f "$main_path" && ! -L "$main_path" ]] || fail 'Expected a regular existing /etc/caddy/Caddyfile.'
[[ ! -e "$site_path" || ( -f "$site_path" && ! -L "$site_path" ) ]] || fail 'Unexpected site configuration path.'
for command_name in caddy curl gzip runuser flock; do
    command -v "$command_name" > /dev/null || fail "Required existing command is missing: $command_name"
done
getent group caddy > /dev/null || fail 'The existing Caddy service group is missing.'
exec 9>/run/lock/events-coverage-setup.lock
flock --nonblock 9 || fail 'Another Events Coverage preparation is already running.'
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

systemctl is-active --quiet caddy.service || fail 'The existing Caddy service is not active.'
systemctl is-active --quiet cloudflared.service || fail 'The existing M4 tunnel service is not active.'
m4_status_before="$(m4_status)"
[[ "$m4_status_before" == 302 ]] || fail "M4 baseline is not the expected HTTP 302: $m4_status_before"

install -d -o root -g root -m 0700 /root/events-coverage-backups
backup_dir="$(mktemp -d /root/events-coverage-backups/setup-$(date -u +%Y%m%dT%H%M%SZ).XXXXXX)"
cp --preserve=all -- "$main_path" "$backup_dir/Caddyfile.before"
if [[ -e "$site_path" ]]; then
    site_existed=1
    cp --preserve=all -- "$site_path" "$backup_dir/askmedia.news.before"
fi

# Keep existing directories unchanged; only create missing project-owned paths.
for directory in /etc/caddy/sites /var/www/coverage /var/www/coverage/releases; do
    if [[ ! -e "$directory" ]]; then
        install -d -o root -g caddy -m 0755 "$directory"
    fi
    [[ -d "$directory" && ! -L "$directory" ]] || fail "Unexpected directory: $directory"
    runuser -u caddy -- test -x "$directory"
done
if [[ ! -e /var/www/coverage/current && ! -L /var/www/coverage/current ]]; then
    [[ ! -e /var/www/coverage/releases/bootstrap ]] || fail 'A bootstrap folder already exists without current; inspect it first.'
    install -d -o root -g caddy -m 0755 /var/www/coverage/releases/bootstrap
    printf '%s\n' '<!doctype html><meta charset="utf-8"><title>Events Coverage</title><p>Awaiting the first dashboard release.</p>' \
        > "$backup_dir/index.html"
    gzip -n -9 -c "$backup_dir/index.html" > "$backup_dir/index.html.gz"
    install -o root -g caddy -m 0644 "$backup_dir/index.html" /var/www/coverage/releases/bootstrap/index.html
    install -o root -g caddy -m 0644 "$backup_dir/index.html.gz" /var/www/coverage/releases/bootstrap/index.html.gz
    install -o root -g caddy -m 0644 /dev/null /var/www/coverage/releases/bootstrap/.bootstrap-pending
    ln -s releases/bootstrap /var/www/coverage/current
fi
runuser -u caddy -- test -r /var/www/coverage/current/index.html

cp -- "$template_path" "$backup_dir/askmedia.news.candidate"
caddy fmt --overwrite "$backup_dir/askmedia.news.candidate"

# The actual main file keeps every original byte; append only the new import if absent.
cp --preserve=all -- "$backup_dir/Caddyfile.before" "$backup_dir/Caddyfile.candidate"
if ! grep --fixed-strings --line-regexp --quiet -- "$import_line" "$backup_dir/Caddyfile.candidate"; then
    printf '\n%s\n' "$import_line" >> "$backup_dir/Caddyfile.candidate"
fi
# Validate the whole configuration against the staged site before changing live files.
awk -v live="$site_path" -v staged="$backup_dir/askmedia.news.candidate" \
    '$1 == "import" && $2 == live && NF == 2 { print "import " staged; next } { print }' \
    "$backup_dir/Caddyfile.candidate" > "$backup_dir/Caddyfile.validation"
if ! caddy validate --config "$backup_dir/Caddyfile.validation" --adapter caddyfile \
    > "$backup_dir/validation.log" 2>&1; then
    fail "Combined Caddy configuration did not validate. Inspect $backup_dir/validation.log over SSH."
fi

files_changed=1
install -o root -g caddy -m 0640 "$backup_dir/askmedia.news.candidate" "$site_temp"
mv --force --no-target-directory -- "$site_temp" "$site_path"
if ! cmp --silent -- "$main_path" "$backup_dir/Caddyfile.candidate"; then
    cp --preserve=all -- "$backup_dir/Caddyfile.candidate" "$main_temp"
    mv --force --no-target-directory -- "$main_temp" "$main_path"
fi
runuser -u caddy -- test -r "$site_path"
runuser -u caddy -- test -r "$main_path"
# Recheck the real import paths before the service sees the new configuration.
caddy validate --config "$main_path" --adapter caddyfile > "$backup_dir/live-validation.log" 2>&1
reload_attempted=1
systemctl reload caddy.service > "$backup_dir/reload.log" 2>&1
systemctl is-active --quiet caddy.service
systemctl is-active --quiet cloudflared.service
m4_status_after="$(m4_status)"
[[ "$m4_status_after" == "$m4_status_before" ]] || fail "M4 status changed after reload: $m4_status_before → $m4_status_after"

completed=1
printf 'Public askmedia.news site configuration prepared; dashboard data was not uploaded.\n'
printf 'M4 still returns HTTP %s; Caddy and cloudflared are active.\n' "$m4_status_after"
printf 'Original configuration and validation logs: %s\n' "$backup_dir"
printf 'The site does not require a login or password.\n'
printf 'DNS, provider firewall and public HTTPS still need separate verification.\n'
