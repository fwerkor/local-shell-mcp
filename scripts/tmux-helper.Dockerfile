ARG ALPINE_VERSION=3.22
FROM alpine:${ALPINE_VERSION} AS builder

ARG TMUX_VERSION=3.5a
# Release asset ID and checksum are pinned to the same version.
ARG TMUX_ASSET_ID=197025443
ARG TMUX_SHA256=16216bd0877170dfcc64157085ba9013610b12b082548c7c9542cc0103198951

RUN apk add --no-cache \
    build-base \
    bison \
    ca-certificates \
    curl \
    libevent-dev \
    libevent-static \
    linux-headers \
    ncurses-dev \
    ncurses-static \
    pkgconf

WORKDIR /build
# GitHub release downloads and its API use different front doors. Fall back to
# the exact official asset when the release CDN is unavailable; both paths must
# pass the same pinned checksum before any source is extracted.
RUN (curl --retry 5 --retry-all-errors --retry-delay 2 --connect-timeout 15 --max-time 45 -fsSL "https://github.com/tmux/tmux/releases/download/${TMUX_VERSION}/tmux-${TMUX_VERSION}.tar.gz" -o tmux.tar.gz \
      || curl --retry 6 --retry-all-errors --retry-max-time 180 --connect-timeout 15 --max-time 45 -fsSL \
         -H 'Accept: application/octet-stream' "https://api.github.com/repos/tmux/tmux/releases/assets/${TMUX_ASSET_ID}" -o tmux.tar.gz) \
    && echo "${TMUX_SHA256}  tmux.tar.gz" | sha256sum -c - \
    && tar -xzf tmux.tar.gz

WORKDIR /build/tmux-${TMUX_VERSION}
RUN LIBEVENT_CFLAGS="$(pkg-config --cflags libevent)" \
    LIBEVENT_LIBS="$(pkg-config --static --libs libevent)" \
    LIBTINFO_CFLAGS="$(pkg-config --cflags ncursesw)" \
    LIBTINFO_LIBS="$(pkg-config --static --libs ncursesw)" \
    LDFLAGS="-static" \
    ./configure \
    && make -j"$(getconf _NPROCESSORS_ONLN)" \
    && strip tmux \
    && ./tmux -V \
    && mkdir -p /out \
    && install -m 0755 tmux /out/tmux

FROM scratch
COPY --from=builder /out/tmux /tmux
