#!/usr/bin/env python3
"""Idempotently create the GitHub section's operational documentation."""
import os
import re
import sqlite3
from datetime import datetime
from html import unescape

DB_PATH = os.environ.get("BASICWIKI_DB", "/data/wiki.db")
PROFILE = "https://github.com/jeffavery"

BACKUP_CHECK = """<h2>Check the backup destination</h2>
<p>Run this before an update or manual backup. <code>findmnt</code> must show the SMB source <code>//shopserver/ShopDockerBackup</code>. If it shows nothing, do not run the backup yet: files could be written to the local empty mountpoint instead of the server.</p>
<pre><code># Show what is mounted at the backup destination.
findmnt /mnt/shopdocker-backup

# Confirm the path is a real mount and show available space.
mountpoint /mnt/shopdocker-backup
df -h /mnt/shopdocker-backup

# If it is not mounted, ask Linux to mount this one fstab entry.
sudo mount /mnt/shopdocker-backup

# Recheck it. The SOURCE column should be //shopserver/ShopDockerBackup.
findmnt /mnt/shopdocker-backup

# If mounting failed, inspect this boot's mount/network messages.
sudo journalctl -b --no-pager | grep -Ei 'shopdocker-backup|cifs|smb|mount'</code></pre>
<p>Typical search terms from the error are <code>CIFS permission denied</code>, <code>host is down</code>, <code>no route to host</code>, <code>bad UNC</code>, or <code>mount error</code>. Check that ShopServer is reachable, the share exists, the credentials file still exists, and the relevant <code>/etc/fstab</code> entry has not changed. Never print the credentials file.</p>
<h3>Check the backup job</h3>
<pre><code># Show the schedule and the most recent service result.
sudo systemctl status shopdocker-backup.timer
sudo systemctl status shopdocker-backup.service

# Read the last 150 backup log lines.
sudo journalctl -u shopdocker-backup.service -n 150 --no-pager

# Show completed and incomplete archives without opening them.
ls -lh /mnt/shopdocker-backup/ShopDocker_*.tar.gz
ls -lh /mnt/shopdocker-backup/ShopDocker_*.incomplete</code></pre>
<p>A completed <code>.tar.gz</code> is retained for 30 full days and becomes deletion-eligible on day 31. An <code>.incomplete</code> file means publication did not finish; investigate the journal and container state before deleting it.</p>"""

GIT_SAFETY = """<h2>Keep private/runtime files out of Git</h2>
<p>Add project-appropriate rules to <code>.gitignore</code> before staging. Do not blindly copy every rule if the project intentionally versions a similarly named example file.</p>
<pre><code># Common local-only files.
.env
.env.*
!.env.example
data/
uploads/
backups/
*.db
*.sqlite
*.sqlite3
*.log
*.tar
*.tar.gz</code></pre>
<pre><code># List changed and untracked filenames before staging.
git status --short

# Stage only the files you deliberately edited; avoid \"git add .\".
git add path/to/changed-file

# Review the exact list that would be committed.
git diff --cached --name-status
git diff --cached --stat

# Confirm representative private paths are ignored.
# \"No such path\" is fine if that project does not use one.
git check-ignore -v .env data/ uploads/ 2>/dev/null || true

# These commands should print nothing. Output means a private/runtime
# path is already tracked and needs attention before committing.
git ls-files '.env' '.env.*' 'data/*' 'uploads/*' '*.db' '*.sqlite*' '*.log' '*.tar*'</code></pre>
<p>If a private file is staged but was never committed, run <code>git restore --staged PATH</code>, add an ignore rule, and check again. If it is already tracked, use <code>git rm --cached PATH</code> to stop tracking it without deleting the local file. If a real secret was ever committed or pushed, changing <code>.gitignore</code> is not enough: rotate that password/token/key and then decide whether repository history must be cleaned.</p>"""

GIT_WORK = """<h2>Edit and publish code</h2>
<pre><code># Enter the repository and confirm the current branch and changes.
cd PROJECT_PATH
git status

# Download remote information without changing local files.
git fetch --all --prune

# Update main only when status is clean. --ff-only refuses a surprise merge.
git switch main
git pull --ff-only

# Work on a separate branch so main stays easy to update and recover.
git switch -c change/short-description

# Edit files, then check whitespace/errors and review the change.
git diff --check
git diff

# Stage only intentional files, review them, commit, and publish the branch.
git add path/to/changed-file
git diff --cached --name-status
git commit -m "Describe the change"
git push -u origin change/short-description</code></pre>
<p>Replace <code>PROJECT_PATH</code>, branch names, and file paths. Open a pull request on GitHub, review the Files changed tab, and merge only after tests pass. The separate branch makes review and abandonment safe without disturbing <code>main</code>.</p>""" + GIT_SAFETY

COMMON_TROUBLE = """<h2>Troubleshooting</h2>
<h3>Container exits or keeps restarting</h3>
<p>You may see <code>Restarting</code>, an unhealthy state, or repeated startup messages. Capture the error before rebuilding.</p>
<pre><code># Show state, exit codes, and health.
docker compose ps
docker inspect --format='status={{.State.Status}} exit={{.State.ExitCode}} error={{.State.Error}} health={{if .State.Health}}{{.State.Health.Status}}{{end}}' CONTAINER

# Read recent logs, then follow new messages while reproducing the problem.
docker compose logs --tail=200 SERVICE
docker compose logs --follow SERVICE</code></pre>
<p>Press <code>Ctrl+C</code> to stop following logs. Fix the first useful error: missing setting, permission, port collision, unavailable dependency, or damaged data. Then run <code>docker compose up -d SERVICE</code> and check again.</p>
<h3>Application suddenly shows empty data</h3>
<p>This usually means an expected NAS/bind mount is absent and Docker can only see an empty local directory. Stop the application before it writes there.</p>
<pre><code># Stop writes first.
docker compose stop SERVICE

# Compare Compose's intended mounts with the container's actual mounts.
docker compose config
docker inspect --format='{{range .Mounts}}{{.Source}} -> {{.Destination}} ({{.Type}}){{println}}{{end}}' CONTAINER

# Check the host mount and a small directory listing.
findmnt EXPECTED_HOST_MOUNT
mountpoint EXPECTED_HOST_MOUNT
ls -la EXPECTED_HOST_MOUNT | head

# Remount the specific fstab entry, verify it, then restart.
sudo mount EXPECTED_HOST_MOUNT
findmnt EXPECTED_HOST_MOUNT
docker compose up -d SERVICE</code></pre>
<h3>Caddy returns 502 Bad Gateway</h3>
<p>A 502 means Caddy answered, but it could not reach the configured upstream.</p>
<pre><code># Check the application and recent errors.
docker compose ps
docker compose logs --tail=100 SERVICE

# Find the hostname and reverse_proxy target in the active Caddyfile.
grep -n -A12 'HOSTNAME' /opt/docker/caddy/Caddyfile

# For container-name upstreams, both containers need the same Docker network.
docker inspect --format='{{json .NetworkSettings.Networks}}' CONTAINER
docker inspect --format='{{json .NetworkSettings.Networks}}' caddy

# Validate Caddy before applying configuration changes.
docker exec caddy caddy validate --config /etc/caddy/Caddyfile
docker exec caddy caddy reload --config /etc/caddy/Caddyfile</code></pre>
<p>If the upstream is a host IP/port, test that exact address from the server. If it is a container name, confirm the service name, internal port, and shared network. Restore the previous Caddy configuration if validation fails.</p>
<h3>Database errors</h3>
<p>Symptoms include migration failures, corruption messages, locked-database errors, or a service that exits when opening its data store.</p>
<pre><code># Stop every service that writes to this application's database.
docker compose stop

# Record ownership and make a timestamped rollback copy of the app data.
sudo ls -ld DATA_PATH
sudo cp -a DATA_PATH "DATA_PATH.before-repair-$(date +%Y%m%d-%H%M%S)"

# Read logs without changing the database.
docker compose logs --tail=300

# Start only after following the application's database-specific repair docs.
docker compose up -d
docker compose ps</code></pre>
<p>Do not run a generic repair command against an unfamiliar database. SQLite, PostgreSQL, Redis, and Elasticsearch have different recovery procedures.</p>"""

