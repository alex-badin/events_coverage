#!/bin/zsh
# Build and publish the website from an existing JSON export. No warehouse rebuild or paid calls.
# Run: DEPLOY_HOST=m4-pilot zsh scripts/deploy_dashboard.sh
set -euo pipefail

project_root="${0:A:h:h}"
project_python="$project_root/.venv/bin/python"
input_data="${DEPLOY_DATA-$project_root/outputs/dashboard_exports/dashboard_data.json}"
site_template="$project_root/configs/deploy/askmedia.Caddyfile"
[[ -f "$input_data" && -r "$input_data" && -s "$input_data" ]] || { print -u2 'The dashboard JSON export is missing or unreadable.'; exit 1; }
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
web_dir="$deploy_tmp_dir/web"
"$project_python" "$project_root/dashboard/build_dashboard.py" \
    --web-dir "$web_dir" --release-id "$release_id" --data "${input_data:A}"
cp -- "$site_template" "$deploy_tmp_dir/askmedia.Caddyfile"
chmod 0600 "$deploy_tmp_dir/askmedia.Caddyfile"
"$project_python" - "$web_dir" > "$deploy_tmp_dir/manifest.sha256" <<'HASH_FILES'
import gzip
import hashlib
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
files = set()
dirs = set()
for path in root.rglob("*"):
    name = path.relative_to(root).as_posix()
    if not path.is_symlink() and path.is_file():
        files.add(name)
    elif not path.is_symlink() and path.is_dir():
        dirs.add(name)
    else:
        raise SystemExit(f"Unexpected release entry: {name}")
events = {name for name in files if re.fullmatch(r"data/events/[0-9a-f]{32}[.]json", name)}
plain_files = {"index.html", "data/index.json"} | events
expected = plain_files | {f"{name}.gz" for name in plain_files}
if not events or dirs != {"data", "data/events"} or files != expected:
    raise SystemExit("The website build is incomplete or contains unexpected paths.")
for name in sorted(plain_files):
    plain = (root / name).read_bytes()
    compressed = (root / f"{name}.gz").read_bytes()
    if not plain or gzip.decompress(compressed) != plain:
        raise SystemExit(f"Gzip does not match {name}.")
    print(f"{hashlib.sha256(plain).hexdigest()}  {name}")
    print(f"{hashlib.sha256(compressed).hexdigest()}  {name}.gz")
HASH_FILES
chmod 0600 "$deploy_tmp_dir/manifest.sha256"
manifest_sha="$("$project_python" -c 'import hashlib, sys; from pathlib import Path; print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())' "$deploy_tmp_dir/manifest.sha256")"
remote_upload="/var/www/coverage/releases/.staged-$release_id"
remote_stage="/root/events-coverage-setup/releases/$release_id"
ssh_options=(-o BatchMode=yes -o ConnectTimeout=15)
ssh "${ssh_options[@]}" -- "$deploy_host" bash -s -- "$release_id" <<'PREPARE_REMOTE'
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Deployment currently requires the existing root SSH account.' >&2; exit 1; }
[[ "$1" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$ ]] || exit 1
[[ -d /var/www/coverage/releases && ! -L /var/www/coverage/releases ]] || { echo 'Prepare the dashboard host first.' >&2; exit 1; }
umask 077
mkdir -- "/var/www/coverage/releases/.staged-$1"
install -d -o root -g root -m 0700 /root/events-coverage-setup/releases
mkdir -- "/root/events-coverage-setup/releases/$1"
PREPARE_REMOTE
rsync -rz \
    --rsh='ssh -o BatchMode=yes -o ConnectTimeout=15' -- \
    "$web_dir/" "$deploy_host:$remote_upload/"
rsync -a --no-owner --no-group \
    --rsh='ssh -o BatchMode=yes -o ConnectTimeout=15' -- \
    "$deploy_tmp_dir/askmedia.Caddyfile" "$deploy_tmp_dir/manifest.sha256" "$deploy_host:$remote_stage/"

