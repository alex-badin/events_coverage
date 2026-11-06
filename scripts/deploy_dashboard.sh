#!/bin/zsh
# Publish the existing HTML snapshot. This script does not rebuild data or call paid services.
# Run: DEPLOY_HOST=m4-pilot zsh scripts/deploy_dashboard.sh
set -euo pipefail

project_root="${0:A:h:h}"
project_python="$project_root/.venv/bin/python"
input_html="$project_root/outputs/dashboard_exports/coverage_dashboard.html"
site_template="$project_root/configs/deploy/askmedia.Caddyfile"
[[ -r "$input_html" && -s "$input_html" ]] || { print -u2 'The dashboard HTML is missing or unreadable.'; exit 1; }
[[ -r "$site_template" && -s "$site_template" ]] || { print -u2 'The public Caddy template is missing or unreadable.'; exit 1; }
[[ -x "$project_python" ]] || { print -u2 'The project Python environment is missing.'; exit 1; }
if grep -Eq '^[[:space:]]*(basic_auth|basicauth)([[:space:]]|\{)|__SITE_PASSWORD_HASH__' "$site_template"; then
    print -u2 'The site template still contains authentication; expected the reviewed public configuration.'
    exit 1
fi
if (( ${+DEPLOY_HOST} )); then
    deploy_host="$DEPLOY_HOST"
else
    deploy_host="$("$project_python" - "$project_root/.env" <<'READ_HOST'
import logging
import sys
from dotenv import dotenv_values
logging.getLogger('dotenv').disabled = True
value = dotenv_values(sys.argv[1], interpolate=False).get('DEPLOY_HOST')
if not value:
    raise SystemExit('Set DEPLOY_HOST in the environment or the local .env file.')
print(value)
READ_HOST
    )"
fi
host_pattern='^[A-Za-z0-9_][A-Za-z0-9_.-]*(@[A-Za-z0-9][A-Za-z0-9_.-]*)?$'
[[ "$deploy_host" =~ "$host_pattern" ]] || { print -u2 'DEPLOY_HOST must be an SSH alias or user@host, without options or spaces.'; exit 1; }
release_id="$(date -u +%Y%m%dT%H%M%SZ)-$("$project_python" -c 'import secrets; print(secrets.token_hex(4))')"
deploy_tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/events-coverage-deploy.XXXXXX")"
trap 'rm -rf -- "$deploy_tmp_dir"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cp -- "$input_html" "$deploy_tmp_dir/index.html"
chmod 0644 "$deploy_tmp_dir/index.html"
cp -- "$site_template" "$deploy_tmp_dir/askmedia.Caddyfile"
chmod 0600 "$deploy_tmp_dir/askmedia.Caddyfile"
gzip -n -9 -k "$deploy_tmp_dir/index.html"
chmod 0644 "$deploy_tmp_dir/index.html.gz"
gzip -t "$deploy_tmp_dir/index.html.gz"
gzip -cd "$deploy_tmp_dir/index.html.gz" | cmp - "$deploy_tmp_dir/index.html"
sha_output="$("$project_python" - "$deploy_tmp_dir/index.html" "$deploy_tmp_dir/index.html.gz" <<'HASH_FILES'
import hashlib
import sys
def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()
print(' '.join(digest(p) for p in sys.argv[1:]))
HASH_FILES
)"
html_sha="${sha_output%% *}"
gzip_sha="${sha_output#* }"
remote_release="/var/www/coverage/releases/$release_id"
remote_stage="/root/events-coverage-setup/releases/$release_id"
ssh_options=(-o BatchMode=yes -o ConnectTimeout=15)
ssh "${ssh_options[@]}" -- "$deploy_host" bash -s -- "$release_id" <<'PREPARE_REMOTE'
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Deployment currently requires the existing root SSH account.' >&2; exit 1; }
[[ "$1" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$ ]] || exit 1
[[ -d /var/www/coverage/releases ]] || { echo 'Prepare the dashboard host first.' >&2; exit 1; }
mkdir -- "/var/www/coverage/releases/$1"
chmod 0755 "/var/www/coverage/releases/$1"
install -d -o root -g root -m 0700 /root/events-coverage-setup/releases
mkdir -- "/root/events-coverage-setup/releases/$1"
chmod 0700 "/root/events-coverage-setup/releases/$1"
PREPARE_REMOTE
rsync -az --no-owner --no-group \
    --rsh='ssh -o BatchMode=yes -o ConnectTimeout=15' -- \
    "$deploy_tmp_dir/index.html" "$deploy_tmp_dir/index.html.gz" "$deploy_host:$remote_release/"