def restore_block(project, paths, compose="docker compose", services=""):
    archive_path = project.lstrip("/")
    label = project.strip("/").split("/")[-1]
    path_lines = "\n".join(f"# Restore {p} from staging after verifying it exists there." for p in paths)
    return f"""<h2>Restore from a ShopDocker archive</h2>
<p>Replace the example archive name. This stages the archive first and never extracts directly over production.</p>
<pre><code># Choose a completed archive and validate gzip integrity.
ARCHIVE="/mnt/shopdocker-backup/ShopDocker_YYYY-MM-DD_HH-MM-SS.tar.gz"
gzip -t "$ARCHIVE"

# Confirm this application's paths are present without displaying file contents.
tar -tzf "$ARCHIVE" | grep -E '^{archive_path}/' | head -50

# Stop the application and preserve current data as rollback.
cd {project}
{compose} stop {services}
sudo cp -a {project} "{project}.before-restore-$(date +%Y%m%d-%H%M%S)"

# Extract into a new isolated staging directory.
RESTORE_STAGE="$(mktemp -d /tmp/{label}-restore-XXXXXX)"
sudo tar --numeric-owner -xpf "$ARCHIVE" -C "$RESTORE_STAGE" \
  --xattrs --acls "{archive_path}"

{path_lines}
# Review paths and ownership before copying anything into production.
sudo find "$RESTORE_STAGE/{archive_path}" -maxdepth 2 -printf '%M %u:%g %p\\n' | head -100

# After review, copy the staged application tree into place.
sudo cp -a "$RESTORE_STAGE/{archive_path}/." "{project}/"

# Rebuild/recreate, check state, and inspect startup logs.
{compose} up -d --build
{compose} ps
{compose} logs --tail=150</code></pre>
<p>Test the application before removing the timestamped rollback copy or staging directory. External media paths under <code>/mnt</code> are not restored by this archive unless explicitly documented.</p>"""

def volume_restore_block(container, volume, archive_path):
    return f"""<h2>Restore the named-volume data</h2>
<p>Replace the archive name. This stages the volume first and preserves current data before replacement.</p>
<pre><code># Choose and validate a completed archive.
ARCHIVE="/mnt/shopdocker-backup/ShopDocker_YYYY-MM-DD_HH-MM-SS.tar.gz"
gzip -t "$ARCHIVE"
tar -tzf "$ARCHIVE" | grep -E '^{archive_path}/' | head -50

# Stop writes and preserve the current volume data.
docker stop {container}
sudo cp -a /var/lib/docker/volumes/{volume}/_data \
  "/var/lib/docker/volumes/{volume}/_data.before-restore-$(date +%Y%m%d-%H%M%S)"

# Extract only this volume into an isolated staging directory.
RESTORE_STAGE="$(mktemp -d /tmp/{volume}-restore-XXXXXX)"
sudo tar --numeric-owner -xpf "$ARCHIVE" -C "$RESTORE_STAGE" \
  --xattrs --acls "{archive_path}"

# Inspect ownership and paths before replacing production data.
sudo find "$RESTORE_STAGE/{archive_path}" -maxdepth 2 -printf '%M %u:%g %p\\n' | head -100

# Replace the volume contents while the container remains stopped.
sudo find /var/lib/docker/volumes/{volume}/_data -mindepth 1 -maxdepth 1 -exec rm -rf -- {{}} +
sudo cp -a "$RESTORE_STAGE/{archive_path}/." \
  /var/lib/docker/volumes/{volume}/_data/

# Restart and inspect state and logs.
docker start {container}
docker ps --filter name={container}
docker logs --tail=150 {container}</code></pre>
<p>The deletion line affects only the explicitly named volume after a rollback copy is made. Verify the exact volume name before running it.</p>"""

def rollback_block(kind, project, compose, image="", service="", repo_path=""):
    if kind == "git":
        repo_path = repo_path or project
        return f"""<h2>Rollback an update</h2>
<p>Yes, a pulled Git update can be undone. Capture the commit before pulling; the old commit remains available even after the pull.</p>
<pre><code>cd {repo_path}

# Before updating: require a clean tree and record the current commit.
git status
git rev-parse HEAD
git branch "rollback/pre-update-$(date +%Y%m%d-%H%M%S)"

# Update and deploy.
git pull --ff-only
{compose} up -d --build

# If validation fails, list rollback branches and select the saved one.
git branch --list 'rollback/pre-update-*'
git switch rollback/pre-update-YYYYMMDD-HHMMSS
{compose} up -d --build
{compose} ps
{compose} logs --tail=150

# Later, return to main only after deciding how to resolve the failed update.
git switch main</code></pre>
<p>If you forgot to create the rollback branch, use <code>git reflog --date=local</code> to locate the commit immediately before the pull, then create a branch at that commit. Do not use a destructive reset while uncommitted work exists.</p>"""
    if kind in ("image", "build"):
        action = (f"{compose} pull {service}\n{compose} up -d {service}"
                  if kind == "image" else f"{compose} up -d --build {service}")
        restore = (f"{compose} up -d --no-deps {service}" if kind == "image"
                   else f"{compose} up -d --no-build --no-deps {service}")
        return f"""<h2>Rollback an image update</h2>
<p>Because this app pulls a container image rather than Git source, tag the current local image before pulling.</p>
<pre><code>cd {project}

# Before updating: preserve the exact current image under a rollback tag.
docker image inspect {image} --format '{{{{.Id}}}}'
docker image tag {image} local/{service}-rollback:pre-update

# Pull or build and recreate with the new image.
{action}
{compose} ps
{compose} logs --tail=150 {service}

# If validation fails, put the saved image back under the Compose tag.
docker image tag local/{service}-rollback:pre-update {image}
{restore}
{compose} ps
{compose} logs --tail=150 {service}</code></pre>
<p>Do not run <code>docker image prune</code> until the update is proven good; pruning can remove the rollback image.</p>"""
    return """<h2>Rollback an update</h2><p>This container has no verified Compose project or source folder. Before changing it, recover and document its creation command or Compose file, then preserve its current image with <code>docker image inspect</code> and <code>docker image tag</code>. Do not update it from this page until that deployment definition is known.</p>"""