ssh "${ssh_options[@]}" -- "$deploy_host" bash -s -- "$release_id" "$manifest_sha" <<'ACTIVATE_REMOTE'
set +x
set -euo pipefail
umask 077
release_id="$1"; manifest_sha="$2"
[[ $EUID -eq 0 && "$release_id" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$ ]] || exit 1
[[ "$manifest_sha" =~ ^[0-9a-f]{64}$ ]] || exit 1
domain=askmedia.news
release_dir="/var/www/coverage/releases/$release_id"
upload_dir="/var/www/coverage/releases/.staged-$release_id"
stage_dir="/root/events-coverage-setup/releases/$release_id"
manifest="$stage_dir/manifest.sha256"
backup_dir="/root/events-coverage-backups/deploy-$release_id"
main_path=/etc/caddy/Caddyfile
site_path=/etc/caddy/sites/askmedia.news.caddy
current_path=/var/www/coverage/current
site_temp="/etc/caddy/sites/.askmedia.news.deploy-$release_id"
current_temp="/var/www/coverage/.current-$release_id"
site_changed=0; current_changed=0; complete=0; reload_attempted=0
fail() { printf '%s\n' "$*" >&2; exit 1; }
main_digest() { sha256sum "$main_path" | cut -d ' ' -f 1; }
m4_status() {
    curl --silent --show-error --noproxy '*' --connect-timeout 3 --max-time 10 \
        --output /dev/null --write-out '%{http_code}' http://127.0.0.1:8080/
}
restore_previous() {
    if (( current_changed )); then
        # Browsers may already have loaded the new page and need its versioned JSON.
        ln -s -- "$previous_target" "$current_temp" &&
            mv --force --no-target-directory -- "$current_temp" "$current_path" || return 1
    elif (( site_changed )); then
        cp --preserve=all -- "$backup_dir/site.before" "$site_temp" &&
            mv --force --no-target-directory -- "$site_temp" "$site_path" || return 1
        if (( reload_attempted )); then
            caddy validate --config "$main_path" --adapter caddyfile > "$backup_dir/rollback-validation.log" 2>&1 &&
                systemctl reload caddy.service > "$backup_dir/rollback-reload.log" 2>&1 || return 1
        fi
    fi
    [[ "$(readlink "$current_path")" == "$previous_target" ]]
}
finish() {
    local result=$?
    trap - EXIT INT TERM
    if (( (site_changed || current_changed) && ! complete )); then
        printf 'Deployment failed; restoring the previous dashboard.\n' >&2
        rm -f -- "$site_temp" "$current_temp"
        if restore_previous; then
            printf 'Previous dashboard restored. Backup: %s\n' "$backup_dir" >&2
        else
            printf 'ROLLBACK FAILED. Inspect %s over SSH.\n' "$backup_dir" >&2
            result=2
        fi
        (( result != 0 )) || result=1
    fi
    rm -f -- "$site_temp" "$current_temp"
    exit "$result"
}

artifact_sha() { awk -v artifact="$1" '$2 == artifact { print $1; exit }' "$manifest"; }
response_header() {
    awk -F ': *' -v name="$2" 'tolower($1) == name { sub(/\r$/, "", $2); print $2 }' "$1"
}
https_options=(--silent --show-error --noproxy '*' --connect-timeout 5 --max-time 90
    --resolve "$domain:443:127.0.0.1")
check_https() {
    local url_path="$1" encoding="$2" expected_sha="$3" log_name="$4"
    local headers="$backup_dir/$log_name.headers"
    local hash_file="$backup_dir/$log_name.body.sha256"
    local options=(--fail --header "Accept-Encoding: $encoding" --dump-header "$headers")
    [[ "$encoding" != gzip ]] || options+=(--compressed)
    curl "${https_options[@]}" "${options[@]}" "https://$domain$url_path" | sha256sum > "$hash_file"
    [[ "$(awk '/^HTTP\// { sub(/\r$/, "", $2); code=$2 } END { print code }' "$headers")" == 200 ]] ||
        fail "Unexpected HTTPS status for $url_path ($encoding)."
    [[ "$(cut -d ' ' -f 1 "$hash_file")" == "$expected_sha" ]] ||
        fail "HTTPS body differs from the uploaded file for $url_path ($encoding)."
    if [[ "$encoding" == gzip ]]; then
        [[ "$(response_header "$headers" content-encoding)" == gzip ]] ||
            fail "No Content-Encoding: gzip for $url_path."
    fi
}
check_status() {
    local code
    code="$(curl "${https_options[@]}" --head --output /dev/null --write-out '%{http_code}' "https://$domain$1")"
    [[ "$code" == "$2" ]] || fail "HTTPS returned $code for $1; expected $2."
}

exec 9>/run/lock/events-coverage-setup.lock
flock --nonblock 9 || fail 'Another dashboard setup or activation is running.'
[[ -f "$main_path" && ! -L "$main_path" && -f "$site_path" && ! -L "$site_path" ]] || fail 'Expected the prepared Caddy files.'
[[ -L "$current_path" && -d "$current_path" ]] || fail 'Expected a valid existing current release link.'
[[ -d "$upload_dir" && ! -L "$upload_dir" && ! -e "$release_dir" && ! -L "$release_dir" ]] ||
    fail 'Expected an unpublished, staged release.'
for filename in "$stage_dir/askmedia.Caddyfile" "$manifest"; do
    [[ -f "$filename" && ! -L "$filename" ]] || fail "Missing staged file: $filename"