rsync -a --no-owner --no-group \
    --rsh='ssh -o BatchMode=yes -o ConnectTimeout=15' -- \
    "$deploy_tmp_dir/askmedia.Caddyfile" "$deploy_host:$remote_stage/askmedia.Caddyfile"

ssh "${ssh_options[@]}" -- "$deploy_host" bash -s -- "$release_id" "$html_sha" "$gzip_sha" <<'ACTIVATE_REMOTE'
set +x
set -euo pipefail
umask 077
release_id="$1"; html_sha="$2"; gzip_sha="$3"
[[ $EUID -eq 0 && "$release_id" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$ ]] || exit 1
[[ "$html_sha" =~ ^[0-9a-f]{64}$ && "$gzip_sha" =~ ^[0-9a-f]{64}$ ]] || exit 1
domain=askmedia.news
release_dir="/var/www/coverage/releases/$release_id"
stage_dir="/root/events-coverage-setup/releases/$release_id"
backup_dir="/root/events-coverage-backups/deploy-$release_id"
main_path=/etc/caddy/Caddyfile
site_path=/etc/caddy/sites/askmedia.news.caddy
current_path=/var/www/coverage/current
site_temp="/etc/caddy/sites/.askmedia.news.deploy-$release_id"
current_temp="/var/www/coverage/.current-$release_id"
changed=0; complete=0; reload_attempted=0
fail() { printf '%s\n' "$*" >&2; exit 1; }
main_digest() { sha256sum "$main_path" | cut -d ' ' -f 1; }
m4_status() {
    curl --silent --show-error --noproxy '*' --connect-timeout 3 --max-time 10 \
        --output /dev/null --write-out '%{http_code}' http://127.0.0.1:8080/
}
restore_previous() {
    cp --preserve=all -- "$backup_dir/site.before" "$site_temp" &&
        mv --force --no-target-directory -- "$site_temp" "$site_path" || return 1
    ln -s -- "$previous_target" "$current_temp" &&
        mv --force --no-target-directory -- "$current_temp" "$current_path" || return 1
    if (( reload_attempted )); then
        caddy validate --config "$main_path" --adapter caddyfile > "$backup_dir/rollback-validation.log" 2>&1 &&
            systemctl reload caddy.service > "$backup_dir/rollback-reload.log" 2>&1 || return 1
    fi
}
finish() {
    local result=$?
    trap - EXIT INT TERM
    if (( changed && ! complete )); then
        printf 'Deployment failed; restoring the previous site and release.\n' >&2
        rm -f -- "$site_temp" "$current_temp"
        if restore_previous; then
            printf 'Previous site and release restored. Backup: %s\n' "$backup_dir" >&2
        else
            printf 'ROLLBACK FAILED. Inspect %s over SSH.\n' "$backup_dir" >&2
            result=2
        fi
        (( result != 0 )) || result=1
    fi
    rm -f -- "$site_temp" "$current_temp"
    exit "$result"
}
exec 9>/run/lock/events-coverage-setup.lock
flock --nonblock 9 || fail 'Another dashboard setup or activation is running.'
[[ -f "$main_path" && ! -L "$main_path" && -f "$site_path" && ! -L "$site_path" ]] || fail 'Expected the prepared Caddy files.'
[[ -L "$current_path" && -d "$current_path" ]] || fail 'Expected a valid existing current release link.'
[[ -r "$stage_dir/askmedia.Caddyfile" ]] || fail 'The staged public site template is missing.'
chown root:root "$stage_dir/askmedia.Caddyfile"
chmod 0600 "$stage_dir/askmedia.Caddyfile"
for filename in index.html index.html.gz; do
    [[ -f "$release_dir/$filename" && ! -L "$release_dir/$filename" ]] || fail 'The uploaded release is incomplete.'