def app_page(a):
    links = f'<li>Application: <a href="{a["url"]}">{a["url"]}</a></li>' if a.get("url") else "<li>Application URL: no public route verified</li>"
    repo = a.get("repo")
    links += f'<li>GitHub: <a href="{repo}">{repo}</a></li>' if repo else "<li>GitHub: no repository verified for this local/custom deployment</li>"
    if a.get("upstream"): links += f'<li>Original GitHub: <a href="{a["upstream"]}">{a["upstream"]}</a></li>'
    compose = a.get("compose", "docker compose")
    if a["kind"] == "image":
        update = f"""# Enter the deployment folder and review resolved configuration.
cd {a["project"]}
{compose} config

# Pull the current image and recreate only this service.
{compose} pull {a["service"]}
{compose} up -d {a["service"]}
{compose} ps
{compose} logs --tail=100 {a["service"]}"""
    elif a["kind"] == "git":
        update = f"""# Enter the repository and confirm there are no uncommitted changes.
cd {a.get("repo_path", a["project"])}
git status

# Record the current commit, pull only a fast-forward update, and rebuild.
git rev-parse HEAD
git pull --ff-only
{compose} up -d --build
{compose} ps
{compose} logs --tail=100"""
    elif a["kind"] == "build":
        update = f"""# Review the locally maintained source and resolved Compose file.
cd {a["project"]}
{compose} config

# Build a new image, recreate the service, and check startup.
{compose} up -d --build {a["service"]}
{compose} ps
{compose} logs --tail=100 {a["service"]}"""
    else:
        update = f"""# Read-only inspection: no verified update definition exists yet.
docker inspect {a["container"]} --format='image={{{{.Config.Image}}}} status={{{{.State.Status}}}}'
docker logs --tail=100 {a["container"]}"""
    return f"""<h2>Links and technical outline</h2><ul>{links}<li>Project: <code>{a["project"]}</code></li><li>Container/service: <code>{a["container"]}</code> / <code>{a["service"]}</code></li><li>{a["outline"]}</li></ul>
<h2>Persistent data and backup</h2><p>{a["data"]}</p><p>The ShopDocker configuration backup destination is <code>/mnt/shopdocker-backup</code>, with completed archives retained for 30 full days.</p>
{BACKUP_CHECK}
<h2>Update and validate</h2><p>Read the project's release notes first. Confirm the backup mount and latest successful archive, then run:</p><pre><code>{update}</code></pre>
<p>Open the application, sign in if applicable, load existing data, and perform one normal read/write workflow. Check logs once more before declaring the update successful.</p>
{rollback_block(a["kind"],a["project"],compose,a.get("image",""),a["service"],a.get("repo_path",""))}
{a.get("restore_html") or restore_block(a["project"],a["paths"],compose,a.get("restore_services",""))}
{GIT_WORK if a["kind"] == "git" else ""}
{COMMON_TROUBLE}"""