done
chown root:root "$stage_dir/askmedia.Caddyfile" "$manifest"
chmod 0600 "$stage_dir/askmedia.Caddyfile" "$manifest"
printf '%s  %s\n' "$manifest_sha" "$manifest" | sha256sum --check --status ||
    fail 'The staged manifest differs from the local manifest.'
[[ -z "$(find "$upload_dir" ! -type d ! -type f -print -quit)" ]] ||
    fail 'The uploaded release contains a link or a special file.'
{
    printf '%s\n' './data' './data/events'
    sed -E 's/^[0-9a-f]{64}  /\.\//' "$manifest"
} | LC_ALL=C sort > "$stage_dir/expected-tree"
(cd "$upload_dir"; find . -mindepth 1 -print | LC_ALL=C sort) | cmp -s - "$stage_dir/expected-tree" ||
    fail 'Unexpected or missing files in the uploaded release.'
(cd "$upload_dir"; sha256sum --check --strict --status "$manifest") ||
    fail 'An uploaded file differs from the local build.'
chown -R root:caddy "$upload_dir"
find "$upload_dir" -type d -exec chmod 0755 {} +
find "$upload_dir" -type f -exec chmod 0644 {} +
runuser -u caddy -- test -r "$upload_dir/index.html"
runuser -u caddy -- test -r "$upload_dir/data/index.json.gz"
html_sha="$(artifact_sha index.html)"
gzip_sha="$(artifact_sha index.html.gz)"
sample_event="$(awk '$2 ~ /^data\/events\/[0-9a-f]+[.]json$/ { print $2; exit }' "$manifest")"
[[ -n "$sample_event" ]] || fail 'The release has no event details.'
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
mv --no-target-directory -- "$upload_dir" "$release_dir"
if ! cmp -s "$stage_dir/askmedia.Caddyfile" "$site_path"; then
    site_changed=1
    install -o root -g caddy -m 0640 "$stage_dir/askmedia.Caddyfile" "$site_temp"
    mv --force --no-target-directory -- "$site_temp" "$site_path"
    runuser -u caddy -- test -r "$site_path"
    caddy validate --config "$main_path" --adapter caddyfile > "$backup_dir/live-validation.log" 2>&1
    reload_attempted=1
    systemctl reload caddy.service > "$backup_dir/reload.log" 2>&1
    if [[ -f "$current_path/.bootstrap-pending" ]]; then
        check_status / 503
    else
        previous_sha="$(sha256sum "$current_path/index.html" | cut -d ' ' -f 1)"
        check_https / identity "$previous_sha" previous
    fi
fi

# Check the new route while visitors still see the previous page.
version_prefix="/versions/$release_id"
check_https "$version_prefix/data/index.json" gzip "$(artifact_sha data/index.json)" data-index
check_https "$version_prefix/$sample_event" identity "$(artifact_sha "$sample_event")" event
[[ "$(response_header "$backup_dir/data-index.headers" cache-control)" == 'public, max-age=31536000, immutable' ]] ||
    fail 'Versioned JSON is missing its immutable cache policy.'
check_status "$version_prefix/index.html" 404
systemctl is-active --quiet caddy.service
systemctl is-active --quiet cloudflared.service
[[ "$(m4_status)" == "$baseline_m4" ]] || fail 'M4 changed before dashboard activation.'
[[ "$(main_digest)" == "$main_sha_before" ]] || fail 'The main Caddy configuration changed before activation.'

ln -s -- "$release_dir" "$current_temp"
current_changed=1
mv --force --no-target-directory -- "$current_temp" "$current_path"
check_https / identity "$html_sha" identity
check_https / gzip "$html_sha" gzip
check_https /index.html identity "$html_sha" index-html
for log_name in identity index-html; do
    [[ "$(response_header "$backup_dir/$log_name.headers" cache-control)" == no-cache ]] ||
        fail 'The entry page is missing its cache revalidation policy.'
done
check_status /data/index.json 404
systemctl is-active --quiet caddy.service
systemctl is-active --quiet cloudflared.service
[[ "$(m4_status)" == "$baseline_m4" ]] || fail 'M4 changed after dashboard activation.'
[[ "$(main_digest)" == "$main_sha_before" ]] || fail 'The main Caddy configuration changed during activation.'
complete=1
printf 'Published: https://%s/\nRelease: %s\nPrevious: %s\nBackup: %s\n' "$domain" "$release_id" "$previous_target" "$backup_dir"
printf 'HTML SHA-256: %s\nGzip SHA-256: %s\nM4: HTTP %s; Caddy and cloudflared active.\n' "$html_sha" "$gzip_sha" "$baseline_m4"
ACTIVATE_REMOTE