done
[[ "$(find "$release_dir" -mindepth 1 -maxdepth 1 | wc -l)" -eq 2 ]] || fail 'Unexpected files in the uploaded release.'
printf '%s  %s\n%s  %s\n' "$html_sha" "$release_dir/index.html" "$gzip_sha" "$release_dir/index.html.gz" | sha256sum --check --status
gzip -t "$release_dir/index.html.gz"
gzip -cd "$release_dir/index.html.gz" | cmp - "$release_dir/index.html"
chown root:caddy "$release_dir" "$release_dir/index.html" "$release_dir/index.html.gz"
chmod 0755 "$release_dir"; chmod 0644 "$release_dir/index.html" "$release_dir/index.html.gz"
runuser -u caddy -- test -r "$release_dir/index.html"
runuser -u caddy -- test -r "$release_dir/index.html.gz"
systemctl is-active --quiet caddy.service
systemctl is-active --quiet cloudflared.service
baseline_m4="$(m4_status)"
[[ "$baseline_m4" == 302 ]] || fail "Unexpected M4 baseline: HTTP $baseline_m4"
previous_target="$(readlink "$current_path")"
main_sha_before="$(main_digest)"
[[ "$(grep -Fxc 'import /etc/caddy/sites/askmedia.news.caddy' "$main_path" || true)" == 1 ]] || fail 'Expected exactly one prepared site import.'
install -d -o root -g root -m 0700 /root/events-coverage-backups
mkdir -- "$backup_dir"
cp --preserve=all -- "$site_path" "$backup_dir/site.before"
printf '%s\n' "$previous_target" > "$backup_dir/current.before"
printf '%s\n' "$main_sha_before" > "$backup_dir/main-caddy.sha256"
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
awk -v staged="$stage_dir/askmedia.Caddyfile" \
    '$0 == "import /etc/caddy/sites/askmedia.news.caddy" { print "import " staged; next } { print }' \
    "$main_path" > "$backup_dir/Caddyfile.validation"
caddy validate --config "$backup_dir/Caddyfile.validation" --adapter caddyfile > "$backup_dir/validation.log" 2>&1
[[ "$(main_digest)" == "$main_sha_before" ]] || fail 'The main Caddy configuration changed during preparation.'
changed=1
install -o root -g caddy -m 0640 "$stage_dir/askmedia.Caddyfile" "$site_temp"
mv --force --no-target-directory -- "$site_temp" "$site_path"
ln -s -- "$release_dir" "$current_temp"
mv --force --no-target-directory -- "$current_temp" "$current_path"
runuser -u caddy -- test -r "$site_path"
runuser -u caddy -- test -r "$current_path/index.html"
caddy validate --config "$main_path" --adapter caddyfile > "$backup_dir/live-validation.log" 2>&1
reload_attempted=1
systemctl reload caddy.service > "$backup_dir/reload.log" 2>&1

# Curl verifies the normal certificate and hashes streamed bodies without printing them.
for encoding in identity gzip; do
    curl_options=(--silent --show-error --fail --noproxy '*' --connect-timeout 5 --max-time 90
        --resolve "$domain:443:127.0.0.1" --header "Accept-Encoding: $encoding"
        --dump-header "$backup_dir/$encoding.headers")
    [[ "$encoding" != gzip ]] || curl_options+=(--compressed)
    curl "${curl_options[@]}" "https://$domain/" | sha256sum > "$backup_dir/$encoding.body.sha256"
    code="$(awk '/^HTTP\// { code=$2 } END { print code }' "$backup_dir/$encoding.headers")"
    [[ "$code" == 200 ]] || fail "Public HTTPS returned HTTP $code for $encoding."
    [[ "$(cut -d ' ' -f 1 "$backup_dir/$encoding.body.sha256")" == "$html_sha" ]] || fail "Public HTTPS body differs from the uploaded HTML for $encoding."
    if [[ "$encoding" == gzip ]]; then
        content_encoding="$(tr -d '\r' < "$backup_dir/gzip.headers" | awk 'tolower($1)=="content-encoding:" { print tolower($2) }')"
        [[ "$content_encoding" == gzip ]] || fail 'The gzip response has no Content-Encoding: gzip.'
    fi
done
systemctl is-active --quiet caddy.service
systemctl is-active --quiet cloudflared.service
[[ "$(m4_status)" == "$baseline_m4" ]] || fail 'M4 changed after dashboard activation.'
[[ "$(main_digest)" == "$main_sha_before" ]] || fail 'The main Caddy configuration changed during activation.'
complete=1
printf 'Published: https://%s/\nRelease: %s\nPrevious: %s\nBackup: %s\n' "$domain" "$release_id" "$previous_target" "$backup_dir"
printf 'HTML SHA-256: %s\nGzip SHA-256: %s\nM4: HTTP %s; Caddy and cloudflared active.\n' "$html_sha" "$gzip_sha" "$baseline_m4"
ACTIVATE_REMOTE