APPS = [
dict(title="BasicWiki",url="https://wiki.jeffavery.com/",repo="https://github.com/jeffavery/BasicWiki",kind="git",project="/opt/docker/basicwiki",container="basicwiki",service="basicwiki",outline="Flask/SQLite/Gunicorn; host 8085 to container 8000.",data="<code>/opt/docker/basicwiki/data</code> contains the SQLite database and uploads; included in the recursive backup.",paths=["/opt/docker/basicwiki/data"]),
dict(title="Links",url="https://links.jeffavery.com/",repo="https://github.com/jeffavery/links",kind="git",project="/opt/docker/links",container="links",service="links",outline="Custom PHP/Apache app on Docker network <code>proxy</code>; Caddy upstream <code>links:80</code>. A separate old development preview container is not production.",data="<code>/opt/docker/links/data</code> contains JSON and uploaded icons; included in the recursive backup.",paths=["/opt/docker/links/data"]),
dict(title="MeTube",url="https://mtd.jeffavery.com/",repo="https://github.com/jeffavery/metube",upstream="https://github.com/alexta69/metube",kind="git",project="/opt/docker/metube",repo_path="/opt/docker/metube/source",compose="docker compose -f /opt/docker/metube/compose.yml",container="metube",service="metube",outline="Customized fork; deployed image <code>jeffavery/metube:archive</code>; host port 8081. Source is <code>/opt/docker/metube/source</code>.",data="Downloads are in <code>/mnt/tubearchiver/metube</code>, outside the ShopDocker archive. Compose/source under <code>/opt/docker</code> are included.",paths=["/opt/docker/metube"],restore_services="metube"),
dict(title="Web Portal",url="",repo="https://github.com/jeffavery/web-portal",upstream="https://github.com/enchant97/web-portal",kind="git",project="/opt/docker/web-portal-dev",container="web-portal-dev",service="web-portal",outline="Customized fork; host port 8788 to container 8000.",data="<code>/opt/docker/web-portal-dev/data</code> and source are included in the recursive backup.",paths=["/opt/docker/web-portal-dev/data"]),
dict(title="Shop Reference",url="https://machining.jeffavery.com/",repo="https://github.com/jeffavery/shop-reference",kind="git",project="/opt/docker/shop-reference",compose="docker compose -f compose.shopdocker.yaml",container="shop-reference",service="shop-reference",outline="Static nginx site on <code>proxy</code>; no persistent application data.",data="Source/deployment files are included in the recursive backup; GitHub is the primary source copy.",paths=["/opt/docker/shop-reference"]),
dict(title="BenchCalc",url="https://jeffavery.com/benchcalc/",repo="https://github.com/jeffavery/benchcalc",kind="git",project="/opt/docker/benchcalc",container="benchcalc",service="benchcalc",outline="Static/build application on Docker network <code>proxy</code>. The server Caddyfile currently routes <code>electronics.jeffavery.com</code> to it; the supplied public URL is hosted separately.",data="No container data mount was observed. Source/deployment files are included in the recursive backup.",paths=["/opt/docker/benchcalc"]),
dict(title="TubeArchivist",url="https://yta.jeffavery.com/",repo="https://github.com/tubearchivist/tubearchivist",kind="image",project="/opt/docker/tubearchivist",container="tubearchivist",service="tubearchivist",image="bbilly1/tubearchivist",outline="Three services: TubeArchivist, Redis, and Elasticsearch; host port 8010.",data="Cache, Redis, and Elasticsearch state under <code>/opt/docker/tubearchivist</code> are backed up. Media at <code>/mnt/tubearchiver</code> is outside the archive.",paths=["/opt/docker/tubearchivist/cache","/opt/docker/tubearchivist/redis","/opt/docker/tubearchivist/es"],restore_services="",),
dict(title="Caddy Manager",url="https://caddymanager.jeffavery.com/",repo="",kind="build",project="/opt/docker/portainer/data/compose/1",compose="docker compose --env-file stack.env -p caddy-manager",container="caddy-manager",service="caddy-manager",image="caddy-manager-caddy-manager:latest",outline="Custom Python manager. It shares Caddy's network namespace; Caddy should be running before it starts. Keep <code>stack.env</code> private.",data="Manager source and private stack file are backed up recursively; Caddy configuration/backups are mounted from <code>/opt/docker/caddy</code>.",paths=["/opt/docker/portainer/data/compose/1","/opt/docker/caddy/Caddyfile","/opt/docker/caddy/backups"]),
dict(title="Caddy",url="",repo="https://github.com/caddyserver/caddy",kind="build",project="/opt/docker/caddy",container="caddy",service="caddy",image="caddy-caddy:latest",outline="Locally built Caddy image with DNS support; reverse proxy on ports 80/443 using Docker network <code>proxy</code> and DreamHost DNS challenges.",data="<code>Caddyfile</code>, <code>data</code>, <code>config</code>, and <code>backups</code> are under <code>/opt/docker/caddy</code> and included.",paths=["/opt/docker/caddy"]),
dict(title="Manyfold",url="https://3dprint.jeffavery.com/",repo="https://github.com/manyfold3d/manyfold",kind="image",project="/opt/docker/manyfold",container="manyfold",service="manyfold",image="ghcr.io/manyfold3d/manyfold-solo:latest",outline="3D model manager; host port 3214.",data="<code>/opt/docker/manyfold/config</code> is backed up. Model library <code>/mnt/3dprints</code> is outside the archive and needs NAS protection.",paths=["/opt/docker/manyfold/config"]),
dict(title="Immich",url="",repo="https://github.com/immich-app/immich",kind="image",project="/opt/docker/immich",container="immich_server (plus immich_machine_learning, immich_postgres, and immich_redis)",service="immich-server",image="ghcr.io/immich-app/immich-server:v3",outline="Photo-management service on host port 2283; its writable external NAS library is <code>/external/photos</code> inside the server.",data="<code>/opt/docker/immich/library</code>, <code>/opt/docker/immich/postgres</code>, Compose configuration, and the private <code>.env</code> are under the recursive ShopDocker backup. NAS photos at <code>/mnt/immich-photos</code> are outside that archive. The library is writable, so Immich may delete originals or write XMP sidecars. Verify the separate root-only SMB credential and <code>/etc/fstab</code> mount during a restore.",paths=["/opt/docker/immich"],restore_services="immich-server immich-machine-learning database redis"),
dict(title="Network Device Directory",url="https://network.jeffavery.com/",repo="https://github.com/jeffavery/NetMon",kind="build",project="/opt/docker/network-directory",container="network-directory",service="network-directory",image="network-directory-network-directory:latest",outline="Version 6 custom Flask network directory using host networking, ARP/Nmap discovery, and port 8088. It analyzes DNS history from both local Pi-hole 6 servers and first compares destinations with a local signature catalog. When both a completed Deep Scan and DNS analysis remain inconclusive, it automatically researches up to three DNS domains in the background, saves a cited manufacturer or device-category suggestion with confidence and evidence, and caches results by domain. Only domain names are submitted for research; local IP addresses, MAC addresses, friendly names, notes, and raw DNS history are excluded. The public <code>jeffavery/NetMon</code> repository is sanitized; the deployed folder is not currently a Git clone.",data="<code>/opt/docker/network-directory/data</code> contains the SQLite device database, DNS research cache, and protected eero, Home Assistant, and Pi-hole connection state. The owner-only project <code>.env</code> contains the runtime OpenAI service-account key and is generated from Bitwarden secret <code>Network Directory OpenAI API Key</code> by the shared refresh workflow. These files are included in the recursive backup; treat the backup as sensitive and never publish or commit runtime data or secrets.",paths=["/opt/docker/network-directory/data"]),
dict(title="Seedbox Storage Usage",url="https://storage.jeffavery.com/",repo="",kind="standalone",project="/opt/docker",compose="docker",container="gigarapid-bandwidth",service="gigarapid-bandwidth",image="gigarapid-bandwidth:latest",outline="Custom standalone container; host port 8787 to container 8080. No Compose project metadata or source repository was verified.",data="Named volume <code>gigarapid-bandwidth-data</code> is an explicit input to the ShopDocker backup.",paths=["/var/lib/docker/volumes/gigarapid-bandwidth-data/_data"],restore_html=volume_restore_block("gigarapid-bandwidth","gigarapid-bandwidth-data","var/lib/docker/volumes/gigarapid-bandwidth-data/_data")),
dict(title="NetAlertX",url="https://monitor.jeffavery.com/",repo="https://github.com/jokob-sk/NetAlertX",kind="image",project="/opt/docker/netalertx",container="netalertx",service="netalertx",image="jokobsk/netalertx:latest",outline="Network monitor using host networking and port 20211.",data="<code>/opt/docker/netalertx/config</code> and <code>/opt/docker/netalertx/db</code> are included.",paths=["/opt/docker/netalertx/config","/opt/docker/netalertx/db"]),
dict(title="ConvertX",url="https://convert.jeffavery.com/",repo="https://github.com/C4illin/ConvertX",kind="image",project="/opt/docker/convertx",container="convertx",service="convertx",image="ghcr.io/c4illin/convertx:latest",outline="File converter; host port 3000.",data="<code>/opt/docker/convertx/data</code> is included in the recursive backup.",paths=["/opt/docker/convertx/data"]),
dict(title="Navidrome",url="https://navidrome.jeffavery.com/",repo="https://github.com/navidrome/navidrome",kind="image",project="/opt/docker/navidrome",container="navidrome",service="navidrome",image="deluan/navidrome:latest",outline="Music server; container port 4533 and Docker network <code>proxy</code>.",data="<code>/opt/docker/navidrome/data</code> is backed up. Read-only music library <code>/mnt/music</code> is outside the archive.",paths=["/opt/docker/navidrome/data"]),
dict(title="Portainer",url="https://portainer1.jeffavery.com/",repo="https://github.com/portainer/portainer",kind="image",project="/opt/docker/portainer",container="portainer",service="portainer",image="portainer/portainer-ce:latest",outline="Docker management UI with access to the Docker socket; ports 8000, 9000, and 9443.",data="<code>/opt/docker/portainer/data</code> is included in the recursive backup.",paths=["/opt/docker/portainer/data"]),
dict(title="Plex",url="https://plex.jeffavery.com/",repo="https://github.com/plexinc/pms-docker",kind="image",project="/opt/docker/plex",container="plex",service="plex",image="plexinc/pms-docker:latest",outline="Media server using host networking. Container is currently stopped and should not be started solely for documentation testing.",data="<code>/opt/docker/plex/config</code> is backed up; transcode and all media paths under <code>/mnt</code> are excluded.",paths=["/opt/docker/plex/config"]),
dict(title="PixelPurge",url="",repo="",kind="build",project="/opt/docker/pixelpurge",container="pixelpurge-pixelpurge-1",service="pixelpurge",image="pixelpurge-pixelpurge:latest",outline="Custom read-only duplicate finder; loopback host port 8080. No Git remote metadata is present in the deployed folder.",data="Named volume <code>pixelpurge_pixelpurge-data</code> is an explicit backup input. Read-only media at <code>/mnt/pixelpurge-photos</code> is outside the archive.",paths=["/var/lib/docker/volumes/pixelpurge_pixelpurge-data/_data"],restore_html=volume_restore_block("pixelpurge-pixelpurge-1","pixelpurge_pixelpurge-data","var/lib/docker/volumes/pixelpurge_pixelpurge-data/_data")),
]

PAGES = {a["title"]: app_page(a) for a in APPS}

