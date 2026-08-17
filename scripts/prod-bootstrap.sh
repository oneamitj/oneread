#!/bin/sh
# First-time production setup: the data directory, the first certificate, then
# the whole stack. Safe to run again — it skips the certificate if one is
# already there, so it doubles as "put this host back together".
#
#   cp .env.prod.example .env.prod && $EDITOR .env.prod
#   ./scripts/prod-bootstrap.sh            (or: make prod-init)
#
# Pass --force-cert to throw away the existing certificate and issue a new one.

set -eu

cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

COMPOSE_FILE=docker-compose.prod.yml
ENV_FILE=.env.prod

die() {
    printf '\n%s\n\n' "$1" >&2
    exit 1
}

say() {
    printf '\n==> %s\n' "$1"
}

compose() {
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
}

FORCE_CERT=0
for arg in "$@"; do
    case "$arg" in
        --force-cert) FORCE_CERT=1 ;;
        *) die "Unknown argument: $arg (only --force-cert is understood)" ;;
    esac
done

# --- what we were given -------------------------------------------------------

[ -f "$ENV_FILE" ] || die "No $ENV_FILE. Start with: cp .env.prod.example $ENV_FILE"

# `set -a` exports everything the file defines so the checks below can read it.
# docker compose reads the same file itself via --env-file; this is only so this
# script knows the domain.
set -a
# shellcheck disable=SC1090
. "./$ENV_FILE"
set +a

[ -n "${ONEREAD_DOMAIN:-}" ] || die "ONEREAD_DOMAIN is not set in $ENV_FILE."
[ -n "${CERTBOT_EMAIL:-}" ] || die "CERTBOT_EMAIL is not set in $ENV_FILE."
[ "${CERTBOT_EMAIL}" != "you@example.com" ] || \
    die "CERTBOT_EMAIL is still the example address. Put a real one in $ENV_FILE."

STAGING_ARG=""
if [ "${CERTBOT_STAGING:-0}" = "1" ]; then
    STAGING_ARG="--staging"
fi

CERT_DIR="/etc/letsencrypt/live/$ONEREAD_DOMAIN"

# --- the data directory -------------------------------------------------------
#
# The app runs as uid 10001 and ./data is a bind mount, so docker will not chown
# it for us: left alone, dockerd creates it root-owned and the app cannot write
# a single byte. Done through a throwaway container because that container is
# root even when you are not, so this needs no sudo.

say "Making sure ./data belongs to the app's user"
mkdir -p data
docker run --rm -v "$PWD/data:/data" --entrypoint sh nginx:1.29-alpine \
    -c 'chown -R 10001:10001 /data' >/dev/null

# --- the certificate ----------------------------------------------------------

have_cert() {
    compose run --rm --entrypoint sh certbot \
        -c "[ -s $CERT_DIR/fullchain.pem ]" >/dev/null 2>&1
}

if [ "$FORCE_CERT" = "0" ] && have_cert; then
    say "A certificate for $ONEREAD_DOMAIN already exists — leaving it alone"
else
    # nginx will not start without a certificate to open, and certbot cannot get
    # a certificate without nginx serving the challenge. A throwaway self-signed
    # pair breaks the circle: nginx starts on it, certbot replaces it, nginx
    # reloads. It is never served to anyone but the ACME check.
    say "Writing a placeholder certificate so nginx can start"
    compose run --rm --entrypoint sh certbot -c "
        set -e
        rm -rf $CERT_DIR
        mkdir -p $CERT_DIR
        openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
            -keyout $CERT_DIR/privkey.pem \
            -out $CERT_DIR/fullchain.pem \
            -subj '/CN=placeholder' 2>/dev/null
    "

    say "Starting nginx on the placeholder"
    compose up -d --no-deps nginx

    say "Removing the placeholder"
    compose run --rm --entrypoint sh certbot -c "
        rm -rf $CERT_DIR \
               /etc/letsencrypt/archive/$ONEREAD_DOMAIN \
               /etc/letsencrypt/renewal/$ONEREAD_DOMAIN.conf
    "

    if [ -n "$STAGING_ARG" ]; then
        say "Asking Let's Encrypt STAGING for a certificate (browsers will not trust it)"
    else
        say "Asking Let's Encrypt for a certificate for $ONEREAD_DOMAIN"
    fi
    # If this fails, the usual cause is DNS: the A record for the domain has to
    # point at this host and port 80 has to be reachable from the internet
    # before the challenge can be fetched.
    compose run --rm --entrypoint certbot certbot certonly \
        --webroot -w /var/www/certbot \
        -d "$ONEREAD_DOMAIN" \
        --email "$CERTBOT_EMAIL" \
        --agree-tos --no-eff-email --non-interactive \
        $STAGING_ARG

    say "Reloading nginx onto the real certificate"
    compose exec nginx nginx -s reload
fi

# --- everything else ----------------------------------------------------------
#
# The first build downloads the ~385 MB speech model into the image, so this is
# the slow part. After that the image is self-contained and never reaches out.

say "Building and starting the stack"
compose up -d --build

say "Up. https://$ONEREAD_DOMAIN"
if [ -n "$STAGING_ARG" ]; then
    printf '%s\n' "    That certificate is a staging one and browsers will refuse it."
    printf '%s\n' "    Set CERTBOT_STAGING=0 in $ENV_FILE and run this again with --force-cert."
fi
printf '%s\n' "    The app needs about ninety seconds to load the model before it answers."
printf '%s\n\n' "    Watch it come up:  make prod-logs"
