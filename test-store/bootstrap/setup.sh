#!/bin/sh
set -eu
# Never enable shell tracing: passwords are supplied through the local environment.
attempt=0
while [ ! -f wp-config.php ]; do
  attempt=$((attempt + 1))
  if [ "$attempt" -gt 60 ]; then
    echo 'WordPress files were not initialized in time.' >&2
    exit 1
  fi
  sleep 1
done
if ! wp core is-installed >/dev/null 2>&1; then
  wp core install --url='https://localhost:8443' --title='Fictional Connector Lab' \
    --admin_user='lab-admin' --admin_password="$WP_ADMIN_PASSWORD" \
    --admin_email='lab-admin@example.invalid' --skip-email
fi
wp plugin install woocommerce --version=10.2.2 --activate
wp rewrite structure '/%postname%/' --hard
wp option update woocommerce_currency INR
wp eval-file /bootstrap/seed.php