PAGES["Everyday Git Workflow"] = f"""<h2>The mental model</h2>
<p>Your working folder has three useful layers: files you are editing, a staging area containing the exact next commit, and committed history. GitHub is a remote copy plus the review interface. <code>git status</code> tells you which layer each change occupies.</p>
{GIT_WORK}
<h2>What each review command tells you</h2><ul><li><code>git status</code>: branch name; modified, staged, and untracked files.</li><li><code>git fetch</code>: downloads remote history but does not edit your files.</li><li><code>git pull --ff-only</code>: moves your local branch forward only when no merge is required.</li><li><code>git diff</code>: unstaged edits.</li><li><code>git diff --cached</code>: exact content in the next commit.</li><li><code>git log --oneline --decorate -10</code>: recent commits and branch pointers.</li></ul>
<h2>Force-pushing</h2><p>A normal push adds commits. A force-push rewrites a remote branch to match different history and can discard another person's commits. Do not force-push <code>main</code>, a shared branch, or a branch someone else is using. On your own unmerged feature branch, you may encounter it after rebasing or editing old commits; prefer <code>git push --force-with-lease</code>, which refuses if the remote moved unexpectedly. If unsure, do not force-push—add a new corrective commit or ask the project maintainer.</p>
<h2>Undo choices</h2><ul><li>Uncommitted edit: <code>git restore PATH</code> discards that file's unstaged changes—review first.</li><li>Staged by mistake: <code>git restore --staged PATH</code> keeps the edit but removes it from the next commit.</li><li>Published bad commit: <code>git revert COMMIT_ID</code> creates a new commit that reverses it without rewriting history.</li><li>Bad pull/deploy: use the pre-update rollback branch documented on each application page.</li></ul>"""

PAGES["Forking and Contributing on GitHub"] = f"""<h2>Who to ask before a large redesign</h2>
<p>Ask the original project's maintainers—the people listed in its README/CONTRIBUTING file or active in its GitHub Issues and Discussions. Open an issue or discussion describing the problem, proposed direction, scope, and alternatives before spending substantial time. For Jeffrey's own repositories, use the <a href="{PROFILE}">jeffavery profile</a> and its repository issue tracker.</p>
<h2>Create and clone a fork</h2><ol><li>Read the original README, license, CONTRIBUTING guide, code of conduct, security policy, open issues, and recent pull requests.</li><li>Select <strong>Fork</strong> on GitHub and choose <a href="{PROFILE}">jeffavery</a> as the owner.</li><li>Clone Jeffrey's fork and register the original project separately.</li></ol>
<pre><code># Clone Jeffrey's copy. Replace PROJECT with the real repository name.
git clone https://github.com/jeffavery/PROJECT.git
cd PROJECT

# Name the original project \"upstream\". Replace ORIGINAL-OWNER.
git remote add upstream https://github.com/ORIGINAL-OWNER/PROJECT.git

# Verify: origin should show jeffavery; upstream should show the original owner.
git remote -v
git fetch upstream --prune</code></pre>
<h2>Origin, upstream, and branches</h2><p><code>origin</code> is the conventional nickname Git gives the repository you cloned—Jeffrey's writable fork. <code>upstream</code> is the nickname you add for the original community project, normally read-only for you. <code>main</code> should remain a clean copy that is easy to synchronize. Each change gets its own feature branch so it can be reviewed, updated, or discarded independently.</p>
<pre><code># Synchronize Jeffrey's main branch with the original project.
git switch main
git fetch upstream --prune
git merge --ff-only upstream/main
git push origin main

# Start one focused change without altering main directly.
git switch -c fix/short-description

# Edit/test, then review and publish to Jeffrey's fork.
git diff --check
git diff
git add path/to/file
git diff --cached --name-status
git commit -m "Fix concise description"
git push -u origin fix/short-description</code></pre>
<h2>Open the pull request—this is the next, separate step</h2><ol><li>Open Jeffrey's fork on GitHub. GitHub usually shows a <strong>Compare &amp; pull request</strong> button for the new branch.</li><li>Confirm the base repository is the original project and the base branch is its requested default branch. The head repository should be <code>jeffavery/PROJECT</code> and the compare branch should be your feature branch.</li><li>Describe the problem, why this approach was chosen, exactly how it was tested, and any configuration, data, upgrade, or compatibility impact.</li><li>Review Files changed for accidental files and secrets, then submit the pull request.</li><li>When maintainers request changes, edit the same local branch, commit, and run <code>git push</code>. The pull request updates automatically; do not open another one.</li></ol>
<p>For a suspected vulnerability or exposed secret, do not open a public issue. Use the repository's Security tab/policy or the maintainer's stated private contact method.</p>
{GIT_SAFETY}
<h2>After the pull request is merged</h2><pre><code># Refresh main from the original project.
git switch main
git fetch upstream --prune
git merge --ff-only upstream/main
git push origin main

# Remove the completed local and remote feature branches.
git branch -d fix/short-description
git push origin --delete fix/short-description</code></pre>"""

PAGES["Container Troubleshooting"] = BACKUP_CHECK + COMMON_TROUBLE

