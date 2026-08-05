# Metabase on a Debian base, because the DuckDB driver cannot run on the official image.
#
# The official metabase/metabase image is built on Alpine Linux, which uses musl instead of
# glibc. The DuckDB driver ships a compiled native library built against glibc, so on the
# official image it either fails to load or crashes the whole Java process. That was
# confirmed here by trying it: adding libstdc++ and the gcompat shim to the Alpine container
# got the library to load and then the process died in native code. The driver's own
# documentation says the same thing, and this file follows the Debian-based recipe it
# recommends.
#
# The Metabase jar is downloaded from metabase.com rather than taken from a Docker image, so
# the only image needed is a plain Java runtime.
#
# Build and run from the repository root with metabase/start.sh.

FROM eclipse-temurin:21-jre-jammy

# Keep these in step with each other. The driver bundles its own copy of DuckDB, and a
# driver built against an older DuckDB cannot open a file written by a newer one — see the
# version table in metabase/README.md.
ARG METABASE_VERSION=0.62.7

ENV MB_PLUGINS_DIR=/home/metabase/plugins
# Metabase's own storage for saved questions and dashboards, mounted from the host so it
# survives the container being replaced.
ENV MB_DB_FILE=/home/metabase/app-data/metabase.db

RUN groupadd -r metabase && useradd -r -g metabase metabase \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /home/metabase/plugins /home/metabase/app-data /data \
    && chown -R metabase:metabase /home/metabase /data

WORKDIR /home/metabase

ADD --chown=metabase:metabase \
    https://downloads.metabase.com/v${METABASE_VERSION}/metabase.jar \
    /home/metabase/metabase.jar

# Copied from the repository rather than downloaded again, so the jar that was checked here
# is the jar that runs.
COPY --chown=metabase:metabase plugins/duckdb.metabase-driver.jar /home/metabase/plugins/

RUN chmod 755 /home/metabase/metabase.jar /home/metabase/plugins/duckdb.metabase-driver.jar

EXPOSE 3000
USER metabase

CMD ["java", "-jar", "/home/metabase/metabase.jar"]