PAGES["Application Inventory"] = """<h2>Purpose and status</h2>
<p>This is the quick index for applications hosted on ShopDocker. It records the runtime name, access path, deployment source, and persistent-data boundary. Last reconciled with Docker and the active Caddyfile on 2026-09-17.</p>
<h2>Core administration</h2>
<ul>
<li><strong>Caddy:</strong> <code>caddy</code>; project <code>/opt/docker/caddy</code>; ports 80/443; public entry point for proxied services.</li>
<li><strong>Caddy Manager:</strong> <code>caddy-manager</code>; <a href="https://caddymanager.jeffavery.com/">caddymanager.jeffavery.com</a>; source <code>/opt/docker/portainer/data/compose/1</code>; manages Caddyfile and local backups.</li>
<li><strong>Portainer:</strong> <code>portainer</code>; <a href="https://portainer1.jeffavery.com/">portainer1.jeffavery.com</a>; data <code>/opt/docker/portainer/data</code>.</li>
<li><strong>BasicWiki:</strong> <code>basicwiki</code>; <a href="https://wiki.jeffavery.com/">wiki.jeffavery.com</a>; project/data <code>/opt/docker/basicwiki</code>.</li>
</ul>
<h2>Custom and forked applications</h2>
<ul>
<li><strong>Links:</strong> <code>links</code>; <a href="https://links.jeffavery.com/">links.jeffavery.com</a>; project <code>/opt/docker/links</code>; data <code>/opt/docker/links/data</code>.</li>
<li><strong>MeTube:</strong> <code>metube</code>; <a href="https://mtd.jeffavery.com/">mtd.jeffavery.com</a>; project <code>/opt/docker/metube</code>; media <code>/mnt/tubearchiver/metube</code>.</li>
<li><strong>Web Portal:</strong> <code>web-portal-dev</code>; project <code>/opt/docker/web-portal-dev</code>; host port 8788; data subdirectory mounted into the container.</li>
<li><strong>Network Device Directory:</strong> <code>network-directory</code>; <a href="https://network.jeffavery.com/">network.jeffavery.com</a>; project/data <code>/opt/docker/network-directory</code>; host networking.</li>
<li><strong>PixelPurge:</strong> <code>pixelpurge-pixelpurge-1</code>; project <code>/opt/docker/pixelpurge</code>; loopback port 8080; named data volume plus read-only media.</li>
<li><strong>Seedbox Storage Usage:</strong> <code>gigarapid-bandwidth</code>; <a href="https://storage.jeffavery.com/">storage.jeffavery.com</a>; host port 8787; named data volume; original deployment definition still needs recovery.</li>
<li><strong>BenchCalc:</strong> <code>benchcalc</code>; <a href="https://jeffavery.com/benchcalc/">jeffavery.com/benchcalc</a>; project <code>/opt/docker/benchcalc</code>; no persistent mount.</li>
<li><strong>Shop Reference:</strong> <code>shop-reference</code>; <a href="https://machining.jeffavery.com/">machining.jeffavery.com</a>; project <code>/opt/docker/shop-reference</code>; no persistent mount.</li>
</ul>
<h2>Packaged applications</h2>
<ul>
<li><strong>TubeArchivist:</strong> <code>tubearchivist</code>, <code>archivist-redis</code>, and <code>archivist-es</code>; <a href="https://yta.jeffavery.com/">yta.jeffavery.com</a>; state under <code>/opt/docker/tubearchivist</code>; media under <code>/mnt/tubearchiver</code>.</li>
<li><strong>Manyfold:</strong> <code>manyfold</code>; <a href="https://3dprint.jeffavery.com/">3dprint.jeffavery.com</a>; configuration <code>/opt/docker/manyfold/config</code>; models <code>/mnt/3dprints</code>.</li>
<li><strong>Immich:</strong> <code>immich_server</code> plus machine learning, PostgreSQL, and Valkey; host port 2283; project <code>/opt/docker/immich</code>; writable NAS library <code>/mnt/immich-photos</code>.</li>
<li><strong>ConvertX:</strong> <code>convertx</code>; <a href="https://convert.jeffavery.com/">convert.jeffavery.com</a>; data <code>/opt/docker/convertx/data</code>.</li>
<li><strong>NetAlertX:</strong> <code>netalertx</code>; <a href="https://monitor.jeffavery.com/">monitor.jeffavery.com</a>; config/database under <code>/opt/docker/netalertx</code>; host networking.</li>
<li><strong>Navidrome:</strong> <code>navidrome</code>; <a href="https://navidrome.jeffavery.com/">navidrome.jeffavery.com</a>; data <code>/opt/docker/navidrome/data</code>; read-only music <code>/mnt/music</code>.</li>
<li><strong>Plex:</strong> <code>plex</code>; <a href="https://plex.jeffavery.com/">plex.jeffavery.com</a>; config <code>/opt/docker/plex/config</code>; media under multiple <code>/mnt</code> paths. It was stopped during the 2026-09-17 inventory.</li>
</ul>
<h2>Runtime audit commands</h2>
<pre><code># Show every container, including stopped containers.
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

# Show Compose project/source labels and mounts for one container.
docker inspect CONTAINER --format \
'project={{index .Config.Labels "com.docker.compose.project"}} workdir={{index .Config.Labels "com.docker.compose.project.working_dir"}}
{{range .Mounts}}{{.Source}} -> {{.Destination}} ({{.Type}})
{{end}}'

# Compare public hostnames and upstreams with the inventory.
grep -nE '^[A-Za-z0-9.-]+ \\{|reverse_proxy' /opt/docker/caddy/Caddyfile</code></pre>
<p>When adding or removing an application, update this inventory, its individual application page, the network/service map, and the maintenance history together.</p>"""

PAGES["Disaster Recovery Checklist"] = """<h2>Goal</h2>
<p>Recover ShopDocker safely without overwriting the only good copy. This checklist assumes a completed ShopDocker archive exists. External media/NAS libraries require their own recovery plan.</p>
<h2>1. Stabilize and record</h2>
<pre><code># Do not start applications yet. Record host identity, disks, mounts, and Docker state.
hostnamectl
lsblk -f
findmnt
docker ps -a

# Confirm the backup share is mounted from the expected SMB source.
findmnt /mnt/shopdocker-backup
mountpoint /mnt/shopdocker-backup
df -h /mnt/shopdocker-backup</code></pre>
<h2>2. Select and validate an archive</h2>
<pre><code># List completed archives newest first. Do not choose an .incomplete file.
ls -1t /mnt/shopdocker-backup/ShopDocker_*.tar.gz

# Set the chosen archive and validate compressed-file integrity.
ARCHIVE="/mnt/shopdocker-backup/ShopDocker_YYYY-MM-DD_HH-MM-SS.tar.gz"
gzip -t "$ARCHIVE"

# Inspect top-level members without displaying secret contents.
tar -tzf "$ARCHIVE" | head -100</code></pre>
<h2>3. Stage instead of overwriting</h2>
<pre><code># Create an isolated restore area with root-only access.
RESTORE_STAGE="$(mktemp -d /tmp/shopdocker-restore-XXXXXX)"
sudo chmod 700 "$RESTORE_STAGE"

# Extract with numeric ownership, ACLs, and extended attributes preserved.
sudo tar --numeric-owner -xpf "$ARCHIVE" -C "$RESTORE_STAGE" --xattrs --acls

# Confirm expected application, system, and volume paths exist.
sudo test -d "$RESTORE_STAGE/opt/docker"
sudo find "$RESTORE_STAGE/opt/docker" -maxdepth 2 -type f \
  -name 'compose.y*ml' -o -name 'docker-compose.y*ml'</code></pre>
<h2>4. Rebuild host prerequisites</h2>
<ol><li>Install Docker Engine and the Compose plugin.</li><li>Restore or recreate required users/groups with the expected numeric IDs.</li><li>Review staged <code>etc/fstab</code>, SMB credential files, SSH host material, and Tailscale state before copying. Do not print secrets.</li><li>Restore mount definitions and mount NAS/media/backup shares.</li><li>Create the external Docker network <code>proxy</code> if absent.</li></ol>
<pre><code># Create the external proxy network only when it does not already exist.
docker network inspect proxy >/dev/null 2>&1 || docker network create proxy

# Verify every required host mount before applications start.
findmnt /mnt/shopdocker-backup
findmnt /mnt/tubearchiver
findmnt /mnt/3dprints
findmnt /mnt/music</code></pre>
<h2>5. Preserve the damaged/current state</h2>
<pre><code># Stop running containers before replacing application data.
RUNNING_CONTAINERS="$(docker ps -q)"
test -z "$RUNNING_CONTAINERS" || docker stop $RUNNING_CONTAINERS

# Preserve any current application tree as a rollback.
sudo cp -a /opt/docker "/opt/docker.before-restore-$(date +%Y%m%d-%H%M%S)"</code></pre>
<p>The conditional stop safely does nothing when no containers are running. Verify the destination has enough space before copying the full tree.</p>
<h2>6. Restore configuration and application data</h2>
<pre><code># Copy the staged application tree into the expected location.
sudo mkdir -p /opt/docker
sudo cp -a "$RESTORE_STAGE/opt/docker/." /opt/docker/

# Recreate named volumes before copying their staged data.
docker volume create pixelpurge_pixelpurge-data
docker volume create gigarapid-bandwidth-data

# Review volume paths and ownership before copying.
sudo find "$RESTORE_STAGE/var/lib/docker/volumes" -maxdepth 3 -type d -print</code></pre>
<p>Use the PixelPurge and Seedbox Storage Usage pages for their volume-specific copy commands. Restore the backup script and systemd units only after reviewing staged paths, ownership, and permissions.</p>
<h2>7. Start in dependency order</h2>
<ol><li>Mounts and Docker network.</li><li>Caddy.</li><li>Caddy Manager, which depends on Caddy's network namespace.</li><li>Databases/dependencies such as TubeArchivist Elasticsearch and Redis.</li><li>Applications.</li><li>Reverse-proxy validation.</li></ol>
<pre><code># Example: validate and start Caddy first.
cd /opt/docker/caddy
docker compose up -d --build
docker compose ps
docker compose logs --tail=100

# Start TubeArchivist's complete dependency group.
cd /opt/docker/tubearchivist
docker compose up -d
docker compose ps
docker compose logs --tail=150</code></pre>
<h2>8. Validate before declaring recovery complete</h2>
<pre><code># Confirm container and health state.
docker ps -a

# Validate active Caddy configuration.
docker exec caddy caddy validate --config /etc/caddy/Caddyfile

# Confirm backup scheduling, but enable it only after paths are correct.
sudo systemctl daemon-reload
sudo systemctl status shopdocker-backup.timer</code></pre>
<p>Open every critical application, verify existing data, and perform one normal workflow. A readable archive and running containers are not a restore test. Schedule a controlled test restore on an isolated host when practical.</p>
<h2>Known recovery gaps</h2>
<ul><li>No full application restore has been proven yet.</li><li>External media under <code>/mnt</code> is outside the ShopDocker archive.</li><li>Docker images and network definitions must be rebuilt or pulled.</li><li>Seedbox Storage Usage lacks a recovered Compose/deployment definition.</li><li>Backup-share ACLs and encryption at rest remain unverified.</li></ul>"""

PAGES["Network and Service Map"] = """<h2>Request path</h2>
<pre><code>LAN or Tailscale client
        |
        | DNS hostname (Pi-hole/local DNS where configured)
        v
ShopDocker 192.168.12.168
        |
        +-- TCP 80/443 --> Caddy container
                              |
                              +-- Docker network \"proxy\"
                              |     +-- links:80
                              |     +-- benchcalc:80
                              |     +-- shop-reference:80
                              |     +-- navidrome:4533
                              |
                              +-- ShopDocker host IP/ports
                              |     +-- wiki -> 8085
                              |     +-- network -> 8088
                              |     +-- storage -> 8787
                              |     +-- TubeArchivist -> 8010
                              |     +-- MeTube -> 8081
                              |     +-- ConvertX -> 3000
                              |     +-- NetAlertX -> 20211
                              |     +-- Manyfold -> 3214
                              |     +-- Immich -> 2283
                              |     +-- Portainer -> 9000
                              |
                              +-- localhost/network namespace
                              |     +-- Caddy Manager -> 127.0.0.1:8080
                              |
                              +-- other LAN devices
                                    +-- Plex host service -> 32400
                                    +-- Home Assistant house -> 192.168.12.152:8123
                                    +-- Home Assistant shop -> 192.168.12.181:8123
                                    +-- Pi-hole/DNS, NAS, switch, and BirdMic</code></pre>
<h2>Storage and backup path</h2>
<pre><code>Containers
   +-- Bind data under /opt/docker ------------------+
   +-- PixelPurge named volume ----------------------+--> daily backup script
   +-- Seedbox Storage Usage named volume -----------+          |
   +-- selected /etc and Tailscale files ------------+          v
                                                        /mnt/shopdocker-backup
                                                        SMB: //shopserver/ShopDockerBackup

External libraries (not in ShopDocker archive)
   +-- /mnt/tubearchiver  --> TubeArchivist + MeTube
   +-- /mnt/3dprints     --> Manyfold
   +-- /mnt/music        --> Navidrome + Plex
   +-- /mnt/immich-photos --> Immich (writable photo library)
   +-- other /mnt media  --> Plex / PixelPurge</code></pre>
<h2>Important Docker network patterns</h2>
<ul><li><strong>proxy:</strong> Caddy can address attached services by container/service name.</li><li><strong>host networking:</strong> Network Device Directory, NetAlertX, and Plex use the host network; Caddy reaches their host ports.</li><li><strong>default project networks:</strong> BasicWiki, Manyfold, ConvertX, MeTube, PixelPurge, and TubeArchivist use isolated Compose networks and are reached through published host ports where configured.</li><li><strong>Caddy Manager:</strong> shares Caddy's network namespace; start Caddy before Caddy Manager after an outage.</li></ul>
<h2>Trace a failing hostname</h2>
<pre><code># Find the hostname and configured upstream.
grep -n -A12 'HOSTNAME' /opt/docker/caddy/Caddyfile

# Check Caddy and the target container.
docker ps --filter name=caddy
docker ps -a --filter name=TARGET_CONTAINER
docker logs --tail=100 TARGET_CONTAINER

# For container-name upstreams, compare network membership.
docker inspect --format='{{json .NetworkSettings.Networks}}' caddy
docker inspect --format='{{json .NetworkSettings.Networks}}' TARGET_CONTAINER

# Validate Caddy configuration without changing it.
docker exec caddy caddy validate --config /etc/caddy/Caddyfile</code></pre>
<p>This is a logical service map, not a complete physical network diagram. Update it when a hostname, port, Docker network, host address, or storage mount changes.</p>"""

PAGES["Secrets Management"] = """<h2>Design</h2>
<p>Bitwarden cloud Secrets Manager is the authoritative copy of ShopDocker application credentials. The Docker host keeps owner-only runtime files so ordinary starts and automatic restarts do not depend on internet or Bitwarden availability.</p>
<ul><li>Organization: <code>ShopDocker</code>.</li><li>Project: <code>ShopDocker Production</code>.</li><li>Machine account: <code>ShopDocker Host</code>, normally <strong>Can read</strong>.</li><li>CLI: <code>/usr/local/bin/bws</code>.</li><li>Local tools: <code>/opt/docker/secrets-tools</code>.</li></ul>
<p>Never put a token or secret value in this wiki, chat, Git, shell history, or command-line argument.</p>
<h2>Check synchronization</h2>
<pre><code># Compare the 13 expected Bitwarden entries with running containers.
# Values are never displayed or changed.
/opt/docker/secrets-tools/refresh-runtime-secrets --check</code></pre>
<p>Healthy output reports thirteen <code>MATCH</code> lines. <code>DIFFERENT</code> means Bitwarden and the running container disagree; determine which value is intended before applying anything. <code>MISSING_RUNTIME</code> means the container is absent or lacks the expected variable.</p>
<h2>Apply an intentional rotation or restore</h2>
<ol><li>Confirm a current ShopDocker backup or another rollback path.</li><li>Change the value in Bitwarden as a human administrator.</li><li>Run check mode and expect <code>DIFFERENT</code> for only the intended entry.</li><li>Run the apply command below. It creates protected rollback copies, rewrites supported owner-only runtime files, validates Compose, and does not restart containers.</li><li>Review the result, then recreate only the affected application and test its normal workflow.</li></ol>
<pre><code># Stage supported runtime files from Bitwarden; no automatic restart.
/opt/docker/secrets-tools/refresh-runtime-secrets --apply

# Recreate only the affected application after reviewing the result.
cd /opt/docker/APPLICATION
docker compose up -d
docker compose ps
docker compose logs --tail=100</code></pre>
<p>Caddy Manager and PixelPurge use restricted runtime files. Check mode includes them, but apply mode deliberately does not rewrite them. Confirm their exact file ownership and target before handling either separately.</p>
<h2>Replace the machine access token</h2>
<ol><li>Create a replacement access token for <code>ShopDocker Host</code>. Keep the machine account at <strong>Can read</strong>.</li><li>Use Bitwarden's one-time Copy control. Do not paste the token into chat.</li><li>From local Windows PowerShell, pipe the clipboard through SSH using the command below.</li><li>Confirm validation succeeds, run check mode, and revoke the previous token.</li></ol>
<pre><code># Run from local Windows PowerShell, not inside the SSH session.
Get-Clipboard | ssh jeffrey@192.168.12.168 /opt/docker/secrets-tools/store-access-token</code></pre>
<h2>Local permissions and backup</h2>
<ul><li><code>/opt/docker/secrets-tools/private</code>: mode 0700.</li><li>Access-token and state files: mode 0600.</li><li>Runtime <code>.env</code>/<code>stack.env</code> files: mode 0600 and excluded from Git.</li><li>The daily ShopDocker archive contains these files and is not encrypted. Protect the NAS share and never publish an archive.</li></ul>"""

PAGES["Maintenance History"] = """<h2>How to use this page</h2>
<p>Add one dated entry after a confirmed deployment, configuration change, incident recovery, backup test, or rollback. Record what changed, how it was validated, and anything still unverified. Never include secret values.</p>
<h2>2026-09-29 — Network Device Directory DNS research</h2>
<ul><li>Added an automatic background web-research fallback when both a completed Deep Scan and DNS analysis are inconclusive.</li><li>Research submits only up to three DNS domain names, caches findings by domain, and saves a cited identity suggestion, confidence, summary, and evidence.</li><li>Added a dedicated OpenAI service-account key to Bitwarden and the shared owner-only runtime-secret refresh workflow; all thirteen managed secrets matched their running containers.</li><li>Verified end to end with <code>192.168.12.124</code>: 38 requests to <code>us-east-1.x-sense-iot.com</code> produced a high-confidence X-Sense smart-home safety-device correlation with four sources, without claiming an unsupported exact model.</li><li>The previous application image remains tagged <code>network-directory-network-directory:pre-dns-research</code> for rollback.</li></ul>
<h2>2026-09-20 — Immich</h2>
<ul><li>Deployed the official Immich Compose stack on host port 2283 with server, machine-learning, PostgreSQL, and Valkey services.</li><li>Created a dedicated writable NAS photo mount at <code>/mnt/immich-photos</code> and connected it to Immich as <code>/external/photos</code>.</li><li>Stored the NAS password in Bitwarden and retained a root-only runtime credential file; no secret values are documented.</li><li>Validated all services healthy, local API ping HTTP 200, and a create/delete test through the external library.</li><li>External photos remain outside the ShopDocker archive; full restore coverage of the new root-only credential file still needs explicit backup-script verification.</li></ul>
<h2>2026-09-17 — Bitwarden secrets management</h2>
<ul><li>Installed checksum-verified Bitwarden Secrets Manager CLI 2.1.0 and jq 1.7.</li><li>Created a read-only ShopDocker machine-account workflow and imported twelve active application credentials.</li><li>Removed inline secrets from ConvertX, Manyfold, and Navidrome Compose files; protected local runtime caches remain available for offline starts.</li><li>Added protected rollback copies and read-only check/apply tooling. All twelve Bitwarden entries matched the running containers.</li><li>No containers were restarted; Caddy Manager and PixelPurge remain deliberate restricted-file exceptions for automated apply.</li></ul>
<h2>2026-09-17 — BasicWiki operations documentation</h2>
<ul><li>Added section rename/edit capability and deployed it.</li><li>Created detailed GitHub/application operating guides and reconciled them against Docker and Caddy.</li><li>Expanded to 21 pages, then added Application Inventory, Disaster Recovery Checklist, Network and Service Map, and Maintenance History.</li><li>Validated representative pages locally and preserved pre-change database copies.</li><li>Remaining: source changes are not yet committed/pushed; full application restores remain untested.</li></ul>
<h2>2026-09-16 — Manyfold and ConvertX</h2>
<ul><li>Deployed ConvertX at <code>convert.jeffavery.com</code> with persistent data under <code>/opt/docker/convertx/data</code>.</li><li>Deployed Manyfold at <code>3dprint.jeffavery.com</code>; configuration under <code>/opt/docker/manyfold/config</code> and model library at <code>/mnt/3dprints</code>.</li><li>Confirmed HTTPS access through Caddy.</li></ul>
<h2>2026-09-15 — Media applications</h2>
<ul><li>Deployed customized MeTube image on host port 8081.</li><li>Deployed TubeArchivist with Redis and Elasticsearch on host port 8010.</li><li>Recorded that <code>/mnt/tubearchiver</code> media is outside the ShopDocker configuration backup.</li></ul>
<h2>2026-09-13 — Shop Reference</h2>
<ul><li>Deployed repository <code>jeffavery/shop-reference</code> as a static nginx container.</li><li>Configured Caddy upstream <code>shop-reference:80</code>.</li><li>Confirmed container health and local Caddy reachability; DNS/certificate verification was pending at that time.</li></ul>
<h2>2026-09-11 — Backup audit and recovery work</h2>
<ul><li>Audited the daily ShopDocker backup, destination, retention, and coverage.</li><li>Added explicit PixelPurge volume and installed backup-unit coverage.</li><li>Added locking, incomplete-file publication, archive validation, dependency-aware restart retry, and final container-state checks.</li><li>A live run exposed Caddy/Caddy Manager restart order; the archive was validated/promoted manually and service state restored.</li><li>The later dependency-retry version passed syntax and mocked tests but has not completed a fully verified live backup/restore cycle.</li></ul>
<h2>Entry template</h2>
<pre><code>YYYY-MM-DD — Short change name

Changed:
- Exact application/configuration affected.

Validated:
- Commands, health checks, and browser workflow that passed.

Rollback:
- Backup path, Git commit, image tag, or preserved directory.

Still unverified:
- Anything not actually tested.</code></pre>"""

def plain(html):
    html = re.sub(r"<br\s*/?>|</(?:p|h1|h2|h3|li|pre)>", " ", html, flags=re.I)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip()

def main():
    db = sqlite3.connect(DB_PATH)
    section = db.execute("SELECT id FROM sections WHERE slug='github'").fetchone()
    if not section:
        raise SystemExit("GitHub section not found")
    now = datetime.now().isoformat(timespec="seconds")
    with db:
        for title, html in PAGES.items():
            row = db.execute("SELECT id FROM pages WHERE section_id=? AND title=?", (section[0], title)).fetchone()
            if row:
                db.execute("UPDATE pages SET content_html=?,content_text=?,updated_at=? WHERE id=?", (html, plain(html), now, row[0]))
                continue
            base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            slug, n = base, 2
            while db.execute("SELECT 1 FROM pages WHERE slug=?", (slug,)).fetchone():
                slug, n = f"{base}-{n}", n + 1
            db.execute("INSERT INTO pages(section_id,slug,title,content_html,content_text,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (section[0], slug, title, html, plain(html), now, now))
    print(f"Seeded {len(PAGES)} GitHub pages")

if __name__ == "__main__":
    main()
